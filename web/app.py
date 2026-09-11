from __future__ import annotations

from collections.abc import AsyncIterator
import logging
from pathlib import Path
import re
from typing import Literal
from urllib.parse import quote, urljoin

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from web.ffmpeg_stream import (
    audio_mp3_command,
    ffmpeg_available,
    merge_mp4_command,
    stream_command,
)
from web.runtime import (
    RELAY_SLOTS,
    RESOLVE_SLOTS,
    acquire_slot,
    max_media_bytes,
)
from web.security import (
    ACTIVE_CLIENTS,
    active_limit,
    add_security_headers,
    allowed_hosts,
    client_ip,
    env_bool,
    rate_limit_response,
)
from web.service import (
    STORE,
    build_download_plan,
    direct_eligible,
    is_allowed_media_url,
    public_session,
    resolve_media,
    server_merge_eligible,
)


LOGGER = logging.getLogger("mediaflow.web")
ENABLE_DOCS = env_bool("WEB_ENABLE_DOCS", False)
ENABLE_HSTS = env_bool("WEB_ENABLE_HSTS", False)
RANGE_RE = re.compile(r"^bytes=\d*-\d*$")
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_UPSTREAM_REDIRECTS = 2


app = FastAPI(
    title="YouTube Downloader Web API",
    version="0.4.0",
    description=(
        "MVP da camada web: resolve formatos, cria um plano de download, "
        "faz relay e oferece fallback FFmpeg em streaming."
    ),
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=allowed_hosts(),
    www_redirect=False,
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    limited = await rate_limit_response(request)
    if limited is not None:
        response = limited
    else:
        response = await call_next(request)

    add_security_headers(response, hsts=ENABLE_HSTS)

    if request.url.path.startswith("/api/") or request.url.path == "/health":
        response.headers["Cache-Control"] = "no-store"

    return response


class ResolveRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2048)


class PlanRequest(BaseModel):
    session_id: str = Field(min_length=16, max_length=128)
    media_type: Literal["video", "audio"] = "video"
    quality: int | None = Field(default=None, ge=144, le=4320)


def _download_headers(title: str, extension: str) -> dict[str, str]:
    bounded_title = str(title).strip()[:160] or "download"
    safe = (
        re.sub(r"[^A-Za-z0-9._-]+", "_", bounded_title)
        .strip("._")[:80]
        or "download"
    )
    fallback_name = f"{safe}.{extension}"
    encoded_name = quote(f"{bounded_title}.{extension}", safe="")
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
        raise HTTPException(
            status_code=404,
            detail="Sessão expirada ou inexistente.",
        )

    candidate = session.candidates.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Formato inexistente.")

    return session, candidate


def _safe_range_header(request: Request) -> str | None:
    value = request.headers.get("range")
    if not value:
        return None
    if len(value) > 64 or not RANGE_RE.fullmatch(value.strip()):
        raise HTTPException(status_code=416, detail="Range inválido.")
    return value.strip()


async def _open_upstream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
) -> httpx.Response:
    current = url

    for _ in range(MAX_UPSTREAM_REDIRECTS + 1):
        if not is_allowed_media_url(current):
            raise RuntimeError("Destino de mídia não permitido.")

        request = client.build_request("GET", current, headers=headers)
        response = await client.send(request, stream=True)

        if response.status_code not in REDIRECT_STATUSES:
            return response

        location = response.headers.get("location")
        await response.aclose()
        if not location:
            raise RuntimeError("Redirect de origem inválido.")

        next_url = urljoin(current, location)
        if not is_allowed_media_url(next_url):
            raise RuntimeError("Redirect de origem não permitido.")
        current = next_url

    raise RuntimeError("Muitos redirects na origem.")


def _response_exceeds_size_limit(response: httpx.Response) -> bool:
    limit = max_media_bytes()
    if not limit:
        return False

    content_range = response.headers.get("content-range", "")
    if "/" in content_range:
        total = content_range.rsplit("/", 1)[-1].strip()
        if total.isdigit() and int(total) > limit:
            return True

    content_length = response.headers.get("content-length", "").strip()
    if response.status_code != 206 and content_length.isdigit():
        return int(content_length) > limit

    return False


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.post("/api/v1/resolve")
async def resolve(payload: ResolveRequest, request: Request) -> dict:
    client = client_ip(request)
    if not await ACTIVE_CLIENTS.acquire(
        client,
        "resolve",
        active_limit("resolve", 1),
    ):
        raise HTTPException(
            status_code=429,
            detail="Já existe uma resolução ativa para este cliente.",
            headers={"Retry-After": "3"},
        )

    if not await acquire_slot(RESOLVE_SLOTS, timeout=0.1):
        await ACTIVE_CLIENTS.release(client, "resolve")
        raise HTTPException(
            status_code=503,
            detail="Servidor temporariamente ocupado.",
            headers={"Retry-After": "3"},
        )

    try:
        session = await run_in_threadpool(resolve_media, payload.url)
        return public_session(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.warning("media resolve failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="Não foi possível resolver esta mídia.",
        ) from exc
    finally:
        RESOLVE_SLOTS.release()
        await ACTIVE_CLIENTS.release(client, "resolve")


@app.post("/api/v1/plan")
async def plan(payload: PlanRequest) -> dict:
    session = STORE.get(payload.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Sessão expirada ou inexistente.",
        )

    try:
        return build_download_plan(
            session,
            media_type=payload.media_type,
            target_height=payload.quality,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=422,
            detail="Nenhuma combinação compatível foi encontrada.",
        ) from exc


@app.get("/api/v1/direct/{session_id}/{candidate_id}")
async def direct_media(
    session_id: str,
    candidate_id: str,
) -> RedirectResponse:
    _, candidate = _session_and_candidate(session_id, candidate_id)
    if not direct_eligible(candidate):
        raise HTTPException(
            status_code=409,
            detail="Este formato exige o modo compatível.",
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
async def merge_media(
    session_id: str,
    video_id: str,
    audio_id: str,
    request: Request,
) -> StreamingResponse:
    session = STORE.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Sessão expirada ou inexistente.",
        )

    video = session.candidates.get(video_id)
    audio = session.candidates.get(audio_id)
    if video is None or audio is None:
        raise HTTPException(
            status_code=404,
            detail="Formato de vídeo ou áudio inexistente.",
        )
    if not server_merge_eligible(video, audio):
        raise HTTPException(
            status_code=422,
            detail="Combinação não permitida para processamento no servidor.",
        )
    if not ffmpeg_available():
        raise HTTPException(
            status_code=503,
            detail="Processamento temporariamente indisponível.",
        )

    command = merge_mp4_command(video, audio)
    client = client_ip(request)
    if not await ACTIVE_CLIENTS.acquire(
        client,
        "process",
        active_limit("process", 1),
    ):
        raise HTTPException(
            status_code=429,
            detail="Já existe um processamento ativo para este cliente.",
            headers={"Retry-After": "10"},
        )

    async def merge_body() -> AsyncIterator[bytes]:
        try:
            async for chunk in stream_command(command):
                yield chunk
        finally:
            await ACTIVE_CLIENTS.release(client, "process")

    return StreamingResponse(
        merge_body(),
        media_type="video/mp4",
        headers=_download_headers(session.title, "mp4"),
    )


@app.get("/api/v1/convert/audio/{session_id}/{candidate_id}")
async def convert_audio(
    session_id: str,
    candidate_id: str,
    request: Request,
    bitrate: int = Query(default=192, ge=64, le=320),
) -> StreamingResponse:
    session, audio = _session_and_candidate(session_id, candidate_id)
    if not audio.has_audio:
        raise HTTPException(
            status_code=422,
            detail="O formato selecionado não possui áudio.",
        )
    if not ffmpeg_available():
        raise HTTPException(
            status_code=503,
            detail="Processamento temporariamente indisponível.",
        )

    command = audio_mp3_command(audio, bitrate=bitrate)
    client = client_ip(request)
    if not await ACTIVE_CLIENTS.acquire(
        client,
        "process",
        active_limit("process", 1),
    ):
        raise HTTPException(
            status_code=429,
            detail="Já existe um processamento ativo para este cliente.",
            headers={"Retry-After": "10"},
        )

    async def audio_body() -> AsyncIterator[bytes]:
        try:
            async for chunk in stream_command(command):
                yield chunk
        finally:
            await ACTIVE_CLIENTS.release(client, "process")

    return StreamingResponse(
        audio_body(),
        media_type="audio/mpeg",
        headers=_download_headers(session.title, "mp3"),
    )


@app.get("/api/v1/stream/{session_id}/{candidate_id}")
async def stream_media(
    session_id: str,
    candidate_id: str,
    request: Request,
) -> StreamingResponse:
    _, candidate = _session_and_candidate(session_id, candidate_id)

    if not is_allowed_media_url(candidate.url):
        raise HTTPException(
            status_code=422,
            detail="Destino de mídia inválido.",
        )

    range_header = _safe_range_header(request)
    client_identity = client_ip(request)

    if not await ACTIVE_CLIENTS.acquire(
        client_identity,
        "relay",
        active_limit("relay", 6),
    ):
        raise HTTPException(
            status_code=429,
            detail="Muitas conexões de mídia ativas para este cliente.",
            headers={"Retry-After": "3"},
        )

    if not await acquire_slot(RELAY_SLOTS, timeout=0.1):
        await ACTIVE_CLIENTS.release(client_identity, "relay")
        raise HTTPException(
            status_code=503,
            detail="Limite temporário de streams simultâneos atingido.",
            headers={"Retry-After": "3"},
        )

    upstream_headers = dict(candidate.http_headers)
    if range_header:
        upstream_headers["Range"] = range_header

    client: httpx.AsyncClient | None = None
    try:
        client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=10.0,
                read=None,
                write=10.0,
                pool=10.0,
            ),
        )
        response = await _open_upstream(
            client,
            candidate.url,
            upstream_headers,
        )
    except Exception:
        if client is not None:
            await client.aclose()
        RELAY_SLOTS.release()
        await ACTIVE_CLIENTS.release(client_identity, "relay")
        raise HTTPException(
            status_code=502,
            detail="Falha ao abrir o stream de origem.",
        )

    if response.status_code >= 400:
        await response.aclose()
        await client.aclose()
        RELAY_SLOTS.release()
        await ACTIVE_CLIENTS.release(client_identity, "relay")
        raise HTTPException(
            status_code=502,
            detail="A origem recusou o stream.",
        )

    if _response_exceeds_size_limit(response):
        await response.aclose()
        await client.aclose()
        RELAY_SLOTS.release()
        await ACTIVE_CLIENTS.release(client_identity, "relay")
        raise HTTPException(
            status_code=413,
            detail="A mídia excede o limite atual do serviço.",
        )

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes(256 * 1024):
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()
            RELAY_SLOTS.release()
            await ACTIVE_CLIENTS.release(client_identity, "relay")

    passthrough: dict[str, str] = {}
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

    passthrough["Cache-Control"] = "no-store, private"
    content_type = passthrough.pop(
        "content-type",
        "application/octet-stream",
    )
    if not (
        content_type.startswith("video/")
        or content_type.startswith("audio/")
        or content_type.startswith("application/octet-stream")
    ):
        content_type = "application/octet-stream"

    return StreamingResponse(
        body(),
        status_code=response.status_code,
        media_type=content_type,
        headers=passthrough,
    )


STATIC_DIR = Path(__file__).with_name("static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web-ui")
