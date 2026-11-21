"""BrowserOS MCP helper payloads. No browser action is executed here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SESSION_RULES = (
    "La sesión de BrowserOS es compartida (opencode + Claude Code). "
    "Abrir tab propia con tabs new, trabajar solo ahí, snapshot antes de interactuar "
    "y cerrar la tab al terminar. Nunca cerrar el navegador completo."
)


@dataclass(frozen=True, slots=True)
class BrowserOSBridge:
    """Builds MCP call descriptions for a human-reviewed BrowserOS session."""

    description: str = "Helper pasivo: devuelve descriptores de llamada, no los ejecuta."

    def tabs_list(self) -> dict[str, Any]:
        """Describe listing open tabs (results are not authoritative)."""
        return {"server": "browseros-neo", "tool": "tabs", "args": {"action": "list"}}

    def open_tab(self, url: str) -> dict[str, Any]:
        """Describe opening a dedicated tab."""
        return {"server": "browseros-neo", "tool": "tabs", "args": {"action": "new", "url": url}}

    def snapshot(self, page: int) -> dict[str, Any]:
        """Describe taking a snapshot to obtain fresh refs."""
        return {"server": "browseros-neo", "tool": "snapshot", "args": {"page": page}}

    def navigate(self, page: int, url: str) -> dict[str, Any]:
        """Describe navigation to a dashboard or OAuth URL."""
        return {
            "server": "browseros-neo",
            "tool": "navigate",
            "args": {"page": page, "action": "url", "url": url},
        }

    def act(self, page: int, kind: str, ref: str, value: str = "") -> dict[str, Any]:
        """Describe a ref-based action (click, fill, select, press)."""
        args: dict[str, Any] = {"page": page, "kind": kind, "ref": ref}
        if value:
            args["value" if kind in {"fill", "select"} else "text"] = value
        return {"server": "browseros-neo", "tool": "act", "args": args}

    def close_tab(self, page: int) -> dict[str, Any]:
        """Describe closing only this agent's tab."""
        return {"server": "browseros-neo", "tool": "tabs", "args": {"action": "close", "page": page}}

    def dashboard_checklist(self) -> list[str]:
        """Steps to configure the Meta app; all changes need human confirmation."""
        return [
            "Abrir tab propia en https://developers.facebook.com/apps/",
            "Verificar Business Portfolio y usar cases de Instagram + Threads.",
            "Registrar redirect URIs y verificar el verify token del webhook.",
            "Solicitar permisos: instagram_*, threads_*, business_management.",
            "Añadir testers y revisar App Review antes de pasar a Live.",
            "Cerrar la tab propia al terminar; no cerrar el navegador.",
        ]
