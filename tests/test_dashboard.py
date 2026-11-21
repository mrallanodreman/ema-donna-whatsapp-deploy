"""Dashboard is loopback-only, secret-safe and audit-friendly."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from ema.config import Settings
from ema.dashboard import create_dashboard_app

SECRET = "super-secret-value-123"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        meta_app_id="1111727731562433",
        meta_app_secret=SecretStr(SECRET),
        wa_app_id="1111727731562433",
        wa_app_secret=SecretStr(SECRET),
        wa_access_token=SecretStr(SECRET),
        wa_webhook_verify_token=SecretStr(SECRET),
        ema_master_key=SecretStr(SECRET),
        ema_live=False,
        ema_allowlist="1133442449846622",
        ema_audit_file=tmp_path / "audit.jsonl",
        ema_token_file=tmp_path / "tokens.enc.json",
        ema_idempotency_db=tmp_path / "events.sqlite3",
        wa_phone_number_id="1133442449846622",
        wa_waba_id="26494997426777038",
    )


def client_for(tmp_path: Path, env_file: Path):
    settings = make_settings(tmp_path)
    app = create_dashboard_app(
        settings,
        env_path=env_file,
        profile_path=tmp_path / "profile.json",
        audit_path=tmp_path / "config-audit.jsonl",
    )
    return TestClient(app, base_url="http://127.0.0.1:8098")


def test_get_renders_masked_config_without_secret_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"WA_APP_SECRET={SECRET}\nCUSTOM_KEEP=unchanged\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert SECRET not in response.text
    assert "••••••••" in response.text
    assert "WA_ACCESS_TOKEN" in response.text
    assert "SOLO LOCAL" in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("host", ["donna.edgemarketing.tech", "evil.com", "testserver"])
def test_foreign_host_rejected(tmp_path: Path, host: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\n", encoding="utf-8")
    settings = make_settings(tmp_path)
    app = create_dashboard_app(settings, env_path=env_file)
    with TestClient(app, base_url=f"http://{host}") as client:
        assert client.get("/").status_code == 403


def test_foreign_origin_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        response = client.get("/", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_save_preserves_unknown_keys_and_never_echoes_secret(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"WA_APP_SECRET={SECRET}\nCUSTOM_KEEP=unchanged\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        page = client.get("/")
        csrf = page.text.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        response = client.post(
            "/save",
            data={"csrf": csrf, "CUSTOM_NEW": "added", "WA_APP_SECRET": "", "EMA_LIVE": "false", "__bool__EMA_LIVE": "1"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    text = env_file.read_text(encoding="utf-8")
    assert "CUSTOM_KEEP=unchanged" in text
    assert SECRET in text
    assert "CUSTOM_NEW" not in text  # only known Settings keys are accepted
    assert oct(os.stat(env_file).st_mode & 0o777) == "0o600"
    audit = json.loads((tmp_path / "config-audit.jsonl").read_text(encoding="utf-8").strip())
    assert audit["action"] == "config_update"
    assert SECRET not in json.dumps(audit)


def test_save_updates_known_key_and_audit(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        csrf = client.get("/").text.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        response = client.post(
            "/save",
            data={"csrf": csrf, "EMA_LIVE": "false", "__bool__EMA_LIVE": "1", "EMA_HTTP_TIMEOUT": "9.5"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "EMA_HTTP_TIMEOUT=" in env_file.read_text(encoding="utf-8")
    assert "9.5" in env_file.read_text(encoding="utf-8")


def test_csrf_required(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        assert client.post("/save", data={"EMA_LIVE": "true"}).status_code == 403
        assert client.post("/profile", data={"name": "x"}).status_code == 403


def test_profile_saved_with_0600(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        csrf = client.get("/").text.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        response = client.post(
            "/profile",
            data={"csrf": csrf, "name": "Allan", "role": "Operador", "timezone": "America/Guayaquil", "notes": "sin nota"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    profile_file = tmp_path / "profile.json"
    assert json.loads(profile_file.read_text(encoding="utf-8"))["name"] == "Allan"
    assert oct(os.stat(profile_file).st_mode & 0o777) == "0o600"


def csrf_of(client: TestClient) -> str:
    return client.get("/").text.split('name="csrf" value="', 1)[1].split('"', 1)[0]


def test_protected_fields_are_read_only(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\nWA_ACCESS_TOKEN=should-stay\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        page = client.get("/")
        csrf = csrf_of(client)
        response = client.post(
            "/save",
            data={
                "csrf": csrf,
                "EMA_LIVE": "true",
                "__bool__EMA_LIVE": "1",
                "WA_ACCESS_TOKEN": "new-token",
            },
            follow_redirects=False,
        )
    assert page.status_code == 200
    assert "solo lectura" in page.text
    assert "configurado" in page.text
    assert "should-stay" not in page.text
    assert response.status_code == 303
    text = env_file.read_text(encoding="utf-8")
    assert "EMA_LIVE=false" in text
    assert "should-stay" in text
    assert "new-token" not in text


def test_invalid_value_rejected_before_write(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\nEMA_PORT=8099\n", encoding="utf-8")
    before = env_file.read_text(encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        response = client.post(
            "/save",
            data={"csrf": csrf_of(client), "EMA_PORT": "70000"},
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert env_file.read_text(encoding="utf-8") == before
    assert not (tmp_path / "config-audit.jsonl").exists()


def test_variable_expansion_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\n", encoding="utf-8")
    before = env_file.read_text(encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        response = client.post(
            "/save",
            data={"csrf": csrf_of(client), "EMA_HOST": "a${HOME}b"},
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert env_file.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("header", ["x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip"])
def test_forwarded_headers_rejected(tmp_path: Path, header: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        response = client.get("/", headers={header: "192.168.1.4"})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_process_environment_does_not_override_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMA_LIVE", "true")
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        page = client.get("/")
    assert "EMA_LIVE=false — solo borradores" in page.text
    assert "EMA_LIVE=true — envío real habilitado" not in page.text


def test_no_external_assets(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EMA_LIVE=false\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        page = client.get("/").text
    assert "<script src=" not in page
    assert "stylesheet" not in page
    assert "@import" not in page


def test_clear_secret_removes_key_and_audits_name_only(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"WA_APP_SECRET={SECRET}\nEMA_LIVE=false\n", encoding="utf-8")
    with client_for(tmp_path, env_file) as client:
        response = client.post(
            "/save",
            data={"csrf": csrf_of(client), "__clear__WA_APP_SECRET": "1"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    text = env_file.read_text(encoding="utf-8")
    assert "WA_APP_SECRET" not in text
    assert SECRET not in text
    audit = json.loads((tmp_path / "config-audit.jsonl").read_text(encoding="utf-8").strip())
    assert audit["keys"] == ["WA_APP_SECRET"]
    assert SECRET not in json.dumps(audit)
