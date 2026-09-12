import asyncio

import pytest

from web.stream_guard import StreamingSendTimeoutMiddleware


def test_non_stream_path_is_not_wrapped():
    events = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        events.append(message)

    middleware = StreamingSendTimeoutMiddleware(app, timeout_seconds=0.05)
    asyncio.run(
        middleware(
            {"type": "http", "path": "/health"},
            receive,
            send,
        )
    )

    assert events[-1]["body"] == b"ok"


def test_stream_path_aborts_when_client_stops_reading():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"chunk", "more_body": True})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def stalled_send(message):
        if message.get("type") == "http.response.body" and message.get("body"):
            await asyncio.sleep(1)

    middleware = StreamingSendTimeoutMiddleware(app, timeout_seconds=0.05)

    async def run():
        with pytest.raises(TimeoutError):
            await middleware(
                {"type": "http", "path": "/api/v1/stream/a/b"},
                receive,
                stalled_send,
            )

    asyncio.run(run())
