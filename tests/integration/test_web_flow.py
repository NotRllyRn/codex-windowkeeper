import hashlib
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from windowkeeper.config import Settings
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
        codex_version="codex-cli 1.2.3",
        codex_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
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
        login = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
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
        assert (
            client.post(
                f"/accounts/{account['public_token']}/refresh",
                data={"csrf_token": "invalid"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/accounts/{account['public_token']}/refresh",
                data={"csrf_token": csrf},
                headers={"Origin": "https://attacker.example"},
            ).status_code
            == 403
        )
        refresh = client.post(
            f"/accounts/{account['public_token']}/refresh",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert refresh.status_code == 303
        activation = client.post(
            f"/accounts/{account['public_token']}/activate",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert activation.status_code == 303
        wait_for(client, "Succeeded", activation.headers["location"])
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
        finally:
            auth_error_marker.unlink(missing_ok=True)


def test_authentication_csrf_and_readiness_fail_closed(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        runtime_dir=tmp_path / "run",
        vault_key=generate_key(),
        admin_password=PASSWORD,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/").status_code == 401
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
        assert (
            client.post(
                "/settings/webhooks",
                headers={"Origin": "https://attacker.invalid"},
                data={
                    "display_name": "x",
                    "url": "https://example.test",
                    "admin_password": PASSWORD,
                    "csrf_token": client.cookies["wk_csrf"],
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
