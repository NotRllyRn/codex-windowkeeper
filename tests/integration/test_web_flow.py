import asyncio
import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from windowkeeper.config import Settings
from windowkeeper.database import Database
from windowkeeper.vault import generate_key
from windowkeeper.web.app import create_app

PASSWORD = "correct horse battery staple"  # noqa: S105


def wait_for(client: TestClient, text: str, path: str = "/", timeout: float = 8) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(path)
        if text in response.text:
            return str(response.text)
        time.sleep(0.1)
    raise AssertionError(f"{text!r} did not appear at {path}")


def test_enrollment_refresh_activation_and_five_layouts(tmp_path: Path) -> None:
    executable = Path(__file__).parents[1] / "fake_codex.py"
    os.chmod(executable, 0o700)
    settings = Settings(
        data_dir=tmp_path / "data",
        runtime_dir=tmp_path / "run",
        vault_key=generate_key(),
        admin_password=PASSWORD,
        codex_executable=str(executable),
        codex_idle_seconds=0,
        activation_safety_delay_seconds=1,
        activation_jitter_max_seconds=0,
    )
    with TestClient(create_app(settings)) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ok"}
        login_page = client.get("/login")
        assert "default-src 'self'" in login_page.headers["content-security-policy"]
        assert login_page.headers["x-content-type-options"] == "nosniff"
        assert login_page.headers["referrer-policy"] == "no-referrer"
        login = client.post(
            "/login",
            data={"password": PASSWORD},
            headers={"Origin": "https://external.example"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        client.cookies.update(login.cookies)
        csrf = client.cookies["wk_csrf"]
        created = client.post(
            "/accounts",
            data={
                "display_name": "Primary",
                "labels": "team, critical",
                "workspace": "workspace-1",
                "login_method": "CHATGPT_DEVICE_CODE",
                "admin_password": PASSWORD,
                "csrf_token": csrf,
            },
        )
        assert created.status_code == 200
        wait_for(client, "Primary")
        wait_for(client, "Healthy")
        wait_for(client, "22%")
        for variant in ("orbit", "ledger", "rail", "timeline", "focus"):
            response = client.get(f"/?variant={variant}")
            assert response.status_code == 200
            assert f"variant-{variant}" in response.text
        dashboard = client.get("/api/internal/v1/dashboard").json()
        account = dashboard["data"][0]
        assert account["short_percent"] == 22
        login_traces = list((tmp_path / "run" / "accounts").glob("*/.fake-logins"))
        refresh_traces = list((tmp_path / "run" / "accounts").glob("*/.fake-refreshes"))
        assert len(login_traces) == len(refresh_traces) == 1
        assert login_traces[0].read_text(encoding="utf-8").splitlines() == ["login-1"]
        assert refresh_traces[0].read_text(encoding="utf-8").splitlines() == [
            "refresh-1",
            "refresh-2",
        ]
        for path in (
            f"/accounts/{account['public_token']}",
            "/accounts/new",
            "/settings",
            "/logs",
        ):
            assert client.get(path).status_code == 200
        exported_logs = client.get("/logs/export")
        assert exported_logs.status_code == 200
        assert exported_logs.headers["content-type"].startswith("application/x-ndjson")
        export_path = f"/accounts/{account['public_token']}/auth-export"
        assert (
            client.post(
                export_path,
                data={"admin_password": PASSWORD, "csrf_token": "invalid"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                export_path,
                data={"admin_password": "wrong password", "csrf_token": csrf},
            ).status_code
            == 401
        )
        auth_export = client.post(
            export_path,
            data={"admin_password": PASSWORD, "csrf_token": csrf},
        )
        assert auth_export.status_code == 200
        assert auth_export.headers["content-disposition"] == 'attachment; filename="auth.json"'
        assert auth_export.headers["cache-control"] == "no-store, max-age=0"
        assert auth_export.headers["content-type"] == "application/json"
        assert (
            json.loads(auth_export.content)["tokens"]["refresh_token"] == "fork-refresh-2"  # noqa: S105
        )
        reauthenticated = client.post(
            f"/accounts/{account['public_token']}/reauthenticate",
            data={
                "login_method": "CHATGPT_DEVICE_CODE",
                "admin_password": PASSWORD,
                "csrf_token": csrf,
            },
        )
        assert reauthenticated.status_code == 200
        deadline = time.monotonic() + 8
        while len(login_traces[0].read_text(encoding="utf-8").splitlines()) < 2:
            assert time.monotonic() < deadline
            time.sleep(0.1)
        while len(refresh_traces[0].read_text(encoding="utf-8").splitlines()) < 4:
            assert time.monotonic() < deadline
            time.sleep(0.1)
        rotated_export = client.post(
            export_path,
            data={"admin_password": PASSWORD, "csrf_token": csrf},
        )
        assert (
            json.loads(rotated_export.content)["tokens"]["refresh_token"] == "fork-refresh-4"  # noqa: S105
        )
        assert (
            client.post(
                f"/accounts/{account['public_token']}/refresh",
                data={"csrf_token": "invalid"},
            ).status_code
            == 403
        )
        refresh = client.post(
            f"/accounts/{account['public_token']}/refresh",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert refresh.status_code == 303
        wait_for(client, "Succeeded", refresh.headers["location"])
        latest_export = client.post(
            export_path,
            data={"admin_password": PASSWORD, "csrf_token": csrf},
        )
        assert (
            json.loads(latest_export.content)["tokens"]["refresh_token"] == "fork-refresh-6"  # noqa: S105
        )
        activation = client.post(
            f"/accounts/{account['public_token']}/activate",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert activation.status_code == 303
        wait_for(client, "Succeeded", activation.headers["location"])
        post_activation_export = client.post(
            export_path,
            data={"admin_password": PASSWORD, "csrf_token": csrf},
        )
        assert (
            json.loads(post_activation_export.content)["tokens"]["refresh_token"]
            == "fork-refresh-6"  # noqa: S105
        )
        duplicate = client.post(
            f"/accounts/{account['public_token']}/activate",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert duplicate.status_code == 409

        auth_error_marker = executable.with_suffix(".auth-error")
        auth_error_marker.touch()
        try:
            failed_refresh = client.post(
                f"/accounts/{account['public_token']}/refresh",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert failed_refresh.status_code == 303
            wait_for(client, "Failed", failed_refresh.headers["location"])
            wait_for(client, "Action Required")
            wait_for(client, "authentication must be renewed", "/incidents")
            retained_export = client.post(
                export_path,
                data={"admin_password": PASSWORD, "csrf_token": csrf},
            )
            assert (
                json.loads(retained_export.content)["tokens"]["refresh_token"] == "fork-refresh-6"  # noqa: S105
            )
        finally:
            auth_error_marker.unlink(missing_ok=True)


def test_manual_token_migration_recovers_v4_schema_drift(tmp_path: Path) -> None:
    old_migrations = tmp_path / "old-migrations"
    old_migrations.mkdir()
    migrations = Path(__file__).parents[2] / "src" / "windowkeeper" / "migrations"
    for migration in sorted(migrations.glob("00[1-3]_*.sql")):
        shutil.copy2(migration, old_migrations)
    database_path = tmp_path / "data" / "windowkeeper.db"
    database = Database(database_path, old_migrations)
    database.start()
    asyncio.run(database.close())
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "INSERT INTO schema_migrations VALUES(4,'004_manual_token_login','drifted',0)"
        )

    executable = Path(__file__).parents[1] / "fake_codex.py"
    os.chmod(executable, 0o700)
    settings = Settings(
        data_dir=tmp_path / "data",
        runtime_dir=tmp_path / "run",
        vault_key=generate_key(),
        admin_password=PASSWORD,
        codex_executable=str(executable),
        codex_idle_seconds=0,
    )
    with TestClient(create_app(settings)) as client:
        login = client.post("/login", data={"password": PASSWORD})
        client.cookies.update(login.cookies)
        created = client.post(
            "/accounts",
            data={
                "display_name": "Imported",
                "login_method": "MANUAL_TOKENS",
                "access_token": "source.access.jwt",
                "refresh_token": "source-refresh-token",
                "admin_password": PASSWORD,
                "csrf_token": client.cookies["wk_csrf"],
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        wait_for(client, "Succeeded", created.headers["location"])


def test_manual_tokens_use_the_normal_managed_credential_flow(tmp_path: Path) -> None:
    executable = Path(__file__).parents[1] / "fake_codex.py"
    os.chmod(executable, 0o700)
    settings = Settings(
        data_dir=tmp_path / "data",
        runtime_dir=tmp_path / "run",
        vault_key=generate_key(),
        admin_password=PASSWORD,
        codex_executable=str(executable),
        codex_idle_seconds=0,
    )
    access_token = "source.access.jwt"  # noqa: S105
    refresh_token = "source-refresh-token"  # noqa: S105
    with TestClient(create_app(settings)) as client:
        login = client.post("/login", data={"password": PASSWORD})
        client.cookies.update(login.cookies)
        csrf = client.cookies["wk_csrf"]
        rejected = client.post(
            "/accounts",
            data={
                "display_name": "Rejected import",
                "login_method": "MANUAL_TOKENS",
                "admin_password": PASSWORD,
                "csrf_token": csrf,
            },
        )
        assert rejected.status_code == 422
        assert client.get("/api/internal/v1/dashboard").json()["data"] == []
        created = client.post(
            "/accounts",
            data={
                "display_name": "Imported",
                "login_method": "MANUAL_TOKENS",
                "access_token": access_token,
                "refresh_token": refresh_token,
                "admin_password": PASSWORD,
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert created.headers["location"].startswith("/operations/")
        operation = wait_for(client, "Succeeded", created.headers["location"])
        wait_for(client, "Imported")
        account = client.get("/api/internal/v1/dashboard").json()["data"][0]
        detail = client.get(f"/accounts/{account['public_token']}")
        assert "MANUAL_TOKENS" in detail.text
        assert access_token not in operation + detail.text
        assert refresh_token not in client.get("/logs/export").text
        assert not list((tmp_path / "run" / "accounts").glob("*/.fake-logins"))
        traces = list((tmp_path / "run" / "accounts").glob("*/.fake-refreshes"))
        assert len(traces) == 1
        assert traces[0].read_text(encoding="utf-8").splitlines() == ["refresh-1", "refresh-2"]
        exported = client.post(
            f"/accounts/{account['public_token']}/auth-export",
            data={"admin_password": PASSWORD, "csrf_token": csrf},
        )
        assert json.loads(exported.content)["tokens"]["refresh_token"] == "fork-refresh-2"  # noqa: S105
        replaced = client.post(
            f"/accounts/{account['public_token']}/reauthenticate",
            data={
                "login_method": "MANUAL_TOKENS",
                "access_token": access_token,
                "refresh_token": refresh_token,
                "admin_password": PASSWORD,
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        assert replaced.status_code == 303
        wait_for(client, "Succeeded", replaced.headers["location"])
        assert traces[0].read_text(encoding="utf-8").splitlines() == [
            "refresh-1",
            "refresh-2",
            "refresh-3",
            "refresh-4",
        ]
        exported = client.post(
            f"/accounts/{account['public_token']}/auth-export",
            data={"admin_password": PASSWORD, "csrf_token": csrf},
        )
        assert json.loads(exported.content)["tokens"]["refresh_token"] == "fork-refresh-4"  # noqa: S105


def test_latest_auth_export_survives_restart_and_activation(tmp_path: Path) -> None:
    executable = Path(__file__).parents[1] / "fake_codex.py"
    os.chmod(executable, 0o700)
    settings = Settings(
        data_dir=tmp_path / "data",
        runtime_dir=tmp_path / "run",
        vault_key=generate_key(),
        admin_password=PASSWORD,
        codex_executable=str(executable),
        codex_idle_seconds=0,
        activation_safety_delay_seconds=1,
        activation_jitter_max_seconds=0,
    )
    with TestClient(create_app(settings)) as client:
        login = client.post("/login", data={"password": PASSWORD})
        client.cookies.update(login.cookies)
        csrf = client.cookies["wk_csrf"]
        created = client.post(
            "/accounts",
            data={
                "display_name": "Persisted export",
                "login_method": "CHATGPT_DEVICE_CODE",
                "admin_password": PASSWORD,
                "csrf_token": csrf,
            },
        )
        assert created.status_code == 200
        wait_for(client, "22%")
        account = client.get("/api/internal/v1/dashboard").json()["data"][0]
        refreshed = client.post(
            f"/accounts/{account['public_token']}/refresh",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        wait_for(client, "Succeeded", refreshed.headers["location"])

    export_path = f"/accounts/{account['public_token']}/auth-export"
    with TestClient(create_app(settings)) as client:
        login = client.post("/login", data={"password": PASSWORD})
        client.cookies.update(login.cookies)
        csrf = client.cookies["wk_csrf"]
        persisted = client.post(export_path, data={"admin_password": PASSWORD, "csrf_token": csrf})
        assert json.loads(persisted.content)["tokens"]["refresh_token"] == "fork-refresh-4"  # noqa: S105
        activation = client.post(
            f"/accounts/{account['public_token']}/activate",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        wait_for(client, "Succeeded", activation.headers["location"])
        rotated = client.post(export_path, data={"admin_password": PASSWORD, "csrf_token": csrf})
        assert json.loads(rotated.content)["tokens"]["refresh_token"] == "fork-refresh-4"  # noqa: S105


def test_authentication_csrf_and_readiness_fail_closed(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        runtime_dir=tmp_path / "run",
        vault_key=generate_key(),
        admin_password=PASSWORD,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 503
        unauthenticated = client.get("/", follow_redirects=False)
        assert unauthenticated.status_code == 303
        assert unauthenticated.headers["location"] == "/login"
        assert client.post("/login", data={"password": "wrong"}).status_code == 200
        login = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        client.cookies.update(login.cookies)
        assert (
            client.post(
                "/settings/webhooks",
                data={
                    "display_name": "x",
                    "url": "https://example.test",
                    "admin_password": PASSWORD,
                    "csrf_token": "wrong",
                },
            ).status_code
            == 403
        )
        statuses = [
            client.post(
                "/settings/webhooks",
                data={
                    "display_name": "x",
                    "url": "https://example.test",
                    "admin_password": "incorrect administrator password",
                    "csrf_token": client.cookies["wk_csrf"],
                },
            ).status_code
            for _ in range(6)
        ]
        assert statuses == [401, 401, 401, 401, 401, 429]

    rooted = Settings(
        data_dir=tmp_path / "rooted-data",
        runtime_dir=tmp_path / "rooted-run",
        vault_key=generate_key(),
        admin_password=PASSWORD,
        root_path="/windowkeeper",
    )
    with TestClient(create_app(rooted)) as client:
        rooted_redirect = client.get("/", follow_redirects=False)
        assert rooted_redirect.headers["location"] == "/windowkeeper/login"
        login_html = client.get("/login").text
        assert 'data-root-path="/windowkeeper"' in login_html
        assert 'href="/windowkeeper/static/app.css"' in login_html
        rooted_login = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        assert rooted_login.headers["location"] == "/windowkeeper/"
        assert rooted_login.cookies["wk_session"]


def test_login_is_rate_limited(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        runtime_dir=tmp_path / "run",
        vault_key=generate_key(),
        admin_password=PASSWORD,
    )
    with TestClient(create_app(settings)) as client:
        for _ in range(5):
            assert client.post("/login", data={"password": "wrong"}).status_code == 200
        assert client.post("/login", data={"password": "wrong"}).status_code == 429
