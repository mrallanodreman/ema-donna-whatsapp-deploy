"""Normalizer for Meta Page Messenger webhook payloads.

Only customer-authored messages become drafts. Page echoes and delivery,
read, postback and referral events are ignored for automation.
"""

from __future__ import annotations

from typing import Any

from ..events import NormalizedEvent


def _message_text(message: dict[str, Any]) -> tuple[str, str]:
    """Return display text and message kind for one Messenger message object."""
    text = str(message.get("text") or "").strip()
    if text:
        return text, "text"
    attachments = message.get("attachments") or []
    if attachments:
        first = attachments[0] if isinstance(attachments[0], dict) else {}
        kind = str(first.get("type") or "attachment")
        payload = first.get("payload") or {}
        title = str(payload.get("title") or "") if isinstance(payload, dict) else ""
        return title or f"[{kind}]", kind
    return "", "unknown"


def normalize_event(payload: dict[str, Any]) -> list[NormalizedEvent]:
    """Flatten Page `messaging` entries into platform-neutral events."""
    if str(payload.get("object", "")).casefold() != "page":
        return []
    events: list[NormalizedEvent] = []
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        page_id = str(entry.get("id", ""))
        for item in entry.get("messaging", []) or []:
            if not isinstance(item, dict):
                continue
            message = item.get("message")
            if not isinstance(message, dict):
                continue
            mid = str(message.get("mid") or "")
            sender_id = str((item.get("sender") or {}).get("id") or "")
            recipient_id = str((item.get("recipient") or {}).get("id") or "")
            is_echo = bool(message.get("is_echo"))
            actor_id = recipient_id if is_echo else sender_id
            text, kind = _message_text(message)
            if not text or not actor_id:
                continue
            direction = "outbound" if is_echo else "inbound"
            events.append(
                NormalizedEvent(
                    platform="messenger",
                    event_type="message",
                    object_id=page_id,
                    actor_id=actor_id,
                    target_id=page_id,
                    timestamp=str(item.get("timestamp") or entry.get("time") or ""),
                    text=text,
                    extra={
                        "message_id": mid,
                        "message_type": kind,
                        "page_id": page_id,
                        "direction": direction,
                        "is_echo": is_echo,
                    },
                )
            )
    return events
