import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

from windowkeeper.errors import Unavailable, WindowkeeperError

MAX_FRAME = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class WriteEvidence:
    started: bool = False
    completed: bool = False


class AppServerClient:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._writer_lock = asyncio.Lock()
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    @classmethod
    async def spawn(
        cls,
        executable: str,
        *,
        cwd: str,
        environment: Mapping[str, str],
        timeout: float = 15,
    ) -> "AppServerClient":
        try:
            process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    executable,
                    "app-server",
                    cwd=cwd,
                    env=dict(environment),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                ),
                timeout,
            )
        except (OSError, TimeoutError) as error:
            raise Unavailable("CODEX_START_FAILED", "Codex app-server could not start") from error
        client = cls(process)
        try:
            await client.request(
                "initialize",
                {"clientInfo": {"name": "windowkeeper", "version": "0.1.0"}, "capabilities": {}},
                timeout=timeout,
            )
            await client.notify("initialized", {})
        except BaseException:
            await client.close()
            raise
        return client

    async def _read_loop(self) -> None:
        stdout = self.process.stdout
        if stdout is None:
            return
        try:
            while line := await stdout.readline():
                if len(line) > MAX_FRAME:
                    raise WindowkeeperError(
                        "CODEX_FRAME_TOO_LARGE", "Codex returned an oversized frame"
                    )
                try:
                    message = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise WindowkeeperError(
                        "CODEX_INVALID_FRAME", "Codex returned an invalid frame"
                    ) from error
                if not isinstance(message, dict):
                    continue
                if isinstance(message.get("id"), int) and "method" not in message:
                    future = self._pending.pop(message["id"], None)
                    if future and not future.done():
                        future.set_result(message)
                    continue
                try:
                    self._notifications.put_nowait(message)
                except asyncio.QueueFull as overflow:
                    del overflow
                    _ = self._notifications.get_nowait()
                    self._notifications.put_nowait(message)
        except BaseException as error:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            self._pending.clear()

    async def _drain_stderr(self) -> None:
        stderr = self.process.stderr
        if stderr is None:
            return
        while line := await stderr.readline():
            _ = line[:4096]

    async def request(
        self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float = 30
    ) -> tuple[dict[str, Any], WriteEvidence]:
        self._next_id += 1
        request_id = self._next_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        payload = (
            json.dumps(
                {"id": request_id, "method": method, "params": dict(params or {})},
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        evidence = WriteEvidence()
        stdin = self.process.stdin
        if stdin is None:
            raise Unavailable("CODEX_STDIN_CLOSED", "Codex transport is unavailable")
        try:
            async with self._writer_lock:
                evidence = WriteEvidence(started=True)
                stdin.write(payload)
                await stdin.drain()
                evidence = WriteEvidence(started=True, completed=True)
            response = await asyncio.wait_for(future, timeout)
        except BaseException:
            self._pending.pop(request_id, None)
            raise
        if error := response.get("error"):
            upstream_code = ""
            if isinstance(error, Mapping):
                upstream_code = str(error.get("code", "")).lower()
            if upstream_code in {"unauthorized", "authentication_required", "invalid_grant"}:
                raise WindowkeeperError(
                    "CODEX_AUTH_REQUIRED", "Codex authentication must be renewed"
                )
            raise WindowkeeperError(
                "CODEX_RPC_REJECTED", "Codex rejected the request"
            ) from RuntimeError(str(type(error)))
        result = response.get("result")
        return (result if isinstance(result, dict) else {}, evidence)

    async def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        stdin = self.process.stdin
        if stdin is None:
            raise Unavailable("CODEX_STDIN_CLOSED", "Codex transport is unavailable")
        payload = (
            json.dumps(
                {"method": method, "params": dict(params or {})}, separators=(",", ":")
            ).encode()
            + b"\n"
        )
        async with self._writer_lock:
            stdin.write(payload)
            await stdin.drain()

    async def notifications(self) -> AsyncIterator[dict[str, Any]]:
        while self.process.returncode is None:
            yield await self._notifications.get()

    async def close(self) -> None:
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 10)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in (self._reader_task, self._stderr_task):
            task.cancel()
        await asyncio.gather(self._reader_task, self._stderr_task, return_exceptions=True)
