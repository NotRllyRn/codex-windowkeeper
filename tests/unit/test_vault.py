import json
from pathlib import Path

import pytest

from windowkeeper.vault import Vault, decode_key, generate_key


def test_envelope_round_trip_and_account_binding() -> None:
    vault = Vault(decode_key(generate_key()), "instance")
    payload = {"schema_version": 1, "files": []}
    envelope = vault.encrypt("account-a", payload)
    assert vault.decrypt(envelope) == payload
    assert (
        vault.open_text(vault.seal_text("webhook:a", "https://example.test/hook"))
        == "https://example.test/hook"
    )


def test_imported_tokens_create_a_minimal_refreshable_auth_file() -> None:
    vault = Vault(decode_key(generate_key()), "instance")
    payload = vault.imported_tokens("access.jwt.value", "refresh-value", "test")
    auth = json.loads(vault.auth_json(payload))
    assert auth == {
        "tokens": {
            "id_token": "access.jwt.value",
            "access_token": "access.jwt.value",
            "refresh_token": "refresh-value",
            "account_id": None,
        }
    }
    assert "last_refresh" not in auth


def test_capture_and_materialize_reject_unsafe_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "auth.json").write_text('{"token":"secret"}', encoding="utf-8")
    vault = Vault(decode_key(generate_key()), "instance")
    payload = vault.capture(source, "test")
    assert vault.auth_json(payload) == b'{"token":"secret"}'
    destination = tmp_path / "destination"
    vault.materialize(payload, destination)
    assert (destination / "auth.json").read_text() == '{"token":"secret"}'
    payload["files"][0]["relative_path"] = "../auth.json"
    with pytest.raises(ValueError):
        vault.auth_json(payload)
    with pytest.raises(ValueError):
        vault.materialize(payload, tmp_path / "bad")
