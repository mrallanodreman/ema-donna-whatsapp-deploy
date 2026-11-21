"""Encrypted token storage, expiry detection and refresh helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings
from .meta_client import MetaClient
from .security import StoredToken, TokenVault

logger = logging.getLogger(__name__)


class TokenError(RuntimeError):
    """Raised when no usable token is available."""


@dataclass(frozen=True, slots=True)
class TokenRef:
    """Platform + account identifier."""

    platform: str
    account_id: str = "default"

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.account_id}"

    @property
    def env_name(self) -> str:
        return "IG_ACCESS_TOKEN" if self.platform == "instagram" else "THREADS_ACCESS_TOKEN"


def _parse_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_expiring(token: StoredToken, skew_seconds: int = 300) -> bool:
    """True when a token expires within the safety window."""
    expiry = _parse_expiry(token.expires_at)
    return bool(expiry and expiry <= datetime.now(timezone.utc) + timedelta(seconds=skew_seconds))


class TokenStore:
    """Fernet-backed store with in-memory cache and automatic refresh."""

    def __init__(
        self,
        settings: Settings,
        *,
        vault: TokenVault | None = None,
        client_factory: Callable[[str], MetaClient] | None = None,
    ) -> None:
        self.settings = settings
        self._vault = vault
        self._factory = client_factory or (
            lambda base: MetaClient(base, timeout=settings.ema_http_timeout, max_retries=settings.ema_max_retries)
        )
        self._cache: dict[str, StoredToken] = {}
        self._clients: dict[str, MetaClient] = {}

    @property
    def vault(self) -> TokenVault:
        """Create the encrypted vault on first use."""
        if self._vault is None:
            self._vault = TokenVault(
                self.settings.ema_token_file, self.settings.secret(self.settings.ema_master_key)
            )
        return self._vault

    def ref(self, platform: str, account_id: str | None = None) -> TokenRef:
        """Build a token reference using configured default account ids."""
        if platform not in {"instagram", "threads"}:
            raise TokenError(f"unknown platform: {platform}")
        default = (
            self.settings.ig_user_id if platform == "instagram" else self.settings.threads_user_id
        )
        return TokenRef(platform, account_id or default or "default")

    def load(self, platform: str, account_id: str | None = None) -> StoredToken | None:
        """Load a token from cache, vault, then environment (seeding the vault)."""
        ref = self.ref(platform, account_id)
        if ref.key in self._cache:
            return self._cache[ref.key]
        token = self.vault.get(ref.key)
        if token is None:
            raw = self.settings.secret(
                self.settings.ig_access_token
                if platform == "instagram"
                else self.settings.threads_access_token
            )
            if raw:
                token = StoredToken(access_token=raw)
                self.save(platform, token, account_id)
        if token:
            self._cache[ref.key] = token
        return token

    def save(
        self,
        platform: str,
        token: StoredToken,
        account_id: str | None = None,
        *,
        expires_in: int | None = None,
    ) -> StoredToken:
        """Persist a token, optionally computing expires_at from expires_in."""
        if expires_in:
            expiry = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            token = StoredToken(
                access_token=token.access_token,
                refresh_token=token.refresh_token,
                expires_at=expiry.isoformat(timespec="seconds"),
                token_type=token.token_type,
            )
        ref = self.ref(platform, account_id)
        self.vault.put(ref.key, token)
        self._cache[ref.key] = token
        return token

    def _client(self, platform: str) -> MetaClient:
        if platform not in self._clients:
            base = (
                self.settings.graph_base_url
                if platform == "instagram"
                else self.settings.threads_base_url
            )
            self._clients[platform] = self._factory(base)
        return self._clients[platform]

    def status(self, platform: str, account_id: str | None = None) -> dict[str, Any]:
        """Non-secret token status for /status and CLI."""
        try:
            token = self.load(platform, account_id)
        except ValueError:
            token = None
        return {
            "present": token is not None,
            "expiring": is_expiring(token) if token else False,
            "expires_at": token.expires_at if token else None,
        }

    async def get_valid_token(self, platform: str, account_id: str | None = None) -> str:
        """Return a valid access token, refreshing shortly before expiry."""
        token = self.load(platform, account_id)
        if token is None:
            raise TokenError(f"no token stored for {platform}")
        if is_expiring(token):
            token = await self.refresh(platform, account_id)
        return token.access_token

    async def refresh(self, platform: str, account_id: str | None = None) -> StoredToken:
        """Exchange a long-lived token for a fresh one."""
        ref = self.ref(platform, account_id)
        token = self.load(platform, account_id)
        if token is None:
            raise TokenError(f"no token to refresh for {ref.key}")
        client = self._client(platform)
        if platform == "instagram":
            payload = await client.get(
                "/refresh_access_token",
                params={"grant_type": "ig_refresh_token", "access_token": token.access_token},
            )
        else:
            payload = await client.get(
                "https://graph.threads.com/oauth/access_token",
                params={"grant_type": "th_long_lived_token", "access_token": token.access_token},
            )
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise TokenError(f"refresh failed for {ref.key}")
        logger.info("refreshed token for %s", ref.key)
        return self.save(
            platform,
            StoredToken(
                access_token=str(payload["access_token"]),
                token_type=str(payload.get("token_type", "bearer")),
            ),
            account_id,
            expires_in=int(payload.get("expires_in", 0)) or None,
        )

    async def debug_token(
        self, platform: str, access_token: str | None = None, account_id: str | None = None
    ) -> dict[str, Any]:
        """Inspect a token with /debug_token using the app token."""
        token = access_token or await self.get_valid_token(platform, account_id)
        endpoint = (
            f"{self.settings.graph_base_url}/debug_token"
            if platform == "instagram"
            else "https://graph.threads.com/debug_token"
        )
        client = self._client(platform)
        payload = await client.get(
            endpoint,
            params={"input_token": token},
            access_token=self.settings.app_access_token,
        )
        return payload.get("data", {}) if isinstance(payload, dict) else {}

    async def aclose(self) -> None:
        """Close all clients created by this store."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
