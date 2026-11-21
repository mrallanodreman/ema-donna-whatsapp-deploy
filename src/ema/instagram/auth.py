"""Instagram Unified Login / Instagram Login and token lifecycle."""

from __future__ import annotations

from urllib.parse import urlencode

from ..meta_client import MetaClient

IG_SCOPES = (
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_comments",
    "instagram_manage_insights",
    "instagram_manage_messages",
    "instagram_shopping_tag_products",
    "business_management",
    "pages_show_list",
)


def authorization_url(app_id: str, redirect_uri: str, state: str,
                      scopes: tuple[str, ...] = IG_SCOPES, api_version: str = "v20.0") -> str:
    """Build the Unified Login (Facebook dialog) authorization URL."""
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": ",".join(scopes),
        "response_type": "code",
        "state": state,
    }
    return f"https://www.facebook.com/{api_version}/dialog/oauth?{urlencode(params)}"


def instagram_login_url(app_id: str, redirect_uri: str, state: str,
                        scopes: tuple[str, ...] = IG_SCOPES) -> str:
    """Build the standalone Instagram Login URL."""
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "response_type": "code",
        "state": state,
    }
    return f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"


async def exchange_code(client: MetaClient, app_id: str, app_secret: str,
                        code: str, redirect_uri: str) -> dict:
    """Exchange a code for a short-lived Graph token."""
    payload = await client.post(
        "/oauth/access_token",
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    return payload if isinstance(payload, dict) else {}


async def long_lived_token(client: MetaClient, app_secret: str, short_token: str) -> dict:
    """Exchange a short-lived token for a 60-day token."""
    payload = await client.get(
        "/oauth/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": app_secret,
            "access_token": short_token,
        },
    )
    return payload if isinstance(payload, dict) else {}


async def refresh_token(client: MetaClient, token: str) -> dict:
    """Refresh a long-lived token before expiry."""
    payload = await client.get(
        "/refresh_access_token", params={"grant_type": "ig_refresh_token", "access_token": token}
    )
    return payload if isinstance(payload, dict) else {}


async def debug_token(client: MetaClient, app_access_token: str, input_token: str) -> dict:
    """Return /debug_token data for an Instagram token."""
    payload = await client.get(
        "/debug_token", params={"input_token": input_token}, access_token=app_access_token
    )
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}
