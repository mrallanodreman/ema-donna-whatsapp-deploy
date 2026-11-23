"""Environment-driven settings with secret-safe rendering."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _data_dir() -> Path:
    """Resolve writable data dir; installed packages cannot write to site-packages."""
    configured = os.environ.get("EMA_DATA_DIR", "").strip()
    return Path(configured) if configured else PROJECT_ROOT / "data"


class Settings(BaseSettings):
    """Runtime configuration; empty defaults keep test runs secret-free."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    meta_app_id: str = ""
    meta_app_secret: SecretStr = SecretStr("")
    meta_webhook_verify_token: SecretStr = SecretStr("")
    meta_app_secret_proof: SecretStr | None = None
    meta_api_version: str = "v26.0"
    meta_page_id: str = ""

    ema_master_key: SecretStr = SecretStr("")
    ema_live: bool = False
    ema_allowlist: str = ""
    ema_token_file: Path = Field(default_factory=lambda: _data_dir() / "tokens.enc.json")
    ema_audit_file: Path = Field(default_factory=lambda: _data_dir() / "audit.jsonl")
    ema_idempotency_db: Path = Field(default_factory=lambda: _data_dir() / "events.sqlite3")
    ema_host: str = "127.0.0.1"
    ema_port: int = 8099
    ema_http_timeout: float = 20.0
    ema_max_retries: int = 3

    wa_app_id: str = ""
    wa_app_secret: SecretStr = SecretStr("")
    wa_webhook_verify_token: SecretStr = SecretStr("")
    wa_phone_number_id: str = ""
    wa_waba_id: str = ""
    wa_access_token: SecretStr = SecretStr("")

    ig_user_id: str = ""
    ig_access_token: SecretStr = SecretStr("")
    threads_user_id: str = ""
    threads_access_token: SecretStr = SecretStr("")
    threads_app_id: str = ""
    threads_meta_app_id: str = ""
    threads_app_secret: SecretStr = SecretStr("")

    @field_validator("ema_port")
    @classmethod
    def _valid_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("ema_port must be between 1 and 65535")
        return value

    @property
    def allowlist(self) -> frozenset[str]:
        return frozenset(item.strip().lower() for item in self.ema_allowlist.split(",") if item.strip())

    @property
    def graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.meta_api_version}"

    @property
    def threads_base_url(self) -> str:
        return "https://graph.threads.com/v1.0"

    @property
    def app_access_token(self) -> str:
        return f"{self.meta_app_id}|{self.meta_app_secret.get_secret_value()}"

    def secret(self, value: SecretStr | None) -> str:
        return value.get_secret_value() if value else ""

    def sanitized(self) -> dict[str, object]:
        """Status payload: no secret material, only presence flags."""
        return {
            "live": self.ema_live,
            "allowlist_size": len(self.allowlist),
            "app_id_configured": bool(self.meta_app_id),
            "meta_page_id": self.meta_page_id or None,
            "app_secret_configured": bool(self.secret(self.meta_app_secret)),
            "verify_token_configured": bool(self.secret(self.meta_webhook_verify_token)),
            "master_key_configured": bool(self.secret(self.ema_master_key)),
            "whatsapp_app_configured": bool(self.wa_app_id and self.secret(self.wa_app_secret)),
            "whatsapp_phone_configured": bool(self.wa_phone_number_id),
            "whatsapp_waba_configured": bool(self.wa_waba_id),
            "whatsapp_token_configured": bool(self.secret(self.wa_access_token)),
            "ig_user_id": self.ig_user_id or None,
            "threads_user_id": self.threads_user_id or None,
            "threads_app_configured": bool(self.threads_app_id and self.threads_app_secret.get_secret_value()),
            "graph_base_url": self.graph_base_url,
            "threads_base_url": self.threads_base_url,
            "http_timeout": self.ema_http_timeout,
            "max_retries": self.ema_max_retries,
            "host": self.ema_host,
            "port": self.ema_port,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance for the process."""
    return Settings()
