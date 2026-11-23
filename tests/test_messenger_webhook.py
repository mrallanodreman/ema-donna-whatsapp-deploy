"""Meta Page Messenger webhook: signed inbound, draft-only, no auto-send."""

from __future__ import annotations

import asyncio
import json

import httpx

from ema.guardrails import AuditLog
from ema.security import sign_payload
from ema.webhooks import EventStore, create_app

from conftest import APP_SECRET, VERIFY_TOKEN, Settings

PAGE_ID = "page-1"
PSID = "1234567890123456"


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _payload(
    text: str = "¿cuál es el costo mínimo por unidad?",
    *,
    page_id: str = PAGE_ID,
    mid: str = "m_1",
    echo: bool = False,
) -> bytes:
    sender, recipient = (page_id, PSID) if echo else (PSID, page_id)
    return json.dumps({
        "object": "page",
        "entry": [{
            "id": page_id,
            "time": 1700000000,
            "messaging": [{
                "sender": {"id": sender},
                "recipient": {"id": recipient},
                "timestamp": 1700000000,
                "message": {
                    "mid": mid,
                    "text": text,
                    "is_echo": echo,
                },
            }],
        }],
    }).encode()


def _headers(body: bytes, delivery: str = "delivery-messenger-1") -> dict[str, str]:
    return {
        "X-Hub-Signature-256": sign_payload(body, APP_SECRET),
        "X-Hub-Delivery": delivery,
    }


def test_signed_messenger_post_creates_draft_without_sending(settings: Settings, monkeypatch) -> None:
    from ema.meta_client import MetaClient

    def _forbidden(*args, **kwargs):
        raise AssertionError("draft-only must not call Graph API")

    monkeypatch.setattr(MetaClient, "post", _forbidden)
    app = create_app(settings, store=EventStore(settings.ema_idempotency_db))
    body = _payload()
    audit = AuditLog(settings.ema_audit_file)

    async def run() -> None:
        async with _client(app) as client:
            response = await client.post("/webhooks/whatsapp", content=body, headers=_headers(body))
            assert response.status_code == 200
            result = response.json()
            assert result["accepted"] == ["message_inbound", "draft"]
            assert len(result["drafts"]) == 1
            draft = result["drafts"][0]
            assert draft["platform"] == "messenger"
            assert draft["status"] == "draft" and draft["send_allowed"] is False
            assert draft["to"] == PSID and draft["channel_id"] == PAGE_ID
            assert result["sends"][0]["sent"] is False
            assert "hora Quito" in draft["text"]
            audit_rows = [e for e in audit.read() if e["action"] == "draft_messenger"]
            assert len(audit_rows) == 1 and audit_rows[0]["result"] == "draft"

    asyncio.run(run())


def test_messenger_echo_does_not_create_draft(settings: Settings) -> None:
    app = create_app(settings, store=EventStore(settings.ema_idempotency_db))
    body = _payload(echo=True)

    async def run() -> None:
        async with _client(app) as client:
            response = await client.post("/webhooks/whatsapp", content=body, headers=_headers(body))
            assert response.status_code == 200
            result = response.json()
            assert result["accepted"] == ["message_outbound"]
            assert result["drafts"] == []

    asyncio.run(run())


def test_messenger_duplicate_is_idempotent(settings: Settings) -> None:
    app = create_app(settings, store=EventStore(settings.ema_idempotency_db))
    body = _payload()

    async def run() -> None:
        async with _client(app) as client:
            first = await client.post("/webhooks/whatsapp", content=body, headers=_headers(body))
            assert first.json()["accepted"] == ["message_inbound", "draft"]
            second = await client.post("/webhooks/whatsapp", content=body, headers=_headers(body))
            assert second.json()["duplicates"]
            assert second.json()["drafts"] == []

    asyncio.run(run())


def test_foreign_messenger_page_is_blocked(settings: Settings) -> None:
    app = create_app(settings, store=EventStore(settings.ema_idempotency_db))
    body = _payload(page_id="other-page")

    async def run() -> None:
        async with _client(app) as client:
            response = await client.post("/webhooks/whatsapp", content=body, headers=_headers(body))
            assert response.status_code == 422
            row = AuditLog(settings.ema_audit_file).read()[0]
            assert row["action"] == "draft_messenger" and row["result"] == "blocked"

    asyncio.run(run())


def test_messenger_challenge_uses_same_verify_token(settings: Settings) -> None:
    app = create_app(settings, store=EventStore(settings.ema_idempotency_db))

    async def run() -> None:
        async with _client(app) as client:
            ok = await client.get(
                "/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.challenge": "PAGE-CHALLENGE",
                    "hub.verify_token": VERIFY_TOKEN,
                },
            )
            assert ok.status_code == 200 and ok.text == "PAGE-CHALLENGE"

    asyncio.run(run())
