"""Threads insights and publishing quota."""

from __future__ import annotations

from typing import Any

from ..guardrails import ThreadsQuota
from ..meta_client import MetaClient


async def media_insights(client: MetaClient, token: str, media_id: str,
                         metrics: tuple[str, ...] = ("views", "likes", "replies", "reposts", "quotes", "clicks")) -> dict:
    """Return metrics for a Threads media object."""
    payload = await client.get(
        f"/{media_id}/insights", params={"metric": ",".join(metrics)}, access_token=token
    )
    return payload if isinstance(payload, dict) else {}


async def user_insights(client: MetaClient, token: str, metrics: tuple[str, ...],
                        **params: Any) -> dict:
    """Return account-level metrics for a period."""
    payload = await client.get(
        "/me/threads_insights", params={"metric": ",".join(metrics), **params}, access_token=token
    )
    return payload if isinstance(payload, dict) else {}


async def followers(client: MetaClient, token: str, **params: Any) -> dict:
    """Return follower metrics."""
    return await user_insights(client, token, ("followers_count",), **params)


async def demographics(client: MetaClient, token: str, **params: Any) -> dict:
    """Return audience demographics."""
    return await user_insights(client, token, ("audience_countries", "audience_gender_age"), **params)


async def publishing_limit(client: MetaClient, token: str) -> ThreadsQuota:
    """Read remaining Threads publishing quota buckets."""
    payload = await client.get("/threads_publishing_limit", access_token=token)
    return ThreadsQuota.from_payload(payload if isinstance(payload, dict) else {})
