import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .codex.adapter import CodexAdapter
from .codex.client import AppServerClient
from .config import Settings
from .ids import new_id
from .vault import Vault


@dataclass(slots=True)
class AccountRuntime:
    account_id: str
    generation_id: str
    root: Path
    client: AppServerClient
    adapter: CodexAdapter
    lock: asyncio.Lock
    idle_task: asyncio.Task[None] | None = None

    @property
    def codex_home(self) -> Path:
        return self.root / "codex-home"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"


class RuntimeManager:
    """Owns isolated account runtimes; callers only receive serialized adapters."""

    def __init__(self, settings: Settings, vault: Vault | None = None) -> None:
        self.settings = settings
        self.vault = vault
        self._runtimes: dict[str, AccountRuntime] = {}
        self._manager_lock = asyncio.Lock()
        self._start_semaphore = asyncio.Semaphore(settings.process_start_concurrency)

    def _tree(self, account_id: str, generation: str) -> Path:
        return self.settings.runtime_dir / "accounts" / account_id / generation

    def _prepare_tree(
        self, account_id: str, generation: str, payload: dict[str, Any] | None
    ) -> Path:
        root = self._tree(account_id, generation)
        for child in ("home", "codex-home", "tmp", "workspace"):
            path = root / child
            path.mkdir(parents=True, mode=0o700)
            os.chmod(path, 0o700)
        if payload:
            if not self.vault:
                raise RuntimeError("vault is unavailable")
            self.vault.materialize(payload, root / "codex-home")
        else:
            (root / "codex-home" / "config.toml").write_text(
                'cli_auth_credentials_store = "file"\nweb_search = "disabled"\n', encoding="utf-8"
            )
            os.chmod(root / "codex-home" / "config.toml", 0o600)
        return root

    async def start(self, account_id: str, payload: dict[str, Any] | None = None) -> AccountRuntime:
        async with self._manager_lock:
            if active := self._runtimes.get(account_id):
                if active.idle_task:
                    active.idle_task.cancel()
                    active.idle_task = None
                return active
            generation = new_id()
            root = self._prepare_tree(account_id, generation, payload)
            environment = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": str(root / "home"),
                "CODEX_HOME": str(root / "codex-home"),
                "TMPDIR": str(root / "tmp"),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "TZ": "UTC",
                "NO_COLOR": "1",
            }
            try:
                async with self._start_semaphore:
                    client = await AppServerClient.spawn(
                        self.settings.codex_executable,
                        cwd=str(root / "workspace"),
                        environment=environment,
                    )
            except BaseException:
                shutil.rmtree(root, ignore_errors=True)
                raise
            runtime = AccountRuntime(
                account_id, generation, root, client, CodexAdapter(client), asyncio.Lock()
            )
            self._runtimes[account_id] = runtime
            return runtime

    async def use(self, account_id: str, payload: dict[str, Any] | None = None) -> AccountRuntime:
        runtime = await self.start(account_id, payload)
        if runtime.idle_task:
            runtime.idle_task.cancel()
            runtime.idle_task = None
        return runtime

    def release_later(self, account_id: str) -> None:
        runtime = self._runtimes.get(account_id)
        if runtime and not runtime.idle_task:
            runtime.idle_task = asyncio.create_task(self._idle_stop(account_id))

    async def _idle_stop(self, account_id: str) -> None:
        try:
            await asyncio.sleep(self.settings.codex_idle_seconds)
            await self.stop(account_id)
        except asyncio.CancelledError as cancellation:
            del cancellation
            return

    async def stop(self, account_id: str) -> None:
        async with self._manager_lock:
            runtime = self._runtimes.get(account_id)
        if not runtime:
            return
        async with runtime.lock:
            async with self._manager_lock:
                if self._runtimes.get(account_id) is not runtime:
                    return
                self._runtimes.pop(account_id)
            if runtime.idle_task and runtime.idle_task is not asyncio.current_task():
                runtime.idle_task.cancel()
            await runtime.client.close()
            try:
                shutil.rmtree(runtime.root)
            except FileNotFoundError as missing:
                del missing
                return

    async def close(self) -> None:
        for account_id in list(self._runtimes):
            await self.stop(account_id)
