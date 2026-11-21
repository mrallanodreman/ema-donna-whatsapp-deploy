"""Approval-gated Donna replies for eligible WhatsApp intents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import Settings
from ..guardrails import AuditLog, Guardrails
from ..meta_client import MetaClient
from .client import send_text

AUTO_INTENTS = frozenset({"agenda", "venta"})

ClientFactory = Callable[[], Any]


async def reply_to_message(
    settings: Settings,
    draft: dict[str, Any],
    *,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    """Send an approved draft only for agenda/venta; otherwise leave it for a human."""
    intent = str(draft.get("intent", ""))
    if intent not in AUTO_INTENTS:
        return {"sent": False, "reason": "intent requires human review"}
    text = str(draft.get("text", ""))
    if not text:
        return {"sent": False, "reason": "no eligible draft"}
    token = settings.secret(settings.wa_access_token)
    if not token:
        return {"sent": False, "reason": "no WA_ACCESS_TOKEN"}

    factory = client_factory or (
        lambda: MetaClient(settings.graph_base_url, timeout=settings.ema_http_timeout)
    )

    async def operation() -> dict[str, Any]:
        async with factory() as client:
            return await send_text(
                client,
                token,
                settings.wa_phone_number_id,
                str(draft["to"]),
                text,
            )

    guardrails = Guardrails(settings, AuditLog(settings.ema_audit_file))
    decision = await guardrails.run(
        "send",
        settings.wa_phone_number_id,
        {"text": text},
        operation,
        approve=True,
        account=settings.wa_phone_number_id,
        actor="donna",
        platform="whatsapp",
    )
    return {
        "sent": decision.allowed,
        "mode": decision.mode,
        "reasons": decision.reasons,
        "result": decision.plan.get("result"),
    }
