"""Shared test constants and settings fixture for Donna's webhook tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from ema.config import Settings

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        meta_app_id="1111727731562433",
        meta_app_secret=SecretStr(APP_SECRET),
        meta_webhook_verify_token=SecretStr(VERIFY_TOKEN),
        meta_page_id="page-1",
        wa_app_id="1111727731562433",
        wa_app_secret=SecretStr(APP_SECRET),
        wa_webhook_verify_token=SecretStr(VERIFY_TOKEN),
        wa_access_token=SecretStr("test-access-token"),
        wa_phone_number_id="wa-1",
        wa_waba_id="waba-1",
        ema_master_key=SecretStr("test-master-key"),
        ema_live=False,
        ema_allowlist="",
        ema_audit_file=tmp_path / "audit.jsonl",
        ema_token_file=tmp_path / "tokens.enc.json",
        ema_idempotency_db=tmp_path / "events.sqlite3",
    )
