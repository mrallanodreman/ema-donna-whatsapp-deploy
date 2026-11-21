"""WhatsApp Cloud API outbound helper. Never called without guardrail approval."""

from __future__ import annotations

from typing import Any

from ..meta_client import MetaClient


async def send_text(
    client: MetaClient,
    token: str,
    phone_number_id: str,
    to: str,
    text: str,
    **fields: Any,
) -> dict[str, Any]:
    """Send one text message through the WhatsApp Cloud API."""
    payload = await client.post(
        f"/{phone_number_id}/messages",
        json_body={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text, "preview_url": False},
            **fields,
        },
        access_token=token,
    )
    return payload if isinstance(payload, dict) else {}
