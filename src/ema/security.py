"""Token encryption, webhook signatures and short-lived OAuth state."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def generate_master_key() -> str:
    """Return a fresh Fernet key suitable for EMA_MASTER_KEY."""
    return Fernet.generate_key().decode()


def _fernet(key: str | bytes) -> Fernet:
    material = key.encode() if isinstance(key, str) else key
    try:
        return Fernet(material)
    except (ValueError, TypeError) as exc:
        raise ValueError("EMA_MASTER_KEY must be a valid Fernet key") from exc


def encrypt(plaintext: str, key: str | bytes) -> str:
    """Encrypt a token for at-rest storage."""
    return _fernet(key).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, key: str | bytes) -> str:
    """Decrypt a stored token; never leak the ciphertext in errors."""
    try:
        return _fernet(key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("stored token is invalid or key changed") from exc


@dataclass(slots=True)
class StoredToken:
    """Encrypted-at-rest token record with expiry metadata."""

    access_token: str
    refresh_token: str | None = None
    expires_at: str | None = None
    token_type: str = "bearer"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredToken:
        return cls(
            access_token=str(data.get("access_token", "")),
            refresh_token=data.get("refresh_token"),
            expires_at=data.get("expires_at"),
            token_type=str(data.get("token_type", "bearer")),
        )


class TokenVault:
    """0600 JSON file holding encrypted tokens keyed by account name."""

    def __init__(self, path: Path | str, master_key: str | bytes) -> None:
        self.path = Path(path)
        self._fernet = _fernet(master_key)

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("token file must contain a JSON object")
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
        os.chmod(self.path, 0o600)

    def put(self, account: str, token: StoredToken) -> None:
        """Store or replace one account's token."""
        data = self._read()
        data[account] = {
            "access_token": self._fernet.encrypt(token.access_token.encode()).decode(),
            "refresh_token": self._fernet.encrypt(token.refresh_token.encode()).decode()
            if token.refresh_token
            else None,
            "expires_at": token.expires_at,
            "token_type": token.token_type,
        }
        self._write(data)

    def get(self, account: str) -> StoredToken | None:
        """Return a decrypted token or None when absent."""
        record = self._read().get(account)
        if not record:
            return None
        try:
            return StoredToken(
                access_token=self._fernet.decrypt(record["access_token"].encode()).decode(),
                refresh_token=self._fernet.decrypt(record["refresh_token"].encode()).decode()
                if record.get("refresh_token")
                else None,
                expires_at=record.get("expires_at"),
                token_type=str(record.get("token_type", "bearer")),
            )
        except (InvalidToken, KeyError, TypeError) as exc:
            raise ValueError("token file is corrupt or key changed") from exc

    def delete(self, account: str) -> bool:
        """Remove one account token; return True when something was removed."""
        data = self._read()
        if account not in data:
            return False
        del data[account]
        self._write(data)
        return True

    def accounts(self) -> tuple[str, ...]:
        """List stored account keys."""
        return tuple(sorted(self._read()))


def sign_payload(payload: bytes, secret: str) -> str:
    """Build the sha256 signature header for a raw request body."""
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(payload: bytes, header: str | None, secret: str) -> bool:
    """Constant-time verification of X-Hub-Signature-256."""
    if not header or not secret:
        return False
    scheme, separator, received = header.partition("=")
    if not separator or scheme.lower() != "sha256" or not received:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received.strip(), expected)


def verify_verify_token(token: str | None, expected: str) -> bool:
    """Compare hub.verify_token in constant time."""
    return bool(token and expected) and hmac.compare_digest(token, expected)


@dataclass(frozen=True, slots=True)
class OAuthState:
    """Signed, expiring CSRF state payload."""

    platform: str
    nonce: str
    expires_at: int
    redirect_uri: str = ""

    def encode(self, signing_key: str) -> str:
        body = base64.urlsafe_b64encode(json.dumps(asdict(self), sort_keys=True).encode()).decode().rstrip("=")
        signature = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{signature}"

    @classmethod
    def decode(cls, value: str, signing_key: str) -> OAuthState | None:
        body, separator, signature = value.partition(".")
        if not separator:
            return None
        expected = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            data = json.loads(raw)
            return cls(
                platform=str(data["platform"]),
                nonce=str(data["nonce"]),
                expires_at=int(data["expires_at"]),
                redirect_uri=str(data.get("redirect_uri", "")),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None


class OAuthStateManager:
    """Issues single-use state values with a short TTL."""

    def __init__(self, signing_key: str, ttl_seconds: int = 600, max_seen: int = 4096) -> None:
        self._key = signing_key
        self._ttl = ttl_seconds
        self._seen: deque[str] = deque(maxlen=max_seen)

    def issue(self, platform: str, redirect_uri: str = "") -> str:
        state = OAuthState(
            platform=platform,
            nonce=secrets.token_urlsafe(18),
            expires_at=int(time.time()) + self._ttl,
            redirect_uri=redirect_uri,
        )
        return state.encode(self._key)

    def validate(self, state: str, platform: str) -> bool:
        """Validate signature, expiry, platform and replay protection."""
        decoded = OAuthState.decode(state, self._key)
        if decoded is None or decoded.platform != platform:
            return False
        if decoded.expires_at <= int(time.time()):
            return False
        if decoded.nonce in self._seen:
            return False
        self._seen.append(decoded.nonce)
        return True


def utc_now() -> str:
    """UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    print(generate_master_key())
