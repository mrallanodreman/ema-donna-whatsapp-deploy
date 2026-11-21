"""Threads reply moderation and post controls."""

from __future__ import annotations

from typing import Any

from ..meta_client import MetaClient


async def list_replies(client: MetaClient, token: str, post_id: str, **params: Any) -> list[dict]:
    """List replies to a post."""
    payload = await client.get(f"/{post_id}/replies", params=params, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


async def reply_to_post(client: MetaClient, token: str, post_id: str, text: str) -> dict:
    """Reply to a post as the authenticated account."""
    payload = await client.post(f"/{post_id}/replies", access_token=token, data={"text": text})
    return payload if isinstance(payload, dict) else {}


async def hide_reply(client: MetaClient, token: str, reply_id: str) -> dict:
    """Hide a reply from a post."""
    payload = await client.post(f"/{reply_id}/hide", access_token=token)
    return payload if isinstance(payload, dict) else {}


async def unhide_reply(client: MetaClient, token: str, reply_id: str) -> dict:
    """Restore a previously hidden reply."""
    payload = await client.post(f"/{reply_id}/unhide", access_token=token)
    return payload if isinstance(payload, dict) else {}


async def approve_reply(client: MetaClient, token: str, reply_id: str) -> dict:
    """Approve a reply held for moderation."""
    payload = await client.post(f"/{reply_id}/approve", access_token=token)
    return payload if isinstance(payload, dict) else {}


async def ignore_reply(client: MetaClient, token: str, reply_id: str) -> dict:
    """Reject a reply held for moderation."""
    payload = await client.post(f"/{reply_id}/ignore", access_token=token)
    return payload if isinstance(payload, dict) else {}


async def set_reply_audience(client: MetaClient, token: str, post_id: str, audience: str) -> dict:
    """Set who may reply: everyone, accounts_you_follow or mentioned_only."""
    payload = await client.post(
        f"/{post_id}", access_token=token, data={"reply_control": audience}
    )
    return payload if isinstance(payload, dict) else {}


async def pending_replies(client: MetaClient, token: str, **params: Any) -> list[dict]:
    """List replies awaiting moderation."""
    payload = await client.get("/me/replies", params={**params, "view": "pending"}, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []
