"""WhatsApp Cloud API webhook: signed inbound, dedupe, draft-only output."""

from __future__ import annotations

import asyncio
import json

import httpx
from pydantic import SecretStr

from ema.guardrails import AuditLog
from ema.security import sign_payload
from ema.webhooks import EventStore, create_app, dispatch

from conftest import APP_SECRET, VERIFY_TOKEN, Settings

PHONE_ID = "wa-1"


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _payload(text: str = "quiero agendar una reunión", *, phone_id: str = PHONE_ID, wamid: str = "wamid.1") -> bytes:
    return json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "593999999999", "phone_number_id": phone_id},
                    "contacts": [{"wa_id": "593999999999", "profile": {"name": "Cliente"}}],
                    "messages": [{
                        "from": "593999999999", "id": wamid,
                        "timestamp": "1700000000", "type": "text", "text": {"body": text},
                    }],
                },
            }],
        }],
    }).encode()


def _headers(body: bytes, delivery: str = "delivery-wa-1") -> dict[str, str]:
    return {
        "X-Hub-Signature-256": sign_payload(body, APP_SECRET),
        "X-Hub-Delivery": delivery,
    }


def test_whatsapp_challenge_verification(settings: Settings) -> None:
    app = create_app(settings, store=EventStore(settings.ema_idempotency_db))

    async def run() -> None:
        async with _client(app) as client:
            ok = await client.get(
                "/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.challenge": "WA-CHALLENGE",
                    "hub.verify_token": VERIFY_TOKEN,
                },
            )
            assert ok.status_code == 200 and ok.text == "WA-CHALLENGE"
            bad = await client.get(
                "/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.challenge": "WA-CHALLENGE",
                    "hub.verify_token": "wrong",
                },
            )
            assert bad.status_code == 403

    asyncio.run(run())


def test_signed_whatsapp_post_creates_draft_without_sending(settings: Settings, monkeypatch) -> None:
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
            assert result["accepted"] == ["draft"]
            assert len(result["drafts"]) == 1
            draft = result["drafts"][0]
            assert draft["status"] == "draft" and draft["send_allowed"] is False
            assert "10:00" in draft["text"] and "(hora Quito)" in draft["text"]
            assert len(audit.read()) == 1
            assert audit.read()[0]["action"] == "draft_whatsapp"

    asyncio.run(run())


def test_duplicate_whatsapp_message_is_idempotent(settings: Settings) -> None:
    app = create_app(settings, store=EventStore(settings.ema_idempotency_db))
    body = _payload()
    audit = AuditLog(settings.ema_audit_file)

    async def run() -> None:
        async with _client(app) as client:
            first = await client.post("/webhooks/whatsapp", content=body, headers=_headers(body))
            assert first.json()["accepted"] == ["draft"]
            second = await client.post("/webhooks/whatsapp", content=body, headers=_headers(body))
            assert second.json()["duplicates"]
            assert second.json()["drafts"] == []
            assert len(audit.read()) == 1

    asyncio.run(run())


def test_invalid_signature_is_rejected(settings: Settings) -> None:
    app = create_app(settings, store=EventStore(settings.ema_idempotency_db))
    body = _payload()

    async def run() -> None:
        async with _client(app) as client:
            bad = await client.post(
                "/webhooks/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=bad"},
            )
            assert bad.status_code == 403

    asyncio.run(run())


def test_foreign_phone_number_is_blocked(settings: Settings) -> None:
    app = create_app(settings, store=EventStore(settings.ema_idempotency_db))
    body = _payload(phone_id="otro-numero")

    async def run() -> None:
        async with _client(app) as client:
            response = await client.post("/webhooks/whatsapp", content=body, headers=_headers(body))
            assert response.status_code == 422
            assert AuditLog(settings.ema_audit_file).read()[0]["result"] == "blocked"

    asyncio.run(run())


def test_whatsapp_app_identity_is_independent(settings: Settings) -> None:
    wa_settings = settings.model_copy(update={
        "wa_app_secret": SecretStr("wa-app-secret"),
        "wa_webhook_verify_token": SecretStr("wa-verify-token"),
    })
    app = create_app(wa_settings, store=EventStore(wa_settings.ema_idempotency_db))
    body = _payload()
    headers = {
        "X-Hub-Signature-256": sign_payload(body, "wa-app-secret"),
        "X-Hub-Delivery": "delivery-wa-app",
    }

    async def run() -> None:
        async with _client(app) as client:
            posted = await client.post("/webhooks/whatsapp", content=body, headers=headers)
            assert posted.status_code == 200
            ok = await client.get(
                "/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.challenge": "WA",
                    "hub.verify_token": "wa-verify-token",
                },
            )
            assert ok.status_code == 200
            stale = await client.get(
                "/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.challenge": "WA",
                    "hub.verify_token": VERIFY_TOKEN,
                },
            )
            assert stale.status_code == 403

    asyncio.run(run())


def test_dispatch_uses_whatsapp_adapter_only() -> None:
    events = dispatch(json.loads(_payload()))
    assert len(events) == 1
    assert events[0].platform == "whatsapp"
    assert events[0].event_type == "message"
    assert events[0].object_id == PHONE_ID
    assert events[0].extra["message_id"] == "wamid.1"


def test_extra_subscribed_fields_and_version_hints_do_not_break_parsing() -> None:
    """Webhook payloads are structural: the subscription version only changes delivery."""
    payload = json.loads(_payload())
    changes = payload["entry"][0]["changes"]
    changes.extend([
        {"field": "account_update", "value": {"metadata": {"phone_number_id": PHONE_ID}}},
        {"field": "history", "value": {"messages": [{
            "from": "593999999999", "id": "wamid.history", "timestamp": "1699999999",
            "type": "text", "text": {"body": "mensaje antiguo"},
        }]}},
        {"field": "smb_app_state_sync", "value": {}},
        {"field": "smb_message_echoes", "value": {}},
    ])
    events = dispatch(payload)
    assert len(events) == 1
    assert events[0].extra["message_id"] == "wamid.1"
    assert events[0].text == "quiero agendar una reunión"
