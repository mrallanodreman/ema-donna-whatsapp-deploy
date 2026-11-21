"""High-level EMA intents: plan first, then execute behind guardrails."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from . import instagram, threads
from .config import Settings, get_settings
from .guardrails import GuardDecision, Guardrails, ThreadsQuota
from .meta_client import MetaClient
from .tokens import TokenStore

logger = logging.getLogger(__name__)

Operation = Callable[[], Awaitable[Any]]
ClientFactory = Callable[[str], MetaClient]


@dataclass(slots=True)
class PreparedIntent:
    """Resolved intent with its deferred side effect."""

    action: str
    target: str
    payload: dict[str, Any]
    operation: Operation
    platform: str
    account: str
    quota: ThreadsQuota | None = None


class Agent:
    """Turns intents into audited dry-run plans before any API effect."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        tokens: TokenStore | None = None,
        guardrails: Guardrails | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tokens = tokens or TokenStore(self.settings)
        self.guardrails = guardrails or Guardrails(self.settings)
        self._factory = client_factory or (
            lambda base: MetaClient(base, timeout=self.settings.ema_http_timeout,
                                    max_retries=self.settings.ema_max_retries)
        )
        self._clients: dict[str, MetaClient] = {}

    def _client(self, platform: str) -> MetaClient:
        if platform not in self._clients:
            base = (
                self.settings.graph_base_url
                if platform == "instagram"
                else self.settings.threads_base_url
            )
            self._clients[platform] = self._factory(base)
        return self._clients[platform]

    async def _token(self, platform: str) -> str:
        """Return a token or empty string so dry-run planning never needs credentials."""
        try:
            return await self.tokens.get_valid_token(platform)
        except Exception as exc:
            logger.warning("no usable %s token: %s", platform, type(exc).__name__)
            return ""

    async def _quota(self, platform: str, action: str) -> ThreadsQuota | None:
        if platform != "threads" or action not in {"publish", "reply", "delete"}:
            return None
        try:
            token = await self._token("threads")
            return await threads.insights.publishing_limit(self._client("threads"), token)
        except Exception as exc:
            logger.warning("quota check failed, failing closed: %s", type(exc).__name__)
            return ThreadsQuota()

    async def _prepare(self, intent: str, **kwargs: Any) -> PreparedIntent:
        if intent == "publish_thread_text":
            text = str(kwargs["text"])
            client = self._client("threads")
            token = await self._token("threads")
            payload = {"text": text, **kwargs.get("options", {})}
            return PreparedIntent(
                "publish", f"threads:post:{text[:40]}", payload,
                lambda: threads.publish.publish_text(client, token, text, **kwargs.get("options", {})),
                "threads", self.settings.threads_user_id or "threads",
                await self._quota("threads", "publish"),
            )

        if intent == "publish_ig_image":
            image_url = str(kwargs["image_url"])
            caption = str(kwargs.get("caption", ""))
            client = self._client("instagram")
            token = await self._token("instagram")
            ig_user_id = self.settings.ig_user_id
            if not ig_user_id:
                raise ValueError("IG_USER_ID is required to publish on Instagram")
            payload = {"image_url": image_url, "caption": caption}
            return PreparedIntent(
                "publish", f"instagram:media:{image_url[:60]}", payload,
                lambda: instagram.publish.publish_media(
                    client, token, ig_user_id, image_url=image_url, caption=caption
                ),
                "instagram", ig_user_id,
            )

        if intent == "reply_to_mention":
            post_id = str(kwargs["post_id"])
            text = str(kwargs["text"])
            client = self._client("threads")
            token = await self._token("threads")
            return PreparedIntent(
                "reply", f"threads:post:{post_id}", {"post_id": post_id, "text": text},
                lambda: threads.moderation.reply_to_post(client, token, post_id, text),
                "threads", self.settings.threads_user_id or "threads",
                await self._quota("threads", "reply"),
            )

        if intent == "get_insights":
            platform = str(kwargs.get("platform", "threads"))
            media_id = str(kwargs["media_id"])
            client = self._client(platform)
            token = await self._token(platform)
            if platform == "threads":
                operation: Operation = lambda: threads.insights.media_insights(client, token, media_id)
            else:
                operation = lambda: instagram.insights.media_insights(client, token, media_id)
            return PreparedIntent("insights", f"{platform}:media:{media_id}", {"media_id": media_id},
                                  operation, platform, self.settings.ig_user_id or "instagram")

        if intent == "search_keyword":
            query = str(kwargs["query"])
            client = self._client("threads")
            token = await self._token("threads")
            return PreparedIntent(
                "search", f"threads:query:{query}", {"query": query},
                lambda: threads.discovery.keyword_search(client, token, query),
                "threads", self.settings.threads_user_id or "threads",
            )

        if intent == "reply_ig_dm":
            recipient_id = str(kwargs["recipient_id"])
            text = str(kwargs["text"])
            client = self._client("instagram")
            token = await self._token("instagram")
            return PreparedIntent(
                "send", f"instagram:recipient:{recipient_id}", {"recipient_id": recipient_id, "text": text},
                lambda: instagram.messaging.send_text(client, token, recipient_id, text),
                "instagram", self.settings.ig_user_id or "instagram",
            )

        if intent == "moderate_comment":
            comment_id = str(kwargs["comment_id"])
            action = str(kwargs.get("action", "hide"))
            text = str(kwargs.get("text", ""))
            client = self._client("instagram")
            token = await self._token("instagram")
            if action == "reply":
                operation = lambda: instagram.engagement.reply_comment(client, token, comment_id, text)
            elif action == "delete":
                operation = lambda: instagram.engagement.delete_comment(client, token, comment_id)
            elif action == "hide":
                operation = lambda: instagram.engagement.hide_comment(client, token, comment_id)
            else:
                raise ValueError(f"unsupported moderation action: {action}")
            return PreparedIntent(
                action, f"instagram:comment:{comment_id}", {"comment_id": comment_id, "text": text},
                operation, "instagram", self.settings.ig_user_id or "instagram",
            )

        raise ValueError(f"unknown intent: {intent}")

    async def plan(self, intent: str, **kwargs: Any) -> dict[str, Any]:
        """Return the dry-run plan without executing it."""
        prepared = await self._prepare(intent, **kwargs)
        decision = self.guardrails.authorize(
            prepared.action,
            prepared.target,
            prepared.payload,
            account=prepared.account,
            platform=prepared.platform,
            quota=prepared.quota,
        )
        return decision.to_dict()

    async def run(self, intent: str, *, approve: bool = False,
                  actor: str = "agent", **kwargs: Any) -> dict[str, Any]:
        """Authorize the intent and execute it only when all gates pass."""
        prepared = await self._prepare(intent, **kwargs)
        decision: GuardDecision = await self.guardrails.run(
            prepared.action,
            prepared.target,
            prepared.payload,
            prepared.operation,
            approve=approve,
            account=prepared.account,
            actor=actor,
            platform=prepared.platform,
            quota=prepared.quota,
        )
        return decision.to_dict()

    async def aclose(self) -> None:
        """Close HTTP clients opened by this agent."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
        await self.tokens.aclose()
