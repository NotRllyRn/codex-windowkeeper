#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

if "--version" in sys.argv:
    print("codex-cli 0.145.0")
    raise SystemExit(0)

home = Path(os.environ["CODEX_HOME"])


def send(value: dict[str, Any]) -> None:
    print(json.dumps(value, separators=(",", ":")), flush=True)


def marker(suffix: str) -> bool:
    try:
        return Path(__file__).with_suffix(suffix).exists()
    except OSError:
        return False


for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        continue
    if method == "initialize":
        send({"id": request_id, "result": {"serverInfo": {"name": "fake-codex"}}})
    elif method == "account/login/start":
        try:
            home.mkdir(parents=True, exist_ok=True)
            (home / "auth.json").write_text('{"access_token":"fixture"}', encoding="utf-8")
        except OSError:
            send({"id": request_id, "error": {"code": "credential_write_failed"}})
            continue
        send(
            {
                "id": request_id,
                "result": {
                    "loginId": "login-1",
                    "verificationUrl": "https://auth.openai.test/device",
                    "userCode": "ABCD-EFGH",
                    "expiresAt": int(time.time() * 1000) + 60000,
                },
            }
        )
        send(
            {"method": "account/login/completed", "params": {"loginId": "login-1", "success": True}}
        )
    elif method == "account/login/cancel":
        send({"id": request_id, "result": {}})
    elif method == "account/read":
        send(
            {
                "id": request_id,
                "result": {
                    "account": {
                        "email": "owner@example.test",
                        "planType": "pro",
                        "workspaceId": os.environ.get("FAKE_CODEX_WORKSPACE", "workspace-1"),
                    }
                },
            }
        )
    elif method == "account/rateLimits/read":
        if marker(".auth-error"):
            send({"id": request_id, "error": {"code": "unauthorized"}})
            continue
        send(
            {
                "id": request_id,
                "result": {
                    "rateLimitsByLimitId": {
                        "codex": {
                            "windows": [
                                {
                                    "name": "short",
                                    "usedPercent": 22,
                                    "windowDurationMins": 300,
                                    "resetsAt": int(time.time()) + 3600,
                                },
                                {
                                    "name": "weekly",
                                    "usedPercent": 41,
                                    "windowDurationMins": 10080,
                                    "resetsAt": int(time.time()) + 86400,
                                },
                            ]
                        }
                    }
                },
            }
        )
    elif method == "thread/start":
        send({"id": request_id, "result": {"thread": {"id": "thread-1"}}})
    elif method == "turn/start":
        send({"id": request_id, "result": {"turn": {"id": "turn-1"}}})
        send({"method": "item/agentMessage/delta", "params": {"turnId": "turn-1", "delta": "OK"}})
        send({"method": "turn/completed", "params": {"turnId": "turn-1"}})
    elif method == "thread/read":
        turns = []
        if marker(".reconcile-ok"):
            turns = [
                {
                    "id": "turn-1",
                    "status": "completed",
                    "items": [{"type": "agentMessage", "text": "OK"}],
                }
            ]
        send(
            {
                "id": request_id,
                "result": {"thread": {"id": "thread-1", "turns": turns}},
            }
        )
    else:
        send({"id": request_id, "error": {"code": -32601, "message": "unknown"}})
