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
                if not isinstance(message, dict):
                    continue
                kind = str(message.get("type", ""))
                code = ""
                unsupported_type = ""
                if kind == "text":
                    sender = str(message.get("from", ""))
                    text = ((message.get("text") or {}).get("body") or "").strip()
                elif kind == "unsupported":
                    # CTWA first messages on coexistence numbers arrive here with code
                    # 131060 ("message currently unavailable"): keep them visible in
                    # the inbox instead of dropping the whole webhook.
                    errors = message.get("errors") or []
                    if errors and isinstance(errors[0], dict):
                        code = str(errors[0].get("code", ""))
                    unsupported_type = str(
                        (message.get("unsupported") or {}).get("type", "")
                    )
                    sender = str(message.get("from") or "")
                    if not sender:
                        sender = next(
                            (
                                str(item.get("wa_id", ""))
                                for item in contacts
                                if isinstance(item, dict) and item.get("wa_id")
                            ),
                            "",
                        )
                    text = (
                        f"[Mensaje CTWA no disponible por Cloud API"
                        f"{' (' + code + ')' if code else ''}]"
                    )
                else:
                    continue
                if not sender or not text:
                    continue
                extra: dict[str, Any] = {
                    "message_id": str(message.get("id", "")),
                    "message_type": kind,
                    "waba_id": waba_id,
                    "known_contact": sender in names,
                }
                if kind == "unsupported":
                    extra["error_code"] = code
                    extra["unsupported_type"] = unsupported_type
                events.append(
                    NormalizedEvent(
                        platform="whatsapp",
                        event_type="message",
                        object_id=phone_id,
                        actor_id=sender,
                        target_id=waba_id,
                        timestamp=str(message.get("timestamp", "")),
                        text=text,
                        extra=extra,
                    )
                )
    return events
