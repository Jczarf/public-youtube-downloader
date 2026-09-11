from __future__ import annotations

from collections.abc import AsyncIterator
import re
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from web.ffmpeg_stream import (
    audio_mp3_command,
    ffmpeg_available,
    merge_mp4_command,
    stream_command,
)
from web.service import (
    STORE,
    build_download_plan,
    direct_eligible,
    public_session,
    resolve_media,
    server_merge_eligible,
)


app = FastAPI(
    title="YouTube Downloader Web API",
    version="0.3.0",
    description=(
        "MVP da camada web: resolve formatos, cria um plano de download, "
        "faz relay e oferece fallback FFmpeg em streaming."
    ),
)


class ResolveRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2048)


class PlanRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=128)
    media_type: Literal["video", "audio"] = "video"
    quality: int | None = Field(default=None, ge=144, le=4320)


def _download_headers(title: str, extension: str) -> dict[str, str]:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._")[:80] or "download"
    fallback_name = f"{safe}.{extension}"
    encoded_name = quote(f"{title}.{extension}", safe="")
    return {
        "Cache-Control": "no-store, private",
        "Content-Disposition": (
            f'attachment; filename="{fallback_name}"; '
            f"filename*=UTF-8''{encoded_name}"
        ),
    }


def _session_and_candidate(session_id: str, candidate_id: str):
    session = STORE.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão expirada ou inexistente.")

    candidate = session.candidates.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Formato inexistente.")

    return session, candidate


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.post("/api/v1/resolve")
async def resolve(payload: ResolveRequest) -> dict:
    try:
        session = await run_in_threadpool(resolve_media, payload.url)
        return public_session(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao resolver mídia: {exc}") from exc


@app.post("/api/v1/plan")
async def plan(payload: PlanRequest) -> dict:
    session = STORE.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão expirada ou inexistente.")

    try:
        return build_download_plan(
            session,
            media_type=payload.media_type,
            target_height=payload.quality,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/direct/{session_id}/{candidate_id}")
async def direct_media(session_id: str, candidate_id: str) -> RedirectResponse:
    _, candidate = _session_and_candidate(session_id, candidate_id)
    if not direct_eligible(candidate):
        raise HTTPException(
            status_code=409,
            detail="Este formato não é elegível para tentativa direta; use o relay.",
        )

    return RedirectResponse(
        candidate.url,
        status_code=307,
        headers={
            "Cache-Control": "no-store, private",
            "Referrer-Policy": "no-referrer",
        },
    )


@app.get("/api/v1/merge/{session_id}/{video_id}/{audio_id}")
async def merge_media(session_id: str, video_id: str, audio_id: str) -> StreamingResponse:
    session = STORE.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão expirada ou inexistente.")

    video = session.candidates.get(video_id)
    audio = session.candidates.get(audio_id)
    if video is None or audio is None:
        raise HTTPException(status_code=404, detail="Formato de vídeo ou áudio inexistente.")
    if not server_merge_eligible(video, audio):
        raise HTTPException(
            status_code=422,
            detail="O fallback inicial suporta apenas vídeo MP4 + áudio M4A/MP4.",
        )
    if not ffmpeg_available():
        raise HTTPException(status_code=503, detail="FFmpeg não está disponível no servidor.")

    command = merge_mp4_command(video, audio)
    return StreamingResponse(
        stream_command(command),
        media_type="video/mp4",
        headers=_download_headers(session.title, "mp4"),
    )


@app.get("/api/v1/convert/audio/{session_id}/{candidate_id}")
async def convert_audio(
    session_id: str,
    candidate_id: str,
    bitrate: int = Query(default=192, ge=64, le=320),
) -> StreamingResponse:
    session, audio = _session_and_candidate(session_id, candidate_id)
    if not audio.has_audio:
        raise HTTPException(status_code=422, detail="O formato selecionado não possui áudio.")
    if not ffmpeg_available():
        raise HTTPException(status_code=503, detail="FFmpeg não está disponível no servidor.")

    command = audio_mp3_command(audio, bitrate=bitrate)
    return StreamingResponse(
        stream_command(command),
        media_type="audio/mpeg",
        headers=_download_headers(session.title, "mp3"),
    )


@app.get("/api/v1/stream/{session_id}/{candidate_id}")
async def stream_media(session_id: str, candidate_id: str, request: Request) -> StreamingResponse:
    _, candidate = _session_and_candidate(session_id, candidate_id)

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
