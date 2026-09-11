from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import yt_dlp

from src.resolver import LinkType, classificar_link


SESSION_TTL_SECONDS = 10 * 60


@dataclass
class MediaCandidate:
    id: str
    format_id: str
    ext: str
    protocol: str
    url: str
    http_headers: dict[str, str]
    filesize: int | None
    height: int | None
    abr: float | None
    vcodec: str
    acodec: str

    @property
    def has_video(self) -> bool:
        return self.vcodec not in {"none", ""}

    @property
    def has_audio(self) -> bool:
        return self.acodec not in {"none", ""}

    @property
    def progressive(self) -> bool:
        return self.has_video and self.has_audio


@dataclass
class ResolveSession:
    id: str
    created_at: float
    title: str
    webpage_url: str
    thumbnail: str | None
    duration: float | None
    candidates: dict[str, MediaCandidate] = field(default_factory=dict)


class ResolveStore:
    def __init__(self) -> None:
        self._items: dict[str, ResolveSession] = {}
        self._lock = Lock()

    def _purge_locked(self) -> None:
        cutoff = time.time() - SESSION_TTL_SECONDS
        stale = [key for key, item in self._items.items() if item.created_at < cutoff]
        for key in stale:
            self._items.pop(key, None)

    def put(self, session: ResolveSession) -> None:
        with self._lock:
            self._purge_locked()
            self._items[session.id] = session

    def get(self, session_id: str) -> ResolveSession | None:
        with self._lock:
            self._purge_locked()
            return self._items.get(session_id)


STORE = ResolveStore()


def _extract_options() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "retries": 3,
        "extractor_retries": 2,
        "socket_timeout": 20,
    }


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def resolve_media(raw_url: str) -> ResolveSession:
    kind, normalized = classificar_link(raw_url)
    if kind != LinkType.DIRETO:
        raise ValueError("A API web inicial aceita somente links diretos de vídeo do YouTube.")

    with yt_dlp.YoutubeDL(_extract_options()) as ydl:
        info = ydl.extract_info(normalized, download=False)

    if not isinstance(info, dict):
        raise RuntimeError("O YouTube não retornou metadados válidos.")

    candidates: dict[str, MediaCandidate] = {}
    for fmt in info.get("formats") or []:
        if not isinstance(fmt, dict):
            continue

        media_url = fmt.get("url")
        if not isinstance(media_url, str) or not media_url.startswith("https://"):
            continue

        protocol = str(fmt.get("protocol") or "")
        # O primeiro MVP transmite apenas formatos HTTP(S) que podem ser
        # retransmitidos sem implementar um cliente HLS/DASH próprio.
        if protocol not in {"https", "http"}:
            continue

        candidate_id = secrets.token_urlsafe(8)
        headers = {
            str(key): str(value)
            for key, value in (fmt.get("http_headers") or {}).items()
            if value is not None
        }
        candidates[candidate_id] = MediaCandidate(
            id=candidate_id,
            format_id=str(fmt.get("format_id") or ""),
            ext=str(fmt.get("ext") or ""),
            protocol=protocol,
            url=media_url,
            http_headers=headers,
            filesize=_safe_int(fmt.get("filesize") or fmt.get("filesize_approx")),
            height=_safe_int(fmt.get("height")),
            abr=_safe_float(fmt.get("abr")),
            vcodec=str(fmt.get("vcodec") or "none"),
            acodec=str(fmt.get("acodec") or "none"),
        )

    if not candidates:
        raise RuntimeError("Nenhum formato HTTP compatível foi encontrado.")

    session = ResolveSession(
        id=secrets.token_urlsafe(18),
        created_at=time.time(),
        title=str(info.get("title") or "Sem título"),
        webpage_url=str(info.get("webpage_url") or normalized),
        thumbnail=info.get("thumbnail") if isinstance(info.get("thumbnail"), str) else None,
        duration=_safe_float(info.get("duration")),
        candidates=candidates,
    )
    STORE.put(session)
    return session


def public_session(session: ResolveSession) -> dict[str, Any]:
    formats = []
    for candidate in session.candidates.values():
        formats.append({
            "id": candidate.id,
            "format_id": candidate.format_id,
            "ext": candidate.ext,
            "filesize": candidate.filesize,
            "height": candidate.height,
            "abr": candidate.abr,
            "has_video": candidate.has_video,
            "has_audio": candidate.has_audio,
            "progressive": candidate.progressive,
            "stream_url": f"/api/v1/stream/{session.id}/{candidate.id}",
        })

    progressive = [item for item in formats if item["progressive"]]
    video_only = [item for item in formats if item["has_video"] and not item["has_audio"]]
    audio_only = [item for item in formats if item["has_audio"] and not item["has_video"]]

    return {
        "session_id": session.id,
        "expires_in": SESSION_TTL_SECONDS,
        "title": session.title,
        "webpage_url": session.webpage_url,
        "thumbnail": session.thumbnail,
        "duration": session.duration,
        "formats": formats,
        "strategy": {
            "direct_or_proxy_ready": bool(progressive),
            "browser_merge_ready": bool(video_only and audio_only),
            "server_ffmpeg_fallback": bool(video_only and audio_only),
            "progressive_count": len(progressive),
            "video_only_count": len(video_only),
            "audio_only_count": len(audio_only),
        },
    }
