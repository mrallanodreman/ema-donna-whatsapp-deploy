"""Async Graph/Threads HTTP client with retries and cursor pagination."""

from __future__ import annotations

import json
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_HOSTS = frozenset({"graph.facebook.com", "graph.threads.com"})
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class GraphError(Exception):
    """Graph API error carrying Meta diagnostic fields."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        error_subcode: int | None = None,
        fbtrace_id: str | None = None,
        error_type: str | None = None,
        status_code: int = 0,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.error_subcode = error_subcode
        self.fbtrace_id = fbtrace_id
        self.error_type = error_type
        self.status_code = status_code

    @property
    def transient(self) -> bool:
        """Whether this error is worth retrying."""
        return self.status_code in RETRYABLE_STATUSES

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], status_code: int = 0) -> GraphError:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        return cls(
            str(error.get("message") or "Graph API error"),
            code=error.get("code"),
            error_subcode=error.get("error_subcode"),
            fbtrace_id=error.get("fbtrace_id"),
            error_type=error.get("type"),
            status_code=status_code,
        )

    def diagnostic(self) -> dict[str, Any]:
        """Safe diagnostic fields for logs and audit records."""
        return {
            "message": self.message,
            "code": self.code,
            "error_subcode": self.error_subcode,
            "fbtrace_id": self.fbtrace_id,
            "status_code": self.status_code,
        }


class MetaClient:
    """Small async wrapper over httpx for Graph-style JSON APIs."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self._allowed_hosts = allowed_hosts
        self._sleep = sleep_fn or self._default_sleep
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=transport)

    @staticmethod
    async def _default_sleep(delay: float) -> None:
        import asyncio

        await asyncio.sleep(delay)

    async def __aenter__(self) -> MetaClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            parsed = urlparse(path)
            if parsed.hostname not in self._allowed_hosts:
                raise ValueError("refusing to follow an untrusted URL")
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _prepare_data(data: Mapping[str, Any] | None) -> dict[str, Any] | None:
        """Graph expects nested form values as JSON strings."""
        if data is None:
            return None
        return {
            key: json.dumps(value) if isinstance(value, (dict, list, tuple)) else value
            for key, value in data.items()
            if value is not None
        }

    def _parse(self, response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text[:2000]}

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After", "")
        if raw:
            try:
                return max(0.0, min(30.0, float(raw)))
            except ValueError:
                try:
                    when = parsedate_to_datetime(raw)
                    from datetime import datetime, timezone

                    now = datetime.now(timezone.utc)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    return max(0.0, min(30.0, (when - now).total_seconds()))
                except (TypeError, ValueError):
                    pass
        backoff = 0.25 * (2**attempt)
        return backoff + random.uniform(0, backoff / 2)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        access_token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Perform a request, retrying only 429/5xx with jitter and Retry-After."""
        query = dict(params or {})
        if access_token:
            query["access_token"] = access_token
        url = self._url(path)
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            response = await self._client.request(
                method,
                url,
                params=query,
                json=json_body,
                data=self._prepare_data(data),
                files=dict(files) if files else None,
                headers=headers,
            )
            if response.status_code in RETRYABLE_STATUSES:
                if attempt == attempts - 1:
                    raise GraphError(
                        f"transient HTTP {response.status_code}",
                        status_code=response.status_code,
                    )
                delay = self._retry_delay(response, attempt)
                logger.warning(
                    "meta transient status=%s attempt=%s/%s path=%s delay=%.2f",
                    response.status_code,
                    attempt + 1,
                    attempts,
                    urlparse(url).path,
                    delay,
                )
                await self._sleep(delay)
                continue
            payload = self._parse(response)
            if isinstance(payload, dict) and "error" in payload:
                raise GraphError.from_payload(payload, response.status_code)
            response.raise_for_status()
            return payload
        raise RuntimeError("unreachable")

    async def get(self, path: str, **kwargs: Any) -> Any:
        """GET helper."""
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        """POST helper."""
        return await self.request("POST", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        """DELETE helper."""
        return await self.request("DELETE", path, **kwargs)

    @staticmethod
    def _cursor_from_next(next_url: str) -> str | None:
        if not next_url:
            return None
        parsed = urlparse(next_url)
        if parsed.hostname and parsed.hostname not in DEFAULT_ALLOWED_HOSTS:
            return None
        cursors = parse_qs(parsed.query).get("after")
        return cursors[0] if cursors else None

    async def paginate(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        access_token: str | None = None,
        data_field: str = "data",
        max_pages: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield items following Graph `paging.next` cursors."""
        cursor: str | None = None
        for _ in range(max(1, max_pages)):
            page_params = dict(params or {})
            if cursor:
                page_params["after"] = cursor
            payload = await self.get(path, params=page_params, access_token=access_token)
            if not isinstance(payload, dict):
                return
            items = payload.get(data_field, [])
            if not isinstance(items, list):
                return
            for item in items:
                if isinstance(item, dict):
                    yield item
            next_url = str((payload.get("paging") or {}).get("next") or "")
            cursor = self._cursor_from_next(next_url)
            if not cursor:
                return
