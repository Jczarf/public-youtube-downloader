from types import SimpleNamespace

import pytest

from web.security import InMemoryRateLimiter, RateRule, client_ip


class FakeRequest:
    def __init__(self, peer: str, forwarded: str | None = None):
        self.client = SimpleNamespace(host=peer)
        self.headers = {}
        if forwarded is not None:
            self.headers["x-forwarded-for"] = forwarded


@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_limit():
    limiter = InMemoryRateLimiter()
    rule = RateRule("resolve", 2, 60)

    assert await limiter.allow("203.0.113.10", rule) is True
    assert await limiter.allow("203.0.113.10", rule) is True
    assert await limiter.allow("203.0.113.10", rule) is False
    assert await limiter.allow("203.0.113.11", rule) is True


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
