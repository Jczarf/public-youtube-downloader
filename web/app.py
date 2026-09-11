from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from web.service import STORE, public_session, resolve_media


app = FastAPI(
    title="YouTube Downloader Web API",
    version="0.1.0",
    description="MVP da camada web: resolve formatos e retransmite mídia autorizada pela sessão.",
)


class ResolveRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2048)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/resolve")
async def resolve(payload: ResolveRequest) -> dict:
    try:
        session = await run_in_threadpool(resolve_media, payload.url)
        return public_session(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao resolver mídia: {exc}") from exc


@app.get("/api/v1/stream/{session_id}/{candidate_id}")
async def stream_media(session_id: str, candidate_id: str, request: Request) -> StreamingResponse:
    session = STORE.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão expirada ou inexistente.")

    candidate = session.candidates.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Formato inexistente.")

    upstream_headers = dict(candidate.http_headers)
    range_header = request.headers.get("range")
    if range_header:
        upstream_headers["Range"] = range_header

    client = httpx.AsyncClient(follow_redirects=True, timeout=None)
    upstream_request = client.build_request("GET", candidate.url, headers=upstream_headers)

    try:
        response = await client.send(upstream_request, stream=True)
    except Exception:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Falha ao abrir o stream de origem.")

    if response.status_code >= 400:
        status = response.status_code
        await response.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Origem respondeu HTTP {status}.")

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes(256 * 1024):
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    passthrough = {}
    for header in (
        "content-length",
        "content-range",
        "accept-ranges",
        "content-type",
        "etag",
        "last-modified",
    ):
        value = response.headers.get(header)
        if value:
            passthrough[header] = value

    content_type = passthrough.pop(
        "content-type",
        "application/octet-stream",
    )

    return StreamingResponse(
        body(),
        status_code=response.status_code,
        media_type=content_type,
        headers=passthrough,
    )
