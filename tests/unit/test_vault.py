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


def test_capture_and_materialize_reject_unsafe_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "auth.json").write_text('{"token":"secret"}', encoding="utf-8")
    vault = Vault(decode_key(generate_key()), "instance")
    payload = vault.capture(source, "test")
    destination = tmp_path / "destination"
    vault.materialize(payload, destination)
    assert (destination / "auth.json").read_text() == '{"token":"secret"}'
    payload["files"][0]["relative_path"] = "../auth.json"
    with pytest.raises(ValueError):
        vault.materialize(payload, tmp_path / "bad")
