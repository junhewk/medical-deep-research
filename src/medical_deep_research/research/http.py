from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx


RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class RateLimit:
    min_interval_seconds: float = 0.0


_JSON_CACHE: dict[tuple[str, str], tuple[float, Any]] = {}
_HOST_LOCKS: dict[str, asyncio.Lock] = {}
_HOST_LAST_REQUEST: dict[str, float] = {}


def clear_http_cache() -> None:
    _JSON_CACHE.clear()


def reset_rate_limits() -> None:
    _HOST_LAST_REQUEST.clear()


def _cache_key(url: str, params: Mapping[str, object] | None) -> tuple[str, str]:
    if not params:
        return (url, "")
    pairs = tuple(sorted((str(key), str(value)) for key, value in params.items()))
    return (url, repr(pairs))


def _host(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.netloc or parsed.path


async def _respect_rate_limit(url: str, rate_limit: RateLimit | None) -> None:
    if not rate_limit or rate_limit.min_interval_seconds <= 0:
        return
    host = _host(url)
    lock = _HOST_LOCKS.setdefault(host, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        next_allowed = (
            _HOST_LAST_REQUEST.get(host, 0.0) + rate_limit.min_interval_seconds
        )
        if next_allowed > now:
            await asyncio.sleep(next_allowed - now)
        _HOST_LAST_REQUEST[host] = time.monotonic()


def _retry_delay(response: httpx.Response, attempt: int, backoff_base: float) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return max(0.0, min(float(retry_after), 15.0))
        except ValueError:
            pass
    return max(0.0, backoff_base * (2**attempt))


async def request(
    method: str,
    url: str,
    *,
    params: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: httpx.Timeout | float | None = None,
    retries: int = 2,
    backoff_base: float = 0.5,
    rate_limit: RateLimit | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.Response:
    attempts = max(1, retries + 1)
    response: httpx.Response | None = None
    async with httpx.AsyncClient(
        timeout=timeout,
        headers=dict(headers or {}),
        transport=transport,
    ) as client:
        for attempt in range(attempts):
            await _respect_rate_limit(url, rate_limit)
            response = await client.request(method, url, params=params)
            if response.status_code not in RETRY_STATUSES or attempt == attempts - 1:
                return response
            await asyncio.sleep(_retry_delay(response, attempt, backoff_base))
    assert response is not None
    return response


async def get_json(
    url: str,
    *,
    params: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: httpx.Timeout | float | None = None,
    retries: int = 2,
    backoff_base: float = 0.5,
    cache_ttl: float | None = 600.0,
    rate_limit: RateLimit | None = None,
    looks_valid: Callable[[Any], bool] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Any:
    key = _cache_key(url, params)
    now = time.monotonic()
    if cache_ttl and key in _JSON_CACHE:
        expires_at, data = _JSON_CACHE[key]
        if expires_at > now:
            return data
        _JSON_CACHE.pop(key, None)

    response = await request(
        "GET",
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        retries=retries,
        backoff_base=backoff_base,
        rate_limit=rate_limit,
        transport=transport,
    )
    response.raise_for_status()
    data = response.json()
    valid = bool(data) and (looks_valid(data) if looks_valid else True)
    if cache_ttl and valid:
        _JSON_CACHE[key] = (now + cache_ttl, data)
    return data


async def get_text(
    url: str,
    *,
    params: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: httpx.Timeout | float | None = None,
    retries: int = 2,
    backoff_base: float = 0.5,
    rate_limit: RateLimit | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    response = await request(
        "GET",
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        retries=retries,
        backoff_base=backoff_base,
        rate_limit=rate_limit,
        transport=transport,
    )
    response.raise_for_status()
    return response.text
