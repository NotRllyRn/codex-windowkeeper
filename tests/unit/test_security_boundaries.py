import hashlib
from collections.abc import AsyncIterator
from urllib.parse import quote

import pytest

from windowkeeper.errors import WindowkeeperError
from windowkeeper.redaction import redact, sanitize_url
from windowkeeper.services import (
    ApplicationServices,
    browser_contract,
    validate_callback,
    verify_same_identity,
)


def test_browser_callback_contract_and_state() -> None:
    redirect = "http://localhost:1455/auth/callback"
    auth = f"https://auth.openai.test/start?redirect_uri={quote(redirect, safe='')}&state=expected"
    contract = browser_contract(auth, (1455, 1457))
    callback = validate_callback(f"{redirect}?code=accepted&state=expected", contract)
    assert "code=accepted" in callback
    with pytest.raises(WindowkeeperError) as caught:
        validate_callback(f"{redirect}?code=accepted&state=wrong", contract)
    assert caught.value.code == "BROWSER_CALLBACK_STATE_MISMATCH"
    assert contract.state_hash == hashlib.sha256(b"expected").digest()
    with pytest.raises(WindowkeeperError) as oversized:
        browser_contract(auth + "&padding=" + "x" * 17_000, (1455, 1457))
    assert oversized.value.code == "CODEX_BROWSER_AUTH_CONTRACT_CHANGED"


@pytest.mark.asyncio
async def test_activation_rejects_any_tool_item() -> None:
    async def notifications() -> AsyncIterator[dict[str, object]]:
        yield {
            "method": "item/started",
            "params": {
                "turnId": "turn-1",
                "item": {"type": "commandExecution", "id": "unsafe-item"},
            },
        }

    services = object.__new__(ApplicationServices)
    with pytest.raises(WindowkeeperError) as caught:
        await services._await_turn(notifications(), "turn-1")
    assert caught.value.code == "ACTIVATION_SAFETY_VIOLATION"


def test_export_login_must_match_the_managed_identity() -> None:
    managed = {"account": {"email": "Owner@Example.test", "workspaceId": "workspace-1"}}
    verify_same_identity(
        managed, {"account": {"email": "owner@example.test", "workspaceId": "workspace-1"}}
    )
    with pytest.raises(WindowkeeperError) as caught:
        verify_same_identity(
            managed, {"account": {"email": "other@example.test", "workspaceId": "workspace-1"}}
        )
    assert caught.value.code == "AUTH_EXPORT_IDENTITY_MISMATCH"
    with pytest.raises(WindowkeeperError):
        verify_same_identity(
            managed, {"account": {"email": "owner@example.test", "workspaceId": "workspace-2"}}
        )


def test_redaction_is_recursive_and_sanitizes_urls() -> None:
    value = redact(
        {
            "authorization": "Bearer secret",
            "nested": {
                "message": "failure at https://localhost:1455/auth/callback?code=secret&state=private",
                "token_shape": "sk-abcdefghijklmnopqrst",
                "url": "https://example.test/x?code=secret#fragment",
            },
        }
    )
    assert value["authorization"] == "[REDACTED]"
    assert "secret" not in str(value)
    assert sanitize_url("https://example.test/x?a=b") == "https://example.test/x?a=%5BREDACTED%5D"
