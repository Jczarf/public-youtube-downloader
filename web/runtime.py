from __future__ import annotations

import asyncio
import os


def env_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
    allow_zero: bool = False,
) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default

    if allow_zero and value == 0:
        return 0

    return max(minimum, min(value, maximum))


def max_duration_seconds() -> int:
    """Maximum accepted media duration. Zero disables the duration cap."""

    return env_int(
        "WEB_MAX_DURATION_SECONDS",
        7200,
        minimum=60,
        maximum=24 * 60 * 60,
        allow_zero=True,
    )


RESOLVE_CONCURRENCY = env_int(
    "WEB_RESOLVE_CONCURRENCY",
    4,
    minimum=1,
    maximum=16,
)
RELAY_CONCURRENCY = env_int(
    "WEB_RELAY_CONCURRENCY",
    8,
    minimum=1,
    maximum=64,
)

RESOLVE_SLOTS = asyncio.Semaphore(RESOLVE_CONCURRENCY)
RELAY_SLOTS = asyncio.Semaphore(RELAY_CONCURRENCY)


async def acquire_slot(
    semaphore: asyncio.Semaphore,
    *,
    timeout: float = 0.05,
) -> bool:
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
        return True
    except TimeoutError:
        return False
