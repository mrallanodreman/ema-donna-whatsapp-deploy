"""Threads publishing: container lifecycle and post variants."""

from __future__ import annotations

from typing import Any

from ..meta_client import MetaClient


async def create_container(client: MetaClient, token: str, **fields: Any) -> str:
    """Create a media container and return its id."""
    payload = await client.post("/me/threads", access_token=token, data=fields)
    if not isinstance(payload, dict) or not payload.get("id"):
        raise RuntimeError("Threads container creation returned no id")
    return str(payload["id"])


async def get_container_status(client: MetaClient, token: str, container_id: str) -> dict:
    """Poll container status before publishing."""
    payload = await client.get(
        f"/{container_id}", params={"fields": "id,status,error_message"}, access_token=token
    )
    return payload if isinstance(payload, dict) else {}


async def publish_container(client: MetaClient, token: str, container_id: str) -> dict:
    """Publish a ready container."""
    payload = await client.post("/me/threads_publish", access_token=token, data={"creation_id": container_id})
    return payload if isinstance(payload, dict) else {}


async def publish_text(client: MetaClient, token: str, text: str, **fields: Any) -> dict:
    """Create, verify and publish a text post."""
    body: dict[str, Any] = {"media_type": "TEXT", **fields}
    if text:
        body["text"] = text
    container_id = await create_container(client, token, **body)
    status = await get_container_status(client, token, container_id)
    if str(status.get("status", "")).upper() not in {"FINISHED", "PUBLISHED"}:
        raise RuntimeError(f"container {container_id} is not ready: {status.get('status')}")
    published = await publish_container(client, token, container_id)
    return {"container_id": container_id, "status": status, "published": published}


async def publish_image(client: MetaClient, token: str, image_url: str, caption: str = "", **fields: Any) -> dict:
    """Publish a single image with optional caption and alt text."""
    return await publish_text(
        client,
        token,
        caption,
        media_type="IMAGE",
        image_url=image_url,
        **fields,
    )


async def publish_video(client: MetaClient, token: str, video_url: str, caption: str = "", **fields: Any) -> dict:
    """Publish a video; the URL must be reachable by Meta."""
    return await publish_text(
        client,
        token,
        caption,
        media_type="VIDEO",
        video_url=video_url,
        **fields,
    )


async def publish_carousel(client: MetaClient, token: str, children: list[str], caption: str = "", **fields: Any) -> dict:
    """Publish a carousel from 2-20 existing container ids."""
    if not 2 <= len(children) <= 20:
        raise ValueError("carousel requires between 2 and 20 children")
    return await publish_text(
        client,
        token,
        caption,
        media_type="CAROUSEL",
        children=children,
        **fields,
    )


async def create_carousel_item(client: MetaClient, token: str, *, image_url: str | None = None,
                               video_url: str | None = None, alt_text: str = "") -> str:
    """Create a non-published carousel child."""
    fields: dict[str, Any] = {"is_carousel_item": True}
    if image_url:
        fields["media_type"] = "IMAGE"
        fields["image_url"] = image_url
    elif video_url:
        fields["media_type"] = "VIDEO"
        fields["video_url"] = video_url
    else:
        raise ValueError("image_url or video_url is required")
    if alt_text:
        fields["alt_text"] = alt_text
    return await create_container(client, token, **fields)


async def publish_quote(client: MetaClient, token: str, text: str, quote_post_id: str, **fields: Any) -> dict:
    """Publish a quote post."""
    return await publish_text(client, token, text, quote_post_id=quote_post_id, **fields)


async def publish_repost(client: MetaClient, token: str, repost_of_id: str, text: str = "", **fields: Any) -> dict:
    """Repost an existing Threads post."""
    return await publish_text(client, token, text, repost_of_id=repost_of_id, **fields)


async def publish_ghost(client: MetaClient, token: str, text: str, **fields: Any) -> dict:
    """Publish a ghost (unlisted) text post."""
    return await publish_text(client, token, text, is_ghost_post=True, **fields)


async def publish_poll(client: MetaClient, token: str, text: str, options: list[str],
                       duration_hours: int = 24, **fields: Any) -> dict:
    """Publish a text post with a poll attachment."""
    if len(options) < 2:
        raise ValueError("polls need at least two options")
    return await publish_text(
        client, token, text, poll_options=options, poll_duration_hours=duration_hours, **fields
    )


async def create_text_attachment(client: MetaClient, token: str, text: str, title: str = "",
                                 **fields: Any) -> dict:
    """Publish a long-form (up to 10k chars) text attachment."""
    return await publish_text(
        client, token, text, text_attachment={"text": text, "title": title}, **fields
    )


async def delete_post(client: MetaClient, token: str, post_id: str) -> dict:
    """Delete one Threads post."""
    payload = await client.delete(f"/{post_id}", access_token=token)
    return payload if isinstance(payload, dict) else {}
