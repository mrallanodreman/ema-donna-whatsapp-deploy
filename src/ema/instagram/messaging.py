"""Instagram Business Messaging helpers."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..meta_client import MetaClient


async def send_text(client: MetaClient, token: str, recipient_id: str, text: str, **fields: Any) -> dict:
    """Send a text message."""
    payload = await client.post(
        "/me/messages",
        access_token=token,
        data={"recipient": {"id": recipient_id}, "message": {"text": text}, **fields},
    )
    return payload if isinstance(payload, dict) else {}


async def send_quick_replies(client: MetaClient, token: str, recipient_id: str,
                             text: str, options: list[str]) -> dict:
    """Send a message with quick reply buttons."""
    quick_replies = [
        {"content_type": "text", "title": option, "payload": option} for option in options
    ]
    payload = await client.post(
        "/me/messages",
        access_token=token,
        data={
            "recipient": {"id": recipient_id},
            "message": {"text": text, "quick_replies": quick_replies},
        },
    )
    return payload if isinstance(payload, dict) else {}


async def send_generic_template(client: MetaClient, token: str, recipient_id: str,
                                elements: list[dict[str, Any]]) -> dict:
    """Send a generic template carousel."""
    payload = await client.post(
        "/me/messages",
        access_token=token,
        data={
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {"type": "template", "payload": {"template_type": "generic", "elements": elements}}
            },
        },
    )
    return payload if isinstance(payload, dict) else {}


async def send_button_template(client: MetaClient, token: str, recipient_id: str,
                               text: str, buttons: list[dict[str, Any]]) -> dict:
    """Send a button template."""
    payload = await client.post(
        "/me/messages",
        access_token=token,
        data={
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {"template_type": "button", "text": text, "buttons": buttons},
                }
            },
        },
    )
    return payload if isinstance(payload, dict) else {}


async def sender_action(client: MetaClient, token: str, recipient_id: str,
                        action: str = "mark_seen") -> dict:
    """Send a sender action such as mark_seen or typing_on."""
    payload = await client.post(
        "/me/messages",
        access_token=token,
        data={"recipient": {"id": recipient_id}, "sender_action": action},
    )
    return payload if isinstance(payload, dict) else {}


async def set_persistent_menu(client: MetaClient, token: str, ig_user_id: str,
                              locale: str, call_to_actions: list[dict[str, Any]]) -> dict:
    """Configure the persistent menu for an IG business account."""
    payload = await client.post(
        f"/{ig_user_id}/messenger_profile",
        access_token=token,
        data={
            "persistent_menu": [
                {"locale": locale, "composer_input_disabled": False, "call_to_actions": call_to_actions}
            ]
        },
    )
    return payload if isinstance(payload, dict) else {}


async def set_ice_breakers(client: MetaClient, token: str, ig_user_id: str,
                           questions: list[str]) -> dict:
    """Configure ice breaker questions."""
    payload = await client.post(
        f"/{ig_user_id}/messenger_profile",
        access_token=token,
        data={"ice_breakers": [{"question": question} for question in questions]},
    )
    return payload if isinstance(payload, dict) else {}


def ig_me_link(username: str, referral: str = "") -> str:
    """Build an ig.me deep link with optional referral parameter."""
    base = f"https://ig.me/m/{username}"
    return f"{base}?{urlencode({'ref': referral})}" if referral else base


async def get_conversations(client: MetaClient, token: str, ig_user_id: str, **params: Any) -> list[dict]:
    """List conversations for an IG business account."""
    payload = await client.get(f"/{ig_user_id}/conversations", params=params, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


async def get_conversation(client: MetaClient, token: str, conversation_id: str, **params: Any) -> dict:
    """Read one conversation thread."""
    payload = await client.get(f"/{conversation_id}", params=params, access_token=token)
    return payload if isinstance(payload, dict) else {}
