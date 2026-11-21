"""Dry-run by default, explicit approval, allowlist and append-only audit."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .security import utc_now

logger = logging.getLogger(__name__)

EFFECT_ACTIONS = frozenset({"publish", "reply", "delete", "send", "hide", "unhide", "approve", "ignore"})
LINK_RE = re.compile(r"https?://\S+", re.IGNORECASE)
MAX_LINKS_PER_POST = 5
MAX_THREADS_TEXT = 500
SENSITIVE_KEYS = ("token", "secret", "password", "credential", "authorization")


def redact_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively mask secret-looking keys for logs and audit hashes."""
    from collections.abc import Mapping

    result: dict[str, Any] = {}
    for key, value in payload.items():
        if any(part in str(key).lower() for part in SENSITIVE_KEYS):
            result[str(key)] = "***"
        elif isinstance(value, Mapping):
            result[str(key)] = redact_payload(value)
        elif isinstance(value, (list, tuple)):
            result[str(key)] = [
                redact_payload(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            result[str(key)] = value
    return result


def count_links(text: str) -> int:
    """Count HTTP(S) URLs in a text body."""
    return len(LINK_RE.findall(text or ""))


@dataclass(slots=True)
class AuditEvent:
    """Immutable audit record written as one JSON line."""

    timestamp: str
    action: str
    target: str
    payload_hash: str
    result: str
    actor: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "target": self.target,
            "payload_hash": self.payload_hash,
            "result": self.result,
            "actor": self.actor,
            "detail": self.detail,
        }


class AuditLog:
    """Append-only JSONL audit trail with 0600 permissions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, event: AuditEvent) -> None:
        """Append a single event; existing records are never rewritten."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        os.chmod(self.path, 0o600)

    def read(self) -> list[dict[str, str]]:
        """Read events (tests and runbook)."""
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]


@dataclass(slots=True)
class ThreadsQuota:
    """Remaining Threads publishing quota buckets."""

    posts: int = 0
    replies: int = 0
    deletions: int = 0
    location_searches: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ThreadsQuota:
        """Parse the /threads_publishing_limit response."""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        remaining = data.get("quota_remaining") or {}
        if not isinstance(remaining, dict):
            remaining = {}

        def number(key: str) -> int:
            try:
                return int(remaining.get(key, 0))
            except (TypeError, ValueError):
                return 0

        return cls(
            posts=number("posts"),
            replies=number("replies"),
            deletions=number("deletions"),
            location_searches=number("location_searches"),
        )

    def remaining_for(self, action: str) -> int | None:
        """Quota bucket applicable to an effect action."""
        mapping = {
            "publish": self.posts,
            "reply": self.replies,
            "delete": self.deletions,
        }
        return mapping.get(action)


@dataclass(slots=True)
class GuardDecision:
    """Result of a guardrail check, also used as the dry-run plan."""

    action: str
    target: str
    allowed: bool
    mode: str
    reasons: list[str] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "allowed": self.allowed,
            "mode": self.mode,
            "reasons": self.reasons,
            "plan": self.plan,
        }


class Guardrails:
    """Central policy gate for every action with an external effect."""

    def __init__(self, settings: Settings, audit: AuditLog | None = None) -> None:
        self.settings = settings
        self.audit = audit or AuditLog(settings.ema_audit_file)

    def check_limits(self, action: str, payload: dict[str, Any], platform: str = "threads") -> list[str]:
        """Return human-readable policy violations for a payload."""
        violations: list[str] = []
        text = str(payload.get("text") or payload.get("caption") or "")
        if action in {"publish", "reply"} and platform == "threads":
            if len(text) > MAX_THREADS_TEXT:
                violations.append(f"text length {len(text)} exceeds {MAX_THREADS_TEXT}")
        links = count_links(text)
        for extra in payload.get("links", []) or []:
            links += 1 if isinstance(extra, str) else 0
        if payload.get("link"):
            links += 1
        if action in {"publish", "reply"} and links > MAX_LINKS_PER_POST:
            violations.append(f"{links} links exceeds limit of {MAX_LINKS_PER_POST}")
        return violations

    def check_quota(self, action: str, quota: ThreadsQuota | None) -> list[str]:
        """Return violations when a required Threads quota bucket is empty."""
        if quota is None:
            return []
        remaining = quota.remaining_for(action)
        if remaining is not None and remaining <= 0:
            return [f"no Threads quota remaining for {action}"]
        return []

    def authorize(
        self,
        action: str,
        target: str,
        payload: dict[str, Any] | None = None,
        *,
        approve: bool = False,
        account: str | None = None,
        actor: str = "agent",
        platform: str = "threads",
        quota: ThreadsQuota | None = None,
    ) -> GuardDecision:
        """Evaluate policy, record the decision and return an explicit plan."""
        body = payload or {}
        sanitized = redact_payload(body)
        reasons: list[str] = []
        requires_approval = action in EFFECT_ACTIONS

        if requires_approval:
            if not self.settings.ema_live:
                reasons.append("EMA_LIVE=false (dry-run)")
            if not approve:
                reasons.append("approve=True required")
            allowed_account = (account or "").lower()
            if allowed_account not in self.settings.allowlist:
                reasons.append("account not in EMA_ALLOWLIST")
        reasons.extend(self.check_limits(action, body, platform))
        reasons.extend(self.check_quota(action, quota))

        allowed = not reasons
        mode = "live" if allowed else ("denied" if requires_approval else "dry_run")
        plan = {
            "action": action,
            "target": target,
            "platform": platform,
            "account": account,
            "payload": sanitized,
            "requires_approval": requires_approval,
            "actor": actor,
        }
        decision = GuardDecision(
            action=action, target=target, allowed=allowed, mode=mode, reasons=reasons, plan=plan
        )
        digest = hashlib.sha256(
            json.dumps(sanitized, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        plan["payload_hash"] = digest
        self.audit.append(
            AuditEvent(
                timestamp=utc_now(),
                action=action,
                target=target,
                payload_hash=digest,
                result="approved" if allowed else "blocked",
                actor=actor,
                detail="; ".join(reasons),
            )
        )
        logger.info("guardrails action=%s target=%s mode=%s", action, target, mode)
        return decision

    async def run(
        self,
        action: str,
        target: str,
        payload: dict[str, Any] | None,
        operation: Callable[[], Awaitable[Any]],
        *,
        approve: bool = False,
        account: str | None = None,
        actor: str = "agent",
        platform: str = "threads",
        quota: ThreadsQuota | None = None,
    ) -> GuardDecision:
        """Authorize first; only then execute the deferred operation."""
        decision = self.authorize(
            action,
            target,
            payload,
            approve=approve,
            account=account,
            actor=actor,
            platform=platform,
            quota=quota,
        )
        if not decision.allowed:
            return decision
        try:
            result = await operation()
        except Exception as exc:
            self.audit.append(
                AuditEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    action=action,
                    target=target,
                    payload_hash=decision.plan.get("payload_hash", ""),
                    result="error",
                    actor=actor,
                    detail=type(exc).__name__,
                )
            )
            raise
        decision.plan["result"] = redact_payload(result) if isinstance(result, dict) else result
        self.audit.append(
            AuditEvent(
                timestamp=utc_now(),
                action=action,
                target=target,
                payload_hash="",
                result="ok",
                actor=actor,
            )
        )
        return decision
