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
    params = message.get("params") or {}
    request_id = message.get("id")
    if request_id is None:
        continue
    if method == "initialize":
        send({"id": request_id, "result": {"serverInfo": {"name": "fake-codex"}}})
    elif method == "account/login/start":
        try:
            home.mkdir(parents=True, exist_ok=True)
            trace = home.parents[1] / ".fake-logins"
            login_number = (
                len(trace.read_text(encoding="utf-8").splitlines()) + 1 if trace.exists() else 1
            )
            with trace.open("a", encoding="utf-8") as stream:
                stream.write(f"login-{login_number}\n")
            (home / "auth.json").write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": {
                            "id_token": f"id-{login_number}",
                            "access_token": f"access-{login_number}",
                            "refresh_token": f"refresh-{login_number}",
                        },
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        except OSError:
            send({"id": request_id, "error": {"code": "credential_write_failed"}})
            continue
        login_id = f"login-{login_number}"
        send(
            {
                "id": request_id,
                "result": {
                    "loginId": login_id,
                    "verificationUrl": "https://auth.openai.test/device",
                    "userCode": "ABCD-EFGH",
                    "expiresAt": int(time.time() * 1000) + 60000,
                },
            }
        )
        send(
            {"method": "account/login/completed", "params": {"loginId": login_id, "success": True}}
        )
    elif method == "account/login/cancel":
        send({"id": request_id, "result": {}})
    elif method == "account/read":
        if params.get("refreshToken"):
            trace = home.parents[1] / ".fake-refreshes"
            refresh_number = (
                len(trace.read_text(encoding="utf-8").splitlines()) + 1 if trace.exists() else 1
            )
            with trace.open("a", encoding="utf-8") as stream:
                stream.write(f"refresh-{refresh_number}\n")
            auth = json.loads((home / "auth.json").read_text(encoding="utf-8"))
            auth["tokens"] |= {
                "id_token": f"fork-id-{refresh_number}",
                "access_token": f"fork-access-{refresh_number}",
                "refresh_token": f"fork-refresh-{refresh_number}",
            }
            (home / "auth.json").write_text(
                json.dumps(auth, separators=(",", ":")), encoding="utf-8"
            )
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
    elif method == "model/list":
        send(
            {
                "id": request_id,
                "result": {
                    "data": [
                        {
                            "model": "gpt-5.6-sol",
                            "hidden": False,
                            "inputModalities": ["text", "image"],
                            "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
                        },
                        {
                            "model": "gpt-5.4-mini",
                            "hidden": False,
                            "inputModalities": ["text"],
                            "supportedReasoningEfforts": [
                                {"reasoningEffort": "minimal"},
                                {"reasoningEffort": "low"},
                            ],
                        },
                    ],
                    "nextCursor": None,
                },
            }
        )
    elif method == "thread/start":
        if params.get("model") != "gpt-5.4-mini" or params.get("serviceTier") != "default":
            send({"id": request_id, "error": {"code": "expensive_model"}})
            continue
        send(
            {
                "id": request_id,
                "result": {
                    "thread": {"id": "thread-1"},
                    "model": "gpt-5.4-mini",
                    "serviceTier": "default",
                },
            }
        )
    elif method == "turn/start":
        if (
            params.get("model") != "gpt-5.4-mini"
            or params.get("effort") != "minimal"
            or params.get("serviceTier") != "default"
        ):
            send({"id": request_id, "error": {"code": "expensive_turn"}})
            continue
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
