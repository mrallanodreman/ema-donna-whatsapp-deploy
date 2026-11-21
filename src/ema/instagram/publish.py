"""Instagram publishing: containers, stories, resumable upload and add-ons."""

from __future__ import annotations

from typing import Any

from ..meta_client import MetaClient


async def create_container(client: MetaClient, token: str, ig_user_id: str, **fields: Any) -> str:
    """Create an Instagram media container."""
    payload = await client.post(f"/{ig_user_id}/media", access_token=token, data=fields)
    if not isinstance(payload, dict) or not payload.get("id"):
        raise RuntimeError("Instagram container creation returned no id")
    return str(payload["id"])


async def get_container_status(client: MetaClient, token: str, container_id: str) -> dict:
    """Check container status and error_message."""
    payload = await client.get(
        f"/{container_id}", params={"fields": "id,status,error_message"}, access_token=token
    )
    return payload if isinstance(payload, dict) else {}


async def publish_container(client: MetaClient, token: str, ig_user_id: str, container_id: str) -> dict:
    """Publish a ready container."""
    payload = await client.post(
        f"/{ig_user_id}/media_publish", access_token=token, data={"creation_id": container_id}
    )
    return payload if isinstance(payload, dict) else {}


async def publish_media(client: MetaClient, token: str, ig_user_id: str, *,
                        image_url: str | None = None, video_url: str | None = None,
                        media_type: str | None = None, caption: str = "", **fields: Any) -> dict:
    """Create and publish image, video or reel media."""
    body: dict[str, Any] = dict(fields)
    if caption:
        body["caption"] = caption
    if image_url:
        body["image_url"] = image_url
    elif video_url:
        body["video_url"] = video_url
        body["media_type"] = media_type or "VIDEO"
    elif media_type:
        body["media_type"] = media_type
    else:
        raise ValueError("image_url, video_url or media_type is required")
    container_id = await create_container(client, token, ig_user_id, **body)
    status = await get_container_status(client, token, container_id)
    if str(status.get("status", "")).upper() not in {"FINISHED", "PUBLISHED"}:
        raise RuntimeError(f"container {container_id} is not ready: {status.get('status')}")
    published = await publish_container(client, token, ig_user_id, container_id)
    return {"container_id": container_id, "status": status, "published": published}


async def publish_reel(client: MetaClient, token: str, ig_user_id: str, video_url: str,
                       caption: str = "", **fields: Any) -> dict:
    """Publish a reel."""
    return await publish_media(
        client, token, ig_user_id, video_url=video_url, media_type="REELS", caption=caption, **fields
    )


async def publish_carousel(client: MetaClient, token: str, ig_user_id: str,
                           children: list[str], caption: str = "", **fields: Any) -> dict:
    """Publish a carousel from 2-10 child container ids."""
    if not 2 <= len(children) <= 10:
        raise ValueError("carousel requires between 2 and 10 children")
    return await publish_media(
        client, token, ig_user_id, media_type="CAROUSEL", caption=caption,
        children=children, **fields
    )


async def publish_story(client: MetaClient, token: str, ig_user_id: str,
                        image_url: str | None = None, video_url: str | None = None,
                        **fields: Any) -> dict:
    """Publish an image or video story."""
    return await publish_media(
        client, token, ig_user_id, image_url=image_url, video_url=video_url,
        media_type="STORIES", **fields
    )


async def upload_init(client: MetaClient, token: str, ig_user_id: str, *,
                      file_size: int, file_name: str, mime_type: str = "video/mp4") -> dict:
    """Initialize a resumable upload session."""
    payload = await client.post(
        f"/{ig_user_id}/uploads",
        access_token=token,
        data={
            "upload_type": "resumable",
            "file_size": file_size,
            "file_name": file_name,
            "mime_type": mime_type,
        },
    )
    return payload if isinstance(payload, dict) else {}


async def upload_transfer(client: MetaClient, token: str, session_id: str,
                          chunk: bytes, offset: int) -> dict:
    """Transfer one resumable chunk at a byte offset."""
    payload = await client.post(
        f"/upload_session/{session_id}/chunk",
        access_token=token,
        data={"offset": offset},
        files={"video_chunk": ("chunk.bin", chunk, "application/octet-stream")},
    )
    return payload if isinstance(payload, dict) else {}


async def upload_finish(client: MetaClient, token: str, session_id: str) -> dict:
    """Finish a resumable upload and obtain the media id."""
    payload = await client.post(f"/upload_session/{session_id}/finish", access_token=token)
    return payload if isinstance(payload, dict) else {}


async def attach_audio(client: MetaClient, token: str, ig_user_id: str,
                       audio_url: str, caption: str = "") -> dict:
    """Publish media using the Audio API."""
    return await publish_media(
        client, token, ig_user_id, media_type="AUDIO", audio_url=audio_url, caption=caption
    )


async def add_caption_addon(client: MetaClient, token: str, media_id: str,
                            kind: str, **options: Any) -> dict:
    """Attach a poll or prompt add-on to a published media caption."""
    if kind not in {"poll", "prompt"}:
        raise ValueError("kind must be 'poll' or 'prompt'")
    payload = await client.post(
        f"/{media_id}/caption_addons", access_token=token, data={"type": kind, **options}
    )
    return payload if isinstance(payload, dict) else {}


async def add_product_tags(client: MetaClient, token: str, media_id: str,
                           product_ids: list[str], **fields: Any) -> dict:
    """Tag catalog products in a media object."""
    payload = await client.post(
        f"/{media_id}/product_tags",
        access_token=token,
        data={"product_ids": product_ids, **fields},
    )
    return payload if isinstance(payload, dict) else {}


async def add_collaborators(client: MetaClient, token: str, media_id: str,
                            collaborator_ids: list[str]) -> dict:
    """Invite collaborators to a media object."""
    payload = await client.post(
        f"/{media_id}/collaborators", access_token=token, data={"collaborator_ids": collaborator_ids}
    )
    return payload if isinstance(payload, dict) else {}
