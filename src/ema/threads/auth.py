"""Threads OAuth window and token exchange."""

from __future__ import annotations

from urllib.parse import urlencode

from ..meta_client import MetaClient

THREADS_AUTHORIZE_URL = "https://threads.net/oauth/authorize"
OAUTH_URL = "https://graph.threads.com/oauth/access_token"
DEBUG_URL = "https://graph.threads.com/debug_token"
THREADS_SCOPES = (
    "threads_basic",
    "threads_content_publish",
    "threads_manage_replies",
    "threads_read_replies",
    "threads_manage_insights",
    "threads_delete",
    "threads_locations",
)


def authorization_url(
    app_id: str, redirect_uri: str, state: str, scopes: tuple[str, ...] = THREADS_SCOPES
) -> str:
    """Build the Threads authorization window URL."""
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": ",".join(scopes),
        "response_type": "code",
        "state": state,
    }
    return f"{THREADS_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(
    client: MetaClient, app_id: str, app_secret: str, code: str, redirect_uri: str
) -> dict:
    """Exchange an OAuth code for a short-lived token."""
    payload = await client.post(
        OAUTH_URL,
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    return payload if isinstance(payload, dict) else {}


async def long_lived_token(client: MetaClient, short_token: str) -> dict:
    """Upgrade a short-lived token to a long-lived one."""
    payload = await client.get(
        OAUTH_URL,
        params={"grant_type": "th_long_lived_token", "access_token": short_token},
    )
    return payload if isinstance(payload, dict) else {}


async def debug_token(client: MetaClient, app_access_token: str, input_token: str) -> dict:
    """Return /debug_token data for a Threads token."""
    payload = await client.get(
        DEBUG_URL,
        params={"input_token": input_token},
        access_token=app_access_token,
    )
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}
