"""Instagram insights, limits and utility endpoints."""

from __future__ import annotations

from typing import Any

from ..meta_client import MetaClient


async def media_insights(client: MetaClient, token: str, media_id: str,
                         metrics: tuple[str, ...] = ("impressions", "reach", "likes", "comments")) -> dict:
    """Return metrics for an Instagram media object."""
    payload = await client.get(
        f"/{media_id}/insights", params={"metric": ",".join(metrics)}, access_token=token
    )
    return payload if isinstance(payload, dict) else {}


async def user_insights(client: MetaClient, token: str, ig_user_id: str,
                        metrics: tuple[str, ...], **params: Any) -> dict:
    """Return account-level metrics."""
    payload = await client.get(
        f"/{ig_user_id}/insights", params={"metric": ",".join(metrics), **params}, access_token=token
    )
    return payload if isinstance(payload, dict) else {}


async def story_insights(client: MetaClient, token: str, story_id: str,
                         metrics: tuple[str, ...] = ("reach", "impressions", "replies")) -> dict:
    """Return story metrics."""
    return await media_insights(client, token, story_id, metrics)


async def content_publishing_limit(client: MetaClient, token: str, ig_user_id: str) -> dict:
    """Read the content publishing quota."""
    payload = await client.get(f"/{ig_user_id}/content_publishing_limit", access_token=token)
    return payload if isinstance(payload, dict) else {}


async def copyright_detection(client: MetaClient, token: str, ig_user_id: str, **params: Any) -> dict:
    """Check media for copyright status."""
    payload = await client.get(
        f"/{ig_user_id}/copyright_detection", params=params, access_token=token
    )
    return payload if isinstance(payload, dict) else {}


async def available_catalogs(client: MetaClient, token: str, ig_user_id: str) -> list[dict]:
    """List product catalogs linked to the account."""
    payload = await client.get(f"/{ig_user_id}/product_catalog_list", access_token=token)
    return payload.get("data", []) if isinstance(payload, dict) else []


async def oembed(client: MetaClient, token: str, url: str) -> dict:
    """Resolve an Instagram post URL through oEmbed."""
    payload = await client.get("/instagram_oembed", params={"url": url}, access_token=token)
    return payload if isinstance(payload, dict) else {}
