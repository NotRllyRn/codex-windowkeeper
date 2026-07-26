from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from windowkeeper.config import Settings
from windowkeeper.vault import generate_key
from windowkeeper.web.app import _read_secret, create_app

PASSWORD = "correct horse battery staple"  # noqa: S105


def test_secret_file_precedes_environment_value_and_requires_private_mode(tmp_path: Path) -> None:
    source = tmp_path / "secret"
    source.write_text("from-file", encoding="utf-8")
    source.chmod(0o600)
    assert _read_secret(source, "from-environment") == "from-file"
    source.chmod(0o644)
    with pytest.raises(RuntimeError):
        _read_secret(source, None)


def test_network_configuration_is_validated(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            data_dir=tmp_path / "data",
            runtime_dir=tmp_path / "run",
            public_base_url="javascript:alert(1)",
        )
    with pytest.raises(ValidationError):
        Settings(
            data_dir=tmp_path / "data-2",
            runtime_dir=tmp_path / "run-2",
            trusted_proxies="*",
        )


def test_wrong_vault_key_fails_startup_without_mutating_data(tmp_path: Path) -> None:
    data, runtime = tmp_path / "data", tmp_path / "run"
    first = Settings(
        data_dir=data,
        runtime_dir=runtime,
        vault_key=generate_key(),
        admin_password=PASSWORD,
    )
    with TestClient(create_app(first)):
        pass
    second = Settings(
        data_dir=data,
        runtime_dir=runtime,
        vault_key=generate_key(),
        admin_password=PASSWORD,
    )
    with pytest.raises(RuntimeError, match="vault key"), TestClient(create_app(second)):
        pass
