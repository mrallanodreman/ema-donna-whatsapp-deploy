"""Normalize every Instagram webhook field listed in the plan."""

from __future__ import annotations

from typing import Any

from ..events import NormalizedEvent

FIELD_TO_TYPE = {
    "comments": "comment",
    "live_comments": "live_comment",
    "mentions": "mention",
    "messages": "message",
    "message_echoes": "message_echo",
    "message_reactions": "message_reaction",
    "messaging_postbacks": "messaging_postback",
    "messaging_referral": "messaging_referral",
    "messaging_seen": "messaging_seen",
    "messaging_optins": "messaging_optin",
    "messaging_handover": "messaging_handover",
    "messaging_policy_enforcement": "messaging_policy_enforcement",
    "standby": "standby",
    "story_insights": "story_insights",
    "response_feedback": "response_feedback",
}


def _event(field: str, value: dict[str, Any], entry: dict[str, Any]) -> NormalizedEvent:
    sender = value.get("from") or value.get("sender") or {}
    if not isinstance(sender, dict):
        sender = {}
    timestamp = str(value.get("timestamp") or value.get("created_time") or entry.get("time", ""))
    return NormalizedEvent(
        platform="instagram",
        event_type=FIELD_TO_TYPE.get(field, field),
        object_id=str(value.get("id") or value.get("media_id") or entry.get("id") or ""),
        actor_id=str(sender.get("id") or value.get("sender_id") or ""),
        target_id=str(value.get("media_id") or value.get("comment_id") or value.get("recipient_id") or ""),
        timestamp=timestamp,
        text=str(value.get("text") or value.get("message") or ""),
        extra={"field": field, "username": sender.get("username", "")},
    )


def normalize_event(payload: dict[str, Any]) -> list[NormalizedEvent]:
    """Flatten Graph and Messenger-style IG payloads into neutral events."""
    events: list[NormalizedEvent] = []
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes") or entry.get("messaging") or []
        for change in changes:
            if not isinstance(change, dict):
                continue
            if "messaging" in entry or "field" not in change:
                field = "messages" if change.get("message") else "messaging_seen"
                value = change
                event = _event(field, value, entry)
                event.extra["raw_message"] = change.get("message", {})
            else:
                field = str(change.get("field", ""))
                raw = change.get("value")
                value = raw if isinstance(raw, dict) else {"value": raw}
                event = _event(field, value, entry)
            events.append(event)
    return events
