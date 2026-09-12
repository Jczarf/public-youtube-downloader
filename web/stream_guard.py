from __future__ import annotations

import asyncio


class StreamingSendTimeoutMiddleware:
    """Abort long-lived responses when the downstream client stops reading.

    This protects scarce relay/FFmpeg slots from slow-read attacks. The timeout
    is applied only to streaming API response body chunks; normal HTML/API JSON
    responses are unaffected.
    """

    STREAM_PREFIXES = (
        "/api/v1/stream/",
        "/api/v1/merge/",
        "/api/v1/convert/",
    )

    def __init__(self, app, timeout_seconds: float = 30) -> None:
        self.app = app
        # Runtime configuration clamps this to >=5 seconds. A smaller lower
        # bound here keeps the middleware independently testable.
        self.timeout_seconds = max(0.05, min(float(timeout_seconds), 120.0))

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if not path.startswith(self.STREAM_PREFIXES):
            await self.app(scope, receive, send)
            return

        async def guarded_send(message):
            if (
                message.get("type") == "http.response.body"
                and message.get("body")
            ):
                await asyncio.wait_for(
                    send(message),
                    timeout=self.timeout_seconds,
                )
                return
            await send(message)

        await self.app(scope, receive, guarded_send)
