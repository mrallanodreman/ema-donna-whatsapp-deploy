"""Normalize Threads webhook fields into neutral events."""

from __future__ import annotations

from typing import Any

from ..events import NormalizedEvent

FIELD_TO_TYPE = {
    "replies": "reply",
    "mentions": "mention",
    "delete": "delete",
    "publish": "publish",
}


def normalize_event(payload: dict[str, Any]) -> list[NormalizedEvent]:
    """Flatten a Threads webhook payload into normalized events."""
    events: list[NormalizedEvent] = []
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        timestamp = str(entry.get("time", ""))
        changes = entry.get("changes") or entry.get("changing_fields") or []
        for change in changes:
            if not isinstance(change, dict):
                continue
            field = str(change.get("field", ""))
            value = change.get("value")
            value = value if isinstance(value, dict) else {}
            actor = value.get("from") or value.get("from_id") or value.get("sender") or {}
            actor_id = str(actor.get("id") or value.get("from_id") or "")
            events.append(
                NormalizedEvent(
                    platform="threads",
                    event_type=FIELD_TO_TYPE.get(field, field),
                    object_id=str(value.get("id") or value.get("post_id") or entry.get("id") or ""),
                    actor_id=actor_id,
                    target_id=str(value.get("post_id") or value.get("parent_id") or ""),
                    timestamp=timestamp,
                    text=str(value.get("text") or ""),
                    extra={"field": field, "username": actor.get("username", "")},
                )
            )
    return events
