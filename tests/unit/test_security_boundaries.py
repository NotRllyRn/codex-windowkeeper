import hashlib
from collections.abc import AsyncIterator
from typing import Any, cast
from urllib.parse import quote

import pytest

from windowkeeper.codex.adapter import CodexAdapter, select_activation_model
from windowkeeper.errors import WindowkeeperError
from windowkeeper.redaction import redact, sanitize_url
from windowkeeper.services import (
    ApplicationServices,
    browser_contract,
    validate_callback,
    verify_identity,
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


def test_activation_model_is_selected_by_verified_cost_not_catalog_order() -> None:
    models = [
        {
            "model": "gpt-5.6-sol",
            "hidden": False,
            "inputModalities": ["text"],
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
    ]
    assert select_activation_model(models).model == "gpt-5.4-mini"
    assert select_activation_model(models).effort == "minimal"


@pytest.mark.asyncio
async def test_activation_model_reads_every_catalog_page() -> None:
    class Client:
        cursors: list[str | None] = []

        async def request(self, method: str, params: dict[str, Any]) -> tuple[dict[str, Any], None]:
            assert method == "model/list"
            cursor = cast(str | None, params.get("cursor"))
            self.cursors.append(cursor)
            model = "gpt-5.6-sol" if cursor is None else "gpt-5.4-mini"
            return (
                {
                    "data": [
                        {
                            "model": model,
                            "hidden": False,
                            "inputModalities": ["text"],
                            "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
                        }
                    ],
                    "nextCursor": "page-2" if cursor is None else None,
                },
                None,
            )

    client = Client()
    selected = await CodexAdapter(cast(Any, client)).activation_model()
    assert selected.model == "gpt-5.4-mini"
    assert client.cursors == [None, "page-2"]


def test_activation_model_fails_closed_without_comparable_pricing() -> None:
    with pytest.raises(RuntimeError, match="unambiguously cheapest verified pricing"):
        select_activation_model(
            [
                {
                    "model": "unpriced-preview",
                    "hidden": False,
                    "inputModalities": ["text"],
                    "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
                }
            ]
        )


def test_forked_credentials_must_match_the_managed_identity() -> None:
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
    with pytest.raises(WindowkeeperError) as reauthentication:
        verify_identity(
            {"upstream_email": "owner@example.test"},
            {"account": {"email": "other@example.test"}},
        )
    assert reauthentication.value.code == "AUTH_IDENTITY_MISMATCH"


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
