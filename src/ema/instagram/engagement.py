"""Instagram comment moderation, mentions, discovery and creator tools."""

from __future__ import annotations

from typing import Any

from ..meta_client import MetaClient


async def get_comments(client: MetaClient, token: str, media_id: str, **params: Any) -> list[dict]:
    """List comments on a media object."""
    payload = await client.get(f"/{media_id}/comments", params=params, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


async def reply_comment(client: MetaClient, token: str, comment_id: str, text: str) -> dict:
    """Reply to a comment."""
    payload = await client.post(
        f"/{comment_id}/replies", access_token=token, data={"message": text}
    )
    return payload if isinstance(payload, dict) else {}


async def delete_comment(client: MetaClient, token: str, comment_id: str) -> dict:
    """Delete a comment."""
    payload = await client.delete(f"/{comment_id}", access_token=token)
    return payload if isinstance(payload, dict) else {}


async def hide_comment(client: MetaClient, token: str, comment_id: str, hide: bool = True) -> dict:
    """Hide or unhide a comment."""
    payload = await client.post(f"/{comment_id}", access_token=token, data={"hide": hide})
    return payload if isinstance(payload, dict) else {}


async def unhide_comment(client: MetaClient, token: str, comment_id: str) -> dict:
    """Unhide a comment."""
    return await hide_comment(client, token, comment_id, hide=False)


async def get_mentions(client: MetaClient, token: str, ig_user_id: str, **params: Any) -> list[dict]:
    """List media in which the business account was tagged."""
    payload = await client.get(f"/{ig_user_id}/tags", params=params, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


async def hashtag_search(client: MetaClient, token: str, query: str) -> list[dict]:
    """Find hashtag ids by name."""
    payload = await client.get("/ig_hashtag_search", params={"q": query}, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


async def hashtag_media(client: MetaClient, token: str, hashtag_id: str, ig_user_id: str,
                        **params: Any) -> list[dict]:
    """List public media for a hashtag."""
    payload = await client.get(
        f"/ig_hashtag/{hashtag_id}/recent_media",
        params={"user_id": ig_user_id, **params},
        access_token=token,
    )
    return payload.get("data", []) if isinstance(payload, dict) else []


async def business_discovery(client: MetaClient, token: str, ig_user_id: str,
                             username: str, **fields: Any) -> dict:
    """Read a discoverable business account profile."""
    requested = fields.pop("fields", "id,username,name,followers_count,media_count,website")
    payload = await client.get(
        f"/{ig_user_id}/business_discovery",
        params={"username": username, "fields": requested, **fields},
        access_token=token,
    )
    return payload.get("data", payload) if isinstance(payload, dict) else {}


async def creator_discovery(client: MetaClient, token: str, username: str, **fields: Any) -> dict:
    """Read a public creator profile for discovery."""
    requested = fields.pop("fields", "id,username,name,followers_count,media_count")
    payload = await client.get(
        "/business_discovery", params={"username": username, "fields": requested, **fields},
        access_token=token,
    )
    return payload.get("data", payload) if isinstance(payload, dict) else {}


async def creator_messaging(client: MetaClient, token: str, ig_user_id: str,
                            recipient_id: str, message: str) -> dict:
    """Send a discoverer message to a creator."""
    return await client.post(
        f"/{ig_user_id}/messages",
        access_token=token,
        data={"recipient": {"id": recipient_id}, "message": {"text": message}},
    )


async def private_reply(client: MetaClient, token: str, ig_user_id: str,
                        comment_id: str, text: str) -> dict:
    """Send a private reply to a comment."""
    payload = await client.post(
        f"/{ig_user_id}/messages",
        access_token=token,
        data={
            "recipient": {"comment_id": comment_id},
            "message": {"text": text},
            "is_private_reply": True,
        },
    )
    return payload if isinstance(payload, dict) else {}
