"""Shared sliding-window request limits for the public route APIs.

The production adapter uses one atomic Redis Lua script through Upstash REST.
The in-memory adapter is only available when explicitly selected for local or
test environments.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import os
import secrets
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx
from fastapi.responses import JSONResponse


PROTECTED_METHODS = {
    ("POST", "/api/aeds/recommendations"),
    ("GET", "/api/dev/walking-route"),
    ("GET", "/api/dev/driving-route"),
}

UPSTASH_SLIDING_WINDOW_SCRIPT = """
local now_parts = redis.call('TIME')
local now_ms = (tonumber(now_parts[1]) * 1000) + math.floor(tonumber(now_parts[2]) / 1000)
local window_ms = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms - window_ms)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry_seconds = math.max(1, math.ceil((tonumber(oldest[2]) + window_ms - now_ms) / 1000))
  redis.call('PEXPIRE', KEYS[1], window_ms)
  return {0, retry_seconds}
end
redis.call('ZADD', KEYS[1], now_ms, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window_ms)
return {1, 0}
""".strip()


class RateLimitUnavailable(RuntimeError):
    """Raised when a shared rate-limit decision cannot be made safely."""


class RateLimitStore(Protocol):
    async def consume(
        self, key: str, limit: int, window_ms: int, member: str
    ) -> tuple[bool, int]: ...


@dataclass(frozen=True)
class RateLimitPolicy:
    limit: int
    window_ms: int
    hmac_secret: bytes
    trusted_proxy: str


class MemorySlidingWindowStore:
    """Local/test-only store. Share one instance to model multiple app workers."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._events: dict[str, list[int]] = {}
        self._lock = asyncio.Lock()

    async def consume(self, key: str, limit: int, window_ms: int, member: str):
        del member  # Event timestamps are sufficient for the single-process adapter.
        now_ms = int(self._clock() * 1000)
        cutoff = now_ms - window_ms
        async with self._lock:
            events = [stamp for stamp in self._events.get(key, []) if stamp > cutoff]
            if len(events) >= limit:
                retry_ms = events[0] + window_ms - now_ms
                self._events[key] = events
                return False, max(1, (retry_ms + 999) // 1000)
            events.append(now_ms)
            self._events[key] = events
            return True, 0


class UpstashRedisRestStore:
    """Redis-compatible shared store using Upstash's HTTPS REST command API."""

    def __init__(self, url: str, token: str, timeout_seconds: float = 2.0):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("UPSTASH_REDIS_REST_URL must be an HTTPS endpoint")
        self.url = url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    async def consume(self, key: str, limit: int, window_ms: int, member: str):
        command = [
            "EVAL",
            UPSTASH_SLIDING_WINDOW_SCRIPT,
            "1",
            key,
            str(window_ms),
            str(limit),
            member,
        ]
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.url,
                    json=command,
                    headers={"Authorization": f"Bearer {self.token}"},
                )
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(result, list) or len(result) != 2:
                raise RateLimitUnavailable("invalid shared-store response")
            allowed, retry_after = result
            if allowed not in (0, 1) or isinstance(allowed, bool):
                raise RateLimitUnavailable("invalid shared-store decision")
            if isinstance(retry_after, bool) or not isinstance(retry_after, int):
                raise RateLimitUnavailable("invalid shared-store retry value")
            return allowed == 1, max(0, retry_after)
        except RateLimitUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise RateLimitUnavailable("shared-store request failed") from None


class UnavailableRateLimitStore:
    async def consume(self, key: str, limit: int, window_ms: int, member: str):
        raise RateLimitUnavailable("shared rate-limit store is not configured")


def _runtime_is_deployed() -> bool:
    return os.getenv("VERCEL_ENV", "").strip().lower() in {"production", "preview"} or os.getenv(
        "APP_ENV", ""
    ).strip().lower() == "production"


def policy_and_store_from_env():
    """Return (policy, store, safe_config_error); never exposes configuration values."""
    try:
        mode = os.getenv("RATE_LIMIT_STORE", "").strip().lower()
        app_env = os.getenv("APP_ENV", "").strip().lower()
        deployed = _runtime_is_deployed()
        if mode not in {"memory", "upstash"}:
            raise ValueError("RATE_LIMIT_STORE is not configured")
        if mode == "memory" and (deployed or app_env not in {"development", "local", "test"}):
            raise ValueError("memory store is restricted to explicit local/test use")

        raw_limit = os.getenv("RATE_LIMIT_LIMIT", "10")
        raw_window = os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")
        limit = int(raw_limit)
        window_seconds = int(raw_window)
        if not 1 <= limit <= 10000 or not 1 <= window_seconds <= 3600:
            raise ValueError("rate-limit settings are outside supported bounds")

        trusted_proxy = os.getenv("RATE_LIMIT_TRUSTED_PROXY", "").strip().lower()
        if trusted_proxy not in {"peer", "vercel"}:
            raise ValueError("RATE_LIMIT_TRUSTED_PROXY must be peer or vercel")
        if deployed and trusted_proxy != "vercel":
            raise ValueError("deployed Vercel runtime requires the Vercel client-IP header")

        secret = os.getenv("RATE_LIMIT_HMAC_SECRET", "").encode("utf-8")
        if len(secret) < 32:
            raise ValueError("RATE_LIMIT_HMAC_SECRET must be at least 32 bytes")

        policy = RateLimitPolicy(
            limit=limit,
            window_ms=window_seconds * 1000,
            hmac_secret=secret,
            trusted_proxy=trusted_proxy,
        )
        if mode == "memory":
            return policy, MemorySlidingWindowStore(), None

        url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
        token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
        if not url or not token:
            raise ValueError("shared Redis REST settings are incomplete")
        return policy, UpstashRedisRestStore(url, token), None
    except (ValueError, TypeError):
        return None, UnavailableRateLimitStore(), "rate limit is not safely configured"


def normalize_ip(raw: str) -> str:
    address = ipaddress.ip_address(raw.strip())
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped.compressed
    return address.compressed


def client_ip_from_scope(scope, trusted_proxy: str) -> str:
    if trusted_proxy == "vercel":
        headers = {name.lower(): value for name, value in scope.get("headers", [])}
        raw = headers.get(b"x-forwarded-for", b"").decode("ascii", errors="strict").strip()
        # Vercel overwrites this header with the requesting public IP. Reject lists and
        # malformed values instead of trusting an arbitrary first/last-hop convention.
        if not raw or "," in raw:
            raise ValueError("trusted client IP header is missing or ambiguous")
        return normalize_ip(raw)
    client = scope.get("client")
    if not client or not client[0]:
        raise ValueError("client peer address is unavailable")
    return normalize_ip(str(client[0]))


def hashed_client_key(policy: RateLimitPolicy, address: str) -> str:
    digest = hmac.new(policy.hmac_secret, address.encode("ascii"), hashlib.sha256).hexdigest()
    return f"lifetime:rate-limit:v1:{digest}"


def _service_unavailable():
    return JSONResponse(
        {"detail": "Rate limit service unavailable"},
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


class RateLimitMiddleware:
    """Fail-closed ASGI gate that runs before endpoint validation and dependencies."""

    def __init__(self, app, runtime_state):
        self.app = app
        self.state = runtime_state

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "").upper()
        path = scope.get("path", "")
        if method == "OPTIONS" or (method, path) not in PROTECTED_METHODS:
            await self.app(scope, receive, send)
            return

        policy = getattr(self.state, "rate_limit_policy", None)
        store = getattr(self.state, "rate_limit_store", None)
        config_error = getattr(self.state, "rate_limit_config_error", None)
        if policy is None or store is None or config_error:
            await _service_unavailable()(scope, receive, send)
            return
        try:
            address = client_ip_from_scope(scope, policy.trusted_proxy)
            key = hashed_client_key(policy, address)
            allowed, retry_after = await store.consume(
                key, policy.limit, policy.window_ms, secrets.token_hex(16)
            )
        except Exception:
            await _service_unavailable()(scope, receive, send)
            return

        if not allowed:
            response = JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={
                    "Retry-After": str(max(1, retry_after)),
                    "Cache-Control": "no-store",
                    "X-RateLimit-Source": "lifetime",
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
