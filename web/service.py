from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import yt_dlp

from src.resolver import LinkType, classificar_link
from web.runtime import (
    MAX_CANDIDATES_PER_SESSION,
    MAX_SESSIONS,
    max_duration_seconds,
)


SESSION_TTL_SECONDS = 10 * 60
SENSITIVE_DIRECT_HEADERS = {"authorization", "cookie", "proxy-authorization"}
ALLOWED_UPSTREAM_HEADERS = {
    "accept",
    "accept-language",
    "origin",
    "referer",
    "user-agent",
}
MAX_HEADER_VALUE_LENGTH = 1024


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
        stale = [
            key
            for key, item in self._items.items()
            if item.created_at < cutoff
        ]
        for key in stale:
            self._items.pop(key, None)

    def _enforce_capacity_locked(self) -> None:
        while len(self._items) >= MAX_SESSIONS:
            oldest = next(iter(self._items), None)
            if oldest is None:
                break
            self._items.pop(oldest, None)

    def put(self, session: ResolveSession) -> None:
        with self._lock:
            self._purge_locked()
            self._enforce_capacity_locked()
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
        "retries": 2,
        "extractor_retries": 2,
        "socket_timeout": 15,
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


def _trusted_host(host: str, root: str) -> bool:
    host = host.rstrip(".").lower()
    root = root.rstrip(".").lower()
    return host == root or host.endswith(f".{root}")


def is_allowed_media_url(value: str) -> bool:
    """Strict allowlist for server-side media fetches.

    Only HTTPS URLs on Google's video CDN, without embedded credentials and
    without non-standard ports, are accepted. This is deliberately narrower
    than trusting every URL returned by an extractor.
    """

    try:
        parsed = urlparse(value)
    except ValueError:
        return False

    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port not in {None, 443}:
        return False
    return _trusted_host(host, "googlevideo.com")


def _safe_thumbnail(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https":
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if not _trusted_host(host, "ytimg.com"):
        return None
    return value


def sanitize_upstream_headers(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}

    clean: dict[str, str] = {}
    for raw_key, raw_value in raw.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        lower = key.lower()

        if lower not in ALLOWED_UPSTREAM_HEADERS:
            continue
        if not value or len(value) > MAX_HEADER_VALUE_LENGTH:
            continue
        if "\r" in key or "\n" in key or "\r" in value or "\n" in value:
            continue

        clean[key] = value

    return clean


def _bounded_candidates(items: list[MediaCandidate]) -> list[MediaCandidate]:
    if len(items) <= MAX_CANDIDATES_PER_SESSION:
        return items

    progressive = sorted(
        (item for item in items if item.progressive),
        key=lambda item: (item.height or 0, item.filesize or 0),
        reverse=True,
    )
    video_only = sorted(
        (item for item in items if item.has_video and not item.has_audio),
        key=lambda item: (item.height or 0, item.filesize or 0),
        reverse=True,
    )
    audio_only = sorted(
        (item for item in items if item.has_audio and not item.has_video),
        key=lambda item: (item.abr or 0.0, item.filesize or 0),
        reverse=True,
    )

    progressive_quota = min(20, MAX_CANDIDATES_PER_SESSION)
    audio_quota = min(12, max(0, MAX_CANDIDATES_PER_SESSION - progressive_quota))
    video_quota = max(
        0,
        MAX_CANDIDATES_PER_SESSION - progressive_quota - audio_quota,
    )

    selected = (
        progressive[:progressive_quota]
        + video_only[:video_quota]
        + audio_only[:audio_quota]
    )

    if len(selected) < MAX_CANDIDATES_PER_SESSION:
        selected_ids = {id(item) for item in selected}
        for item in items:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            if len(selected) >= MAX_CANDIDATES_PER_SESSION:
                break

    return selected[:MAX_CANDIDATES_PER_SESSION]


def resolve_media(raw_url: str) -> ResolveSession:
    kind, normalized = classificar_link(raw_url)
    if kind != LinkType.DIRETO:
        raise ValueError(
            "A API web inicial aceita somente links diretos de vídeo do YouTube."
        )

    with yt_dlp.YoutubeDL(_extract_options()) as ydl:
        info = ydl.extract_info(normalized, download=False)

    if not isinstance(info, dict):
        raise RuntimeError("Metadados de origem inválidos.")

    duration = _safe_float(info.get("duration"))
    duration_limit = max_duration_seconds()
    if duration_limit and duration and duration > duration_limit:
        limit_minutes = duration_limit // 60
        raise ValueError(
            f"Este vídeo excede o limite atual de {limit_minutes} minutos."
        )

    raw_candidates: list[MediaCandidate] = []
    for fmt in info.get("formats") or []:
        if not isinstance(fmt, dict):
            continue

        media_url = fmt.get("url")
        if not isinstance(media_url, str) or not is_allowed_media_url(media_url):
            continue

        protocol = str(fmt.get("protocol") or "").lower()
        if protocol != "https":
            continue

        raw_candidates.append(
            MediaCandidate(
                id=secrets.token_urlsafe(12),
                format_id=str(fmt.get("format_id") or "")[:64],
                ext=str(fmt.get("ext") or "")[:16],
                protocol="https",
                url=media_url,
                http_headers=sanitize_upstream_headers(fmt.get("http_headers")),
                filesize=_safe_int(fmt.get("filesize") or fmt.get("filesize_approx")),
                height=_safe_int(fmt.get("height")),
                abr=_safe_float(fmt.get("abr")),
                vcodec=str(fmt.get("vcodec") or "none")[:128],
                acodec=str(fmt.get("acodec") or "none")[:128],
            )
        )

    bounded = _bounded_candidates(raw_candidates)
    candidates = {candidate.id: candidate for candidate in bounded}

    if not candidates:
        raise RuntimeError("Nenhum formato HTTPS compatível foi encontrado.")

    title = str(info.get("title") or "Sem título")[:512]
    session = ResolveSession(
        id=secrets.token_urlsafe(24),
        created_at=time.time(),
        title=title,
        webpage_url=normalized,
        thumbnail=_safe_thumbnail(info.get("thumbnail")),
        duration=duration,
        candidates=candidates,
    )
    STORE.put(session)
    return session


def direct_eligible(candidate: MediaCandidate) -> bool:
    if not is_allowed_media_url(candidate.url):
        return False

    header_names = {key.lower() for key in candidate.http_headers}
    return not bool(header_names & SENSITIVE_DIRECT_HEADERS)


def server_merge_eligible(video: MediaCandidate, audio: MediaCandidate) -> bool:
    return (
        is_allowed_media_url(video.url)
        and is_allowed_media_url(audio.url)
        and video.has_video
        and not video.has_audio
        and video.ext.lower() == "mp4"
        and audio.has_audio
        and not audio.has_video
        and audio.ext.lower() in {"m4a", "mp4"}
    )


def _candidate_payload(
    session: ResolveSession,
    candidate: MediaCandidate,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": candidate.id,
        "format_id": candidate.format_id,
        "ext": candidate.ext,
        "filesize": candidate.filesize,
        "height": candidate.height,
        "abr": candidate.abr,
        "has_video": candidate.has_video,
        "has_audio": candidate.has_audio,
        "progressive": candidate.progressive,
        "relay_url": f"/api/v1/stream/{session.id}/{candidate.id}",
        "direct_eligible": direct_eligible(candidate),
    }
    if payload["direct_eligible"]:
        payload["direct_url"] = (
            f"/api/v1/direct/{session.id}/{candidate.id}"
        )
    return payload


def public_session(session: ResolveSession) -> dict[str, Any]:
    formats = [
        _candidate_payload(session, candidate)
        for candidate in session.candidates.values()
    ]

    progressive = [item for item in formats if item["progressive"]]
    video_only = [
        item
        for item in formats
        if item["has_video"] and not item["has_audio"]
    ]
    audio_only = [
        item
        for item in formats
        if item["has_audio"] and not item["has_video"]
    ]

    return {
        "session_id": session.id,
        "expires_in": SESSION_TTL_SECONDS,
        "title": session.title,
        "webpage_url": session.webpage_url,
        "thumbnail": session.thumbnail,
        "duration": session.duration,
        "formats": formats,
        "strategy": {
            "progressive_ready": bool(progressive),
            "browser_merge_candidate": bool(video_only and audio_only),
            "server_ffmpeg_fallback_required": bool(video_only and audio_only),
            "progressive_count": len(progressive),
            "video_only_count": len(video_only),
            "audio_only_count": len(audio_only),
        },
    }


def _container_score(candidate: MediaCandidate, preferred: tuple[str, ...]) -> int:
    try:
        return len(preferred) - preferred.index(candidate.ext.lower())
    except ValueError:
        return 0


def _pick_video_candidate(
    candidates: list[MediaCandidate],
    target_height: int | None,
    preferred_exts: tuple[str, ...] = ("mp4", "webm"),
) -> MediaCandidate | None:
    usable = [item for item in candidates if item.has_video and item.height]
    if not usable:
        return None

    if target_height is None:
        return max(
            usable,
            key=lambda item: (
                item.height or 0,
                _container_score(item, preferred_exts),
                item.filesize or 0,
            ),
        )

    at_or_below = [
        item
        for item in usable
        if (item.height or 0) <= target_height
    ]
    if at_or_below:
        return max(
            at_or_below,
            key=lambda item: (
                item.height or 0,
                _container_score(item, preferred_exts),
                item.filesize or 0,
            ),
        )

    return min(
        usable,
        key=lambda item: (
            item.height or 0,
            -_container_score(item, preferred_exts),
        ),
    )


def _pick_audio_candidate(
    candidates: list[MediaCandidate],
    preferred_exts: tuple[str, ...] = ("m4a", "mp4", "webm"),
) -> MediaCandidate | None:
    usable = [item for item in candidates if item.has_audio and not item.has_video]
    if not usable:
        return None
    return max(
        usable,
        key=lambda item: (
            _container_score(item, preferred_exts),
            item.abr or 0.0,
            item.filesize or 0,
        ),
    )


def build_download_plan(
    session: ResolveSession,
    media_type: str = "video",
    target_height: int | None = None,
) -> dict[str, Any]:
    if media_type not in {"video", "audio"}:
        raise ValueError("media_type deve ser 'video' ou 'audio'.")
    if target_height is not None and not 144 <= target_height <= 4320:
        raise ValueError("quality deve ficar entre 144 e 4320.")

    candidates = list(session.candidates.values())

    if media_type == "audio":
        audio = _pick_audio_candidate(candidates)
        if audio is None:
            progressive = [item for item in candidates if item.progressive]
            audio = max(
                progressive,
                key=lambda item: item.abr or 0.0,
                default=None,
            )
        if audio is None:
            raise RuntimeError("Nenhuma fonte de áudio compatível foi encontrada.")

        source = _candidate_payload(session, audio)
        return {
            "session_id": session.id,
            "media_type": "audio",
            "strategy": (
                "direct-first" if source["direct_eligible"] else "relay"
            ),
            "output": {
                "container": audio.ext,
                "conversion_required_for_mp3": audio.ext.lower() != "mp3",
            },
            "source": source,
            "fallback": {
                "type": "relay",
                "url": source["relay_url"],
            },
            "conversion": {
                "mp3_available": True,
                "mp3_url": (
                    f"/api/v1/convert/audio/{session.id}/{audio.id}"
                ),
            },
        }

    progressive = [item for item in candidates if item.progressive]
    video_only = [
        item
        for item in candidates
        if item.has_video and not item.has_audio
    ]
    audio_only = [
        item
        for item in candidates
        if item.has_audio and not item.has_video
    ]

    progressive_pick = _pick_video_candidate(progressive, target_height)
    adaptive_video = _pick_video_candidate(video_only, target_height)
    adaptive_audio = _pick_audio_candidate(
        audio_only,
        preferred_exts=("m4a", "mp4", "webm")
        if adaptive_video and adaptive_video.ext.lower() == "mp4"
        else ("webm", "m4a", "mp4"),
    )

    progressive_height = progressive_pick.height if progressive_pick else 0
    adaptive_height = adaptive_video.height if adaptive_video else 0

    if progressive_pick and (
        not adaptive_video
        or not adaptive_audio
        or progressive_height >= adaptive_height
    ):
        source = _candidate_payload(session, progressive_pick)
        return {
            "session_id": session.id,
            "media_type": "video",
            "quality": progressive_pick.height,
            "strategy": (
                "direct-first" if source["direct_eligible"] else "relay"
            ),
            "output": {
                "container": progressive_pick.ext,
                "merge_required": False,
            },
            "source": source,
            "fallback": {
                "type": "relay",
                "url": source["relay_url"],
            },
        }

    if adaptive_video and adaptive_audio:
        video_source = _candidate_payload(session, adaptive_video)
        audio_source = _candidate_payload(session, adaptive_audio)
        fallback_available = server_merge_eligible(
            adaptive_video,
            adaptive_audio,
        )
        return {
            "session_id": session.id,
            "media_type": "video",
            "quality": adaptive_video.height,
            "strategy": "browser-merge",
            "output": {
                "container": (
                    "mp4"
                    if adaptive_video.ext.lower() == "mp4"
                    else adaptive_video.ext
                ),
                "merge_required": True,
            },
            "sources": {
                "video": video_source,
                "audio": audio_source,
            },
            "fallback": {
                "type": "server-ffmpeg",
                "available": fallback_available,
                "url": (
                    f"/api/v1/merge/{session.id}/"
                    f"{adaptive_video.id}/{adaptive_audio.id}"
                    if fallback_available
                    else None
                ),
            },
        }

    if progressive_pick:
        source = _candidate_payload(session, progressive_pick)
        return {
            "session_id": session.id,
            "media_type": "video",
            "quality": progressive_pick.height,
            "strategy": (
                "direct-first" if source["direct_eligible"] else "relay"
            ),
            "output": {
                "container": progressive_pick.ext,
                "merge_required": False,
            },
            "source": source,
            "fallback": {
                "type": "relay",
                "url": source["relay_url"],
            },
        }

    raise RuntimeError("Nenhuma combinação de vídeo compatível foi encontrada.")
