import asyncio
from types import SimpleNamespace

from web.security import (
    InMemoryRateLimiter,
    RateRule,
    allowed_hosts,
    client_ip,
    trusted_proxy_networks,
)


class FakeRequest:
    def __init__(self, peer: str, forwarded: str | None = None):
        self.client = SimpleNamespace(host=peer)
        self.headers = {}
        if forwarded is not None:
            self.headers["x-forwarded-for"] = forwarded


def test_rate_limiter_blocks_after_limit():
    async def run():
        limiter = InMemoryRateLimiter()
        rule = RateRule("resolve", 2, 60)

        assert await limiter.allow("203.0.113.10", rule) is True
        assert await limiter.allow("203.0.113.10", rule) is True
        assert await limiter.allow("203.0.113.10", rule) is False
        assert await limiter.allow("203.0.113.11", rule) is True

    asyncio.run(run())


def test_forwarded_for_is_ignored_without_trusted_proxy(monkeypatch):
    monkeypatch.delenv("WEB_TRUSTED_PROXY_CIDRS", raising=False)
    request = FakeRequest("198.51.100.10", "203.0.113.77")

    assert client_ip(request) == "198.51.100.10"


def test_forwarded_chain_only_used_from_trusted_proxy(monkeypatch):
    monkeypatch.setenv("WEB_TRUSTED_PROXY_CIDRS", "172.16.0.0/12")
    request = FakeRequest(
        "172.18.0.5",
        "203.0.113.77, 172.18.0.4",
    )

    assert client_ip(request) == "203.0.113.77"


def test_default_route_cannot_be_trusted_as_proxy(monkeypatch):
    monkeypatch.setenv("WEB_TRUSTED_PROXY_CIDRS", "0.0.0.0/0,::/0")

    assert trusted_proxy_networks() == ()

    request = FakeRequest("198.51.100.10", "203.0.113.77")
    assert client_ip(request) == "198.51.100.10"


def test_allowed_hosts_rejects_universal_wildcard(monkeypatch):
    monkeypatch.setenv("WEB_ALLOWED_HOSTS", "*")

    assert "*" not in allowed_hosts()
    assert "localhost" in allowed_hosts()


def test_allowed_hosts_keeps_explicit_domain(monkeypatch):
    monkeypatch.setenv("WEB_ALLOWED_HOSTS", "media.example.com,localhost")

    assert allowed_hosts() == ["media.example.com", "localhost"]
