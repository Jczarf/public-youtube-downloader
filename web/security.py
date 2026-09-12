from __future__ import annotations

import asyncio
import ipaddress
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name: str, default: Iterable[str] = ()) -> list[str]:
    raw = os.getenv(name)
    values = list(default) if raw is None else raw.split(",")
    return [value.strip() for value in values if value.strip()]


def allowed_hosts() -> list[str]:
    values = env_csv(
        "WEB_ALLOWED_HOSTS",
        default=("localhost", "127.0.0.1", "[::1]"),
    )
    # A wildcard makes TrustedHostMiddleware ineffective. Fail closed instead
    # of letting one environment-variable typo silently disable the control.
    safe = [value for value in values if value != "*"]
    return safe or ["localhost", "127.0.0.1", "[::1]"]


def trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = []
    for value in env_csv("WEB_TRUSTED_PROXY_CIDRS"):
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            continue

        # Trusting the whole Internet turns X-Forwarded-For into an attacker-
        # controlled rate-limit identity. Never accept default routes here.
        if network.prefixlen == 0:
            continue
        networks.append(network)
    return tuple(networks)


def _parse_ip(value: str | None):
    if not value:
        return None
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """Return client IP without trusting spoofable forwarded headers by default.

    X-Forwarded-For is used only when the immediate TCP peer is inside a
    network explicitly configured in WEB_TRUSTED_PROXY_CIDRS. The chain is
    walked from right to left, removing trusted proxies until the first
    untrusted hop is found.
    """

    peer_text = request.client.host if request.client else ""
    peer = _parse_ip(peer_text)
    trusted = trusted_proxy_networks()

    if peer is None or not trusted:
        return peer_text or "unknown"

    if not any(peer in network for network in trusted):
        return str(peer)

    forwarded = request.headers.get("x-forwarded-for", "")
    chain = [_parse_ip(part) for part in forwarded.split(",")]
    chain = [item for item in chain if item is not None]
    chain.append(peer)

    for address in reversed(chain):
        if any(address in network for network in trusted):
            continue
        return str(address)

    return str(chain[0]) if chain else str(peer)


@dataclass(frozen=True)
class RateRule:
    group: str
    limit: int
    window_seconds: int


class InMemoryRateLimiter:
    def __init__(self, *, max_keys: int = 4096) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._max_keys = max(128, max_keys)

    async def allow(self, client: str, rule: RateRule) -> bool:
        if rule.limit <= 0:
            return True

        now = time.monotonic()
        cutoff = now - rule.window_seconds
        key = (client, rule.group)

        async with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= rule.limit:
                return False

            bucket.append(now)

            if len(self._events) > self._max_keys:
                self._prune_locked(now)

        return True

    def _prune_locked(self, now: float) -> None:
        # Conservative bounded-memory cleanup. Empty/old buckets go first;
        # if an attacker rotates identities faster than cleanup, oldest dict
        # entries are evicted to keep memory usage bounded.
        stale_before = now - 3600
        for key in list(self._events):
            bucket = self._events[key]
            while bucket and bucket[0] <= stale_before:
                bucket.popleft()
            if not bucket:
                self._events.pop(key, None)

        while len(self._events) > self._max_keys:
            first_key = next(iter(self._events))
            self._events.pop(first_key, None)


RATE_LIMITER = InMemoryRateLimiter()


def _env_limit(name: str, default: int, maximum: int = 10000) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(0, min(value, maximum))


def rate_rule(request: Request) -> RateRule | None:
    path = request.url.path

    if path == "/api/v1/resolve":
        return RateRule(
            "resolve",
            _env_limit("WEB_RATE_RESOLVE_PER_MINUTE", 8),
            60,
        )
    if path == "/api/v1/plan":
        return RateRule(
            "plan",
            _env_limit("WEB_RATE_PLAN_PER_MINUTE", 30),
            60,
        )
    if path.startswith("/api/v1/merge/") or path.startswith("/api/v1/convert/"):
        return RateRule(
            "process",
            _env_limit("WEB_RATE_PROCESS_PER_MINUTE", 6),
            60,
        )
    if path.startswith("/api/v1/stream/"):
        return RateRule(
            "relay",
            _env_limit("WEB_RATE_RELAY_PER_MINUTE", 180),
            60,
        )
    if path.startswith("/api/v1/direct/"):
        return RateRule(
            "direct",
            _env_limit("WEB_RATE_DIRECT_PER_MINUTE", 60),
            60,
        )
    return None


async def rate_limit_response(request: Request) -> JSONResponse | None:
    rule = rate_rule(request)
    if rule is None:
        return None

    if await RATE_LIMITER.allow(client_ip(request), rule):
        return None

    return JSONResponse(
        status_code=429,
        content={"detail": "Muitas solicitações. Tente novamente mais tarde."},
        headers={
            "Cache-Control": "no-store",
            "Retry-After": "10",
        },
    )


def add_security_headers(response, *, hsts: bool) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "serial=(), bluetooth=(), browsing-topics=()"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "base-uri 'none'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data: https://*.ytimg.com; "
        "connect-src 'self'; "
        "media-src 'self' https://*.googlevideo.com; "
        "worker-src 'self'; "
        "manifest-src 'self'"
    )

    if hsts:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    if "server" in response.headers:
        del response.headers["server"]


class ActiveClientLimiter:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        client: str,
        group: str,
        limit: int,
    ) -> bool:
        if limit <= 0:
            return True

        key = (client, group)
        async with self._lock:
            current = self._counts.get(key, 0)
            if current >= limit:
                return False
            self._counts[key] = current + 1
            return True

    async def release(self, client: str, group: str) -> None:
        key = (client, group)
        async with self._lock:
            current = self._counts.get(key, 0)
            if current <= 1:
                self._counts.pop(key, None)
            else:
                self._counts[key] = current - 1


ACTIVE_CLIENTS = ActiveClientLimiter()


def active_limit(group: str, default: int) -> int:
    env_name = f"WEB_ACTIVE_{group.upper()}_PER_CLIENT"
    return _env_limit(env_name, default, maximum=32)


class RequestBodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Limit API request bodies before JSON/Pydantic parsing."""

    def __init__(self, app, max_body_bytes: int = 16 * 1024) -> None:
        self.app = app
        self.max_body_bytes = max(1024, max_body_bytes)

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope.get("type") != "http"
            or not str(scope.get("path", "")).startswith("/api/")
            or str(scope.get("method", "GET")).upper() in {"GET", "HEAD"}
        ):
            await self.app(scope, receive, send)
            return

        headers = {
            key.lower(): value
            for key, value in scope.get("headers", [])
        }
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > self.max_body_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send, status=400, detail=b'{"detail":"Content-Length invalido."}')
                return

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if not response_started:
                await self._reject(send)
                return
            raise

    @staticmethod
    async def _reject(
        send,
        *,
        status: int = 413,
        detail: bytes = b'{"detail":"Corpo da requisicao excede o limite."}',
    ) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": detail,
                "more_body": False,
            }
        )


def is_cross_site_browser_request(request: Request) -> bool:
    return (
        request.url.path.startswith("/api/")
        and request.headers.get("sec-fetch-site", "").lower() == "cross-site"
    )
