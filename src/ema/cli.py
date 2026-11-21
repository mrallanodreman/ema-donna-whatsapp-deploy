"""Readable JSON CLI; token values are never printed."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from . import instagram, threads
from .agent import Agent
from .config import Settings, get_settings
from .events import NormalizedEvent
from .meta_client import MetaClient
from .security import OAuthStateManager
from .tokens import TokenStore, StoredToken
from .whatsapp.drafts import build_draft


def emit(data: dict[str, Any]) -> None:
    """Print one JSON document."""
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


async def cmd_status(settings: Settings) -> dict[str, Any]:
    """Show sanitized status."""
    from .webhooks import EventStore

    tokens = TokenStore(settings)
    store = EventStore(settings.ema_idempotency_db)
    with store._connect() as conn:
        seen = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    return {
        **settings.sanitized(),
        "tokens": {"instagram": tokens.status("instagram"), "threads": tokens.status("threads")},
        "idempotency_records": seen,
    }


async def cmd_auth_url(settings: Settings, platform: str, redirect_uri: str) -> dict[str, Any]:
    """Generate an OAuth URL with a fresh CSRF state."""
    state_manager = OAuthStateManager(
        settings.secret(settings.ema_master_key) or settings.secret(settings.meta_app_secret)
    )
    state = state_manager.issue(platform, redirect_uri)
    app_id = settings.threads_app_id or settings.meta_app_id
    if platform == "threads":
        url = threads.auth.authorization_url(app_id, redirect_uri, state)
    else:
        url = instagram.auth.authorization_url(
            settings.meta_app_id, redirect_uri, state, api_version=settings.meta_api_version
        )
    return {"platform": platform, "url": url, "state": state, "redirect_uri": redirect_uri}


async def cmd_auth_callback(settings: Settings, platform: str, code: str,
                            redirect_uri: str) -> dict[str, Any]:
    """Exchange a code, upgrade the token and store it encrypted."""
    base = settings.threads_base_url if platform == "threads" else settings.graph_base_url
    async with MetaClient(base, timeout=settings.ema_http_timeout) as client:
        short = await (
            threads.auth.exchange_code(client, settings.threads_app_id or settings.meta_app_id,
                                       settings.secret(settings.meta_app_secret), code, redirect_uri)
            if platform == "threads"
            else instagram.auth.exchange_code(client, settings.meta_app_id,
                                              settings.secret(settings.meta_app_secret), code, redirect_uri)
        )
        token_value = str(short.get("access_token", ""))
        if not token_value:
            raise RuntimeError("token exchange returned no access_token")
        if platform == "threads":
            long_lived = await threads.auth.long_lived_token(client, token_value)
        else:
            long_lived = await instagram.auth.long_lived_token(
                client, settings.secret(settings.meta_app_secret), token_value
            )
    final_token = str(long_lived.get("access_token") or token_value)
    store = TokenStore(settings)
    stored = store.save(
        platform,
        StoredToken(access_token=final_token, token_type=str(long_lived.get("token_type", "bearer"))),
        expires_in=int(long_lived.get("expires_in", 0)) or None,
    )
    await store.aclose()
    return {
        "platform": platform,
        "stored": True,
        "token_type": stored.token_type,
        "expires_at": stored.expires_at,
    }


async def cmd_agent(settings: Settings, intent: str, approve: bool, **kwargs: Any) -> dict[str, Any]:
    """Run one EMA intent through guardrails."""
    agent = Agent(settings)
    try:
        return await agent.run(intent, approve=approve, **kwargs)
    finally:
        await agent.aclose()


async def cmd_publish_thread(settings: Settings, text: str, approve: bool) -> dict[str, Any]:
    """Publish a text post on Threads."""
    return await cmd_agent(settings, "publish_thread_text", approve, text=text)


async def cmd_publish_ig(settings: Settings, image_url: str, caption: str,
                         approve: bool) -> dict[str, Any]:
    """Publish an Instagram image through the EMA intent pipeline."""
    return await cmd_agent(
        settings, "publish_ig_image", approve, image_url=image_url, caption=caption
    )


async def cmd_reply(settings: Settings, platform: str, target: str,
                    text: str, approve: bool) -> dict[str, Any]:
    """Reply to a mention (Threads) or a DM (Instagram)."""
    intent = "reply_to_mention" if platform == "threads" else "reply_ig_dm"
    key = "post_id" if platform == "threads" else "recipient_id"
    return await cmd_agent(settings, intent, approve, **{key: target}, text=text)


async def cmd_insights(settings: Settings, platform: str, media_id: str) -> dict[str, Any]:
    """Read media insights."""
    return await cmd_agent(settings, "get_insights", False, platform=platform, media_id=media_id)


async def cmd_search(settings: Settings, query: str) -> dict[str, Any]:
    """Search Threads by keyword."""
    return await cmd_agent(settings, "search_keyword", False, query=query)


async def cmd_draft_whatsapp(
    settings: Settings,
    text: str,
    sender: str = "593999999999",
) -> dict[str, Any]:
    """Build a review-only Donna draft from local text; no network, no send."""
    event = NormalizedEvent(
        platform="whatsapp",
        event_type="message",
        object_id=settings.wa_phone_number_id,
        actor_id=sender,
        timestamp="",
        text=text,
        extra={},
    )
    return build_draft(event, settings)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="ema", description="EMA Instagram + Threads")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="sanitized configuration and token status")

    auth_url = sub.add_parser("auth-url", help="print an OAuth authorization URL")
    auth_url.add_argument("--platform", choices=["threads", "instagram"], required=True)
    auth_url.add_argument("--redirect-uri", required=True)

    callback = sub.add_parser("auth-callback", help="exchange an OAuth code and store the token")
    callback.add_argument("--platform", choices=["threads", "instagram"], required=True)
    callback.add_argument("--code", required=True)
    callback.add_argument("--redirect-uri", required=True)

    publish_thread = sub.add_parser("publish-thread", help="publish a Threads text post")
    publish_thread.add_argument("--text", required=True)
    publish_thread.add_argument("--approve", action="store_true")

    publish_ig = sub.add_parser("publish-ig", help="publish an Instagram image")
    publish_ig.add_argument("--image-url", required=True)
    publish_ig.add_argument("--caption", default="")
    publish_ig.add_argument("--approve", action="store_true")

    reply = sub.add_parser("reply", help="reply to a mention or DM")
    reply.add_argument("--platform", choices=["threads", "instagram"], required=True)
    reply.add_argument("--target", required=True, help="post id or recipient id")
    reply.add_argument("--text", required=True)
    reply.add_argument("--approve", action="store_true")

    insights = sub.add_parser("insights", help="media insights")
    insights.add_argument("--platform", choices=["threads", "instagram"], default="threads")
    insights.add_argument("--media-id", required=True)

    search = sub.add_parser("search", help="Threads keyword search")
    search.add_argument("--query", required=True)

    draft_wa = sub.add_parser("draft-whatsapp", help="build a Donna WhatsApp draft (never sends)")
    draft_wa.add_argument("--text", required=True)
    draft_wa.add_argument("--from", dest="sender", default="593999999999")

    sub.add_parser("watch", help="run the webhook server")
    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    settings = get_settings()

    if args.command == "watch":
        import uvicorn

        from .webhooks import app

        uvicorn.run(app, host=settings.ema_host, port=settings.ema_port)
        return

    commands = {
        "status": lambda: cmd_status(settings),
        "auth-url": lambda: cmd_auth_url(settings, args.platform, args.redirect_uri),
        "auth-callback": lambda: cmd_auth_callback(settings, args.platform, args.code, args.redirect_uri),
        "publish-thread": lambda: cmd_publish_thread(settings, args.text, args.approve),
        "publish-ig": lambda: cmd_publish_ig(settings, args.image_url, args.caption, args.approve),
        "reply": lambda: cmd_reply(settings, args.platform, args.target, args.text, args.approve),
        "insights": lambda: cmd_insights(settings, args.platform, args.media_id),
        "search": lambda: cmd_search(settings, args.query),
        "draft-whatsapp": lambda: cmd_draft_whatsapp(settings, args.text, args.sender),
    }
    emit(asyncio.run(commands[args.command]()))


if __name__ == "__main__":
    main()
