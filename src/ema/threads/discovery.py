"""Threads discovery: user content, profiles, keywords and topics."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..meta_client import MetaClient


async def get_user_posts(client: MetaClient, token: str, user_id: str = "me", **params: Any) -> list[dict]:
    """List posts published by a user."""
    payload = await client.get(f"/{user_id}/threads", params=params, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


async def get_user_replies(client: MetaClient, token: str, user_id: str = "me", **params: Any) -> list[dict]:
    """List replies published by a user."""
    payload = await client.get(f"/{user_id}/replies", params=params, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


async def get_user_mentions(client: MetaClient, token: str, **params: Any) -> list[dict]:
    """List posts mentioning the authenticated user."""
    payload = await client.get("/me/mentions", params=params, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


async def get_profile(client: MetaClient, token: str, user_id: str = "me", **fields: Any) -> dict:
    """Read a public profile."""
    requested = fields.pop("fields", "id,username,name,threads_profile_picture_url,threads_biography")
    payload = await client.get(f"/{user_id}", params={"fields": requested, **fields}, access_token=token)
    return payload if isinstance(payload, dict) else {}


async def get_profile_posts(client: MetaClient, token: str, user_id: str, **params: Any) -> list[dict]:
    """List posts from another user's public profile."""
    return await get_user_posts(client, token, user_id, **params)


async def keyword_search(client: MetaClient, token: str, query: str, **filters: Any) -> list[dict]:
    """Search posts by keyword with optional type/author/time filters."""
    payload = await client.get(
        "/keyword_search", params={"query": query, **filters}, access_token=token
    )
    return payload.get("data", []) if isinstance(payload, dict) else []


async def topic_posts(client: MetaClient, token: str, topic_tag: str, **params: Any) -> list[dict]:
    """List posts carrying a topic tag."""
    payload = await client.get(
        f"/topics/{topic_tag}/threads", params=params, access_token=token
    )
    return payload.get("data", []) if isinstance(payload, dict) else []


async def trending_topics(client: MetaClient, token: str, **params: Any) -> list[dict]:
    """List currently trending topic tags."""
    payload = await client.get("/topics", params=params, access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


def oembed_url(url: str, access_token: str) -> str:
    """Build an oEmbed URL for a public Threads post."""
    return f"https://graph.threads.com/v1.0/oembed_thread?{urlencode({'url': url, 'access_token': access_token})}"


async def get_oembed(client: MetaClient, token: str, url: str) -> dict:
    """Resolve a Threads post URL through oEmbed."""
    payload = await client.get("/oembed_thread", params={"url": url}, access_token=token)
    return payload if isinstance(payload, dict) else {}
