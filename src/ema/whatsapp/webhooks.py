"""Normalizer for WhatsApp Business Cloud API webhook payloads."""

from __future__ import annotations

from typing import Any

from ..events import NormalizedEvent

FIELD_TO_TYPE = {"messages": "message", "account_update": "account_update"}


def normalize_event(payload: dict[str, Any]) -> list[NormalizedEvent]:
    """Flatten WhatsApp messages into platform-neutral events."""
    if str(payload.get("object", "")).casefold() != "whatsapp_business_account":
        return []
    events: list[NormalizedEvent] = []
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        waba_id = str(entry.get("id", ""))
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") or {}
            phone_id = str(metadata.get("phone_number_id", ""))
            contacts = value.get("contacts") or []
            names = {
                str(item.get("wa_id", ""))
                for item in contacts
                if isinstance(item, dict)
            }
            for message in value.get("messages", []) or []:
                if not isinstance(message, dict) or message.get("type") != "text":
                    continue
                sender = str(message.get("from", ""))
                text = ((message.get("text") or {}).get("body") or "").strip()
                events.append(
                    NormalizedEvent(
                        platform="whatsapp",
                        event_type="message",
                        object_id=phone_id,
                        actor_id=sender,
                        target_id=waba_id,
                        timestamp=str(message.get("timestamp", "")),
                        text=text,
                        extra={
                            "message_id": str(message.get("id", "")),
                            "message_type": "text",
                            "waba_id": waba_id,
                            "known_contact": sender in names,
                        },
                    )
                )
    return events
