"""Donna's WhatsApp draft-only responder: pure logic, no network and no sends."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal

from ..config import Settings
from ..events import NormalizedEvent

Intent = Literal["agenda", "venta", "soporte", "operacion", "ruido", "escalado"]


class DraftError(ValueError):
    """Raised when an inbound event cannot safely produce a draft."""


_ESCALATION = (
    "abogado", "demanda", "sri", "contrato", "pago atrasado", "factura",
    "credencial", "contraseña", "password", "token", "clave de acceso",
)
_BOT_NOISE = ("uber eats", "pedidosya", "pedidos ya", "notificación automática")
_VENTA = ("precio", "cuesta", "costo", "cotización", "cotizacion", "presupuesto")
_SOPORTE = ("soporte", "no funciona", "error", "ayuda")
_OPERACION = ("envío", "envio", "dirección", "direccion", "gps", "motorizado", "pedido")
_AGENDA = (
    "agendar", "agenda", "reunión", "reunion", "cita", "hablar",
    "ver la propuesta", "llamada", "cuándo", "cuando", "disponible",
    "dispionible", "me confirma", "estoy a la espera", "pendiente",
)
_RECIPIENT = re.compile(r"^\+?[0-9]{7,15}$")

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def classify(text: str) -> Intent:
    """Classify inbound text using allowlisted keywords; never execute its content."""
    value = text.casefold()
    if any(word in value for word in _ESCALATION):
        return "escalado"
    if any(word in value for word in _BOT_NOISE):
        return "ruido"
    if any(word in value for word in _VENTA):
        return "venta"
    if any(word in value for word in _SOPORTE):
        return "soporte"
    if any(word in value for word in _OPERACION):
        return "operacion"
    if any(word in value for word in _AGENDA) or "gracias" in value:
        return "agenda"
    return "ruido"


def next_business_day(now: datetime) -> datetime:
    """Return the next weekday, skipping Saturday and Sunday."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _greeting(hour: int) -> str:
    if hour < 12:
        return "Buenos días"
    if hour < 19:
        return "Buenas tardes"
    return "Buenas noches"


def _draft_text(intent: Intent, *, now: datetime, day: datetime) -> str:
    greeting = _greeting(now.hour)
    weekday = _WEEKDAYS[day.weekday()]
    if intent == "agenda":
        return (
            f"{greeting}. Recibí su mensaje y tengo disponibilidad para revisarlo. "
            f"Le propongo {weekday} {day.date().isoformat()} a las 10:00 o a las 16:00 "
            "(hora Quito), por llamada de 15 minutos. ¿Le confirmo alguna de las dos?"
        )
    if intent == "venta":
        return (
            f"{greeting}. El valor depende del alcance y no quiero darle un número suelto. "
            "Prefiero confirmarlo en una llamada de 10 minutos mañana a las 10:00 o a las 16:00 "
            "(hora Quito). ¿Le confirmo alguna de las dos?"
        )
    if intent == "escalado":
        return (
            f"{greeting}. Ese punto necesita la revisión de Allan. "
            "Le confirmo hoy antes de las 17:00 (hora Quito). ¿Me deja su nombre para identificarlo?"
        )
    if intent == "soporte":
        return (
            f"{greeting}. Lo reviso con el equipo y le confirmo hoy antes de las 17:00 "
            "(hora Quito). ¿Me confirma que este chat es el canal para responderle?"
        )
    if intent == "operacion":
        return (
            f"{greeting}. La coordinación del envío la maneja el equipo de logística; "
            "yo se la paso ahora. ¿Me confirma que compartimos la ubicación en este mismo chat?"
        )
    return ""


def build_draft(
    event: NormalizedEvent,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build an approval-only draft. Never sends, never echoes inbound text."""
    if event.platform != "whatsapp":
        raise DraftError("event is not a WhatsApp message")
    phone_id = settings.wa_phone_number_id.strip()
    allowed = {phone_id.lower(), *settings.allowlist}
    if not phone_id or event.object_id.lower() not in allowed:
        raise DraftError("phone number id is not configured or allowlisted")
    if not _RECIPIENT.fullmatch(event.actor_id):
        raise DraftError("recipient is not a valid phone number")

    intent = classify(event.text)
    current = now or datetime.now()
    day = next_business_day(current)
    text = _draft_text(intent, now=current, day=day)
    if text.count("?") > 1:
        raise DraftError("draft may contain only one question")

    return {
        "status": "draft" if text else "ignored",
        "to": event.actor_id,
        "phone_number_id": settings.wa_phone_number_id,
        "wamid": event.extra.get("message_id"),
        "intent": intent,
        "date": day.date().isoformat(),
        "text": text,
        "requires_human": True,
        "escalated": intent == "escalado",
        "send_allowed": False,
    }
