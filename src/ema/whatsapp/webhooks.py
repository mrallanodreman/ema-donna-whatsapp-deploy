"""Normalizer for WhatsApp Business Cloud API webhook payloads."""

from __future__ import annotations

from typing import Any

from ..events import NormalizedEvent

FIELD_TO_TYPE = {
    "messages": "message",
    "smb_message_echoes": "message_echo",
    "history": "history",
    "account_update": "account_update",
}


def _message_text(message: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return display text plus extra metadata for one WhatsApp message object."""
    kind = str(message.get("type", ""))
    extra: dict[str, Any] = {}
    if kind == "text":
        return str((message.get("text") or {}).get("body") or "").strip(), extra
    if kind == "unsupported":
        errors = message.get("errors") or []
        code = ""
        if errors and isinstance(errors[0], dict):
            code = str(errors[0].get("code", ""))
        unsupported_type = str((message.get("unsupported") or {}).get("type", ""))
        extra["error_code"] = code
        extra["unsupported_type"] = unsupported_type
        text = (
            f"[Mensaje CTWA no disponible por Cloud API"
            f"{' (' + code + ')' if code else ''}]"
        )
        return text, extra
    if kind == "revoke":
        original = str((message.get("revoke") or {}).get("original_message_id", ""))
        extra["original_message_id"] = original
        return "[Mensaje eliminado]", extra
    if kind == "edit":
        edited = (message.get("edit") or {}).get("message") or {}
        if isinstance(edited, dict):
            text, inner_extra = _message_text(edited)
            extra.update(inner_extra)
            extra["original_message_id"] = str(
                (message.get("edit") or {}).get("original_message_id", "")
            )
            return text or "[Mensaje editado]", extra
        return "[Mensaje editado]", extra
    if kind == "media_placeholder":
        return "[Contenido multimedia pendiente]", extra
    # image, video, audio, document, location, contacts, interactive, etc.
    payload = message.get(kind) or {}
    caption = ""
    if isinstance(payload, dict):
        caption = str(payload.get("caption") or "")
    extra["media_type"] = kind
    return caption or f"[{kind}]", extra


def _event(
    *,
    message: dict[str, Any],
    phone_id: str,
    waba_id: str,
    actor_id: str,
    direction: str,
    known_contact: bool,
    event_type: str = "message",
) -> NormalizedEvent | None:
    text, message_extra = _message_text(message)
    if not text or not actor_id:
        return None
    extra: dict[str, Any] = {
        "message_id": str(message.get("id", "")),
        "message_type": str(message.get("type", "")),
        "waba_id": waba_id,
        "known_contact": known_contact,
        "direction": direction,
    }
    extra.update(message_extra)
    return NormalizedEvent(
        platform="whatsapp",
        event_type=event_type,
        object_id=phone_id,
        actor_id=actor_id,
        target_id=waba_id,
        timestamp=str(message.get("timestamp", "")),
        text=text,
        extra=extra,
    )


def normalize_event(payload: dict[str, Any]) -> list[NormalizedEvent]:
    """Flatten WhatsApp webhook changes into platform-neutral events."""
    if str(payload.get("object", "")).casefold() != "whatsapp_business_account":
        return []
    events: list[NormalizedEvent] = []
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        waba_id = str(entry.get("id", ""))
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            field = str(change.get("field", ""))
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") or {}
            phone_id = str(metadata.get("phone_number_id", ""))
            display_phone = str(metadata.get("display_phone_number", ""))
            contacts = value.get("contacts") or []
            names = {
                str(item.get("wa_id", ""))
                for item in contacts
                if isinstance(item, dict)
            }

            if field == "messages":
                for message in value.get("messages", []) or []:
                    if not isinstance(message, dict):
                        continue
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
                    event = _event(
                        message=message,
                        phone_id=phone_id,
                        waba_id=waba_id,
                        actor_id=sender,
                        direction="inbound",
                        known_contact=sender in names,
                    )
                    if event:
                        events.append(event)

            elif field == "smb_message_echoes":
                # Business app / companion device outbound. The business is
                # `from`; the customer is `to` and is the thread counterpart.
                for message in value.get("message_echoes", []) or []:
                    if not isinstance(message, dict):
                        continue
                    customer = str(message.get("to") or "")
                    if not customer:
                        customer = next(
                            (
                                str(item.get("wa_id", ""))
                                for item in contacts
                                if isinstance(item, dict) and item.get("wa_id")
                            ),
                            "",
                        )
                    event = _event(
                        message=message,
                        phone_id=phone_id,
                        waba_id=waba_id,
                        actor_id=customer,
                        direction="outbound",
                        known_contact=customer in names,
                        event_type="message_echo",
                    )
                    if event:
                        events.append(event)

            elif field == "history":
                for history in value.get("history", []) or []:
                    if not isinstance(history, dict):
                        continue
                    for thread in history.get("threads", []) or []:
                        if not isinstance(thread, dict):
                            continue
                        context = thread.get("context") or {}
                        thread_customer = str(
                            thread.get("id") or context.get("wa_id") or ""
                        )
                        for message in thread.get("messages", []) or []:
                            if not isinstance(message, dict):
                                continue
                            sender = str(message.get("from") or "")
                            outbound = bool(
                                display_phone and sender == display_phone
                            )
                            customer = thread_customer if outbound else sender
                            event = _event(
                                message=message,
                                phone_id=phone_id,
                                waba_id=waba_id,
                                actor_id=customer,
                                direction="outbound" if outbound else "inbound",
                                known_contact=bool(customer and customer in names),
                                event_type="history",
                            )
                            if event:
                                event.extra["history_phase"] = str(
                                    (history.get("metadata") or {}).get("phase", "")
                                )
                                events.append(event)

            elif field == "account_update":
                events.append(
                    NormalizedEvent(
                        platform="whatsapp",
                        event_type="account_update",
                        object_id=phone_id,
                        actor_id="",
                        target_id=waba_id,
                        timestamp=str(value.get("timestamp", "")),
                        text="",
                        extra={"waba_id": waba_id},
                    )
                )
    return events
