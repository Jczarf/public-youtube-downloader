from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import yt_dlp

from src.resolver import LinkType, classificar_link


SESSION_TTL_SECONDS = 10 * 60
SENSITIVE_DIRECT_HEADERS = {"authorization", "cookie", "proxy-authorization"}


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
        # O MVP transmite somente formatos HTTP(S) diretamente resolvidos.
        # HLS/DASH continuam fora do relay até existir suporte dedicado.
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


def direct_eligible(candidate: MediaCandidate) -> bool:
    """Conservador: direct-first somente para HTTPS do CDN do YouTube.

    O navegador recebe um redirect efêmero. Se a mídia estiver vinculada ao IP
    que resolveu a URL ou exigir headers não reproduzíveis pelo navegador, o
    cliente deve usar o relay como fallback.
    """

    try:
        parsed = urlparse(candidate.url)
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return False
    if host != "googlevideo.com" and not host.endswith(".googlevideo.com"):
        return False

    header_names = {key.lower() for key in candidate.http_headers}
    return not bool(header_names & SENSITIVE_DIRECT_HEADERS)


def server_merge_eligible(video: MediaCandidate, audio: MediaCandidate) -> bool:
    return (
        video.has_video
        and not video.has_audio
        and video.ext.lower() == "mp4"
        and audio.has_audio
        and not audio.has_video
        and audio.ext.lower() in {"m4a", "mp4"}
    )


def _candidate_payload(session: ResolveSession, candidate: MediaCandidate) -> dict[str, Any]:
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
        payload["direct_url"] = f"/api/v1/direct/{session.id}/{candidate.id}"
    return payload


def public_session(session: ResolveSession) -> dict[str, Any]:
    formats = [_candidate_payload(session, candidate) for candidate in session.candidates.values()]

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

    at_or_below = [item for item in usable if (item.height or 0) <= target_height]
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
            audio = max(progressive, key=lambda item: item.abr or 0.0, default=None)
        if audio is None:
            raise RuntimeError("Nenhuma fonte de áudio compatível foi encontrada.")

        source = _candidate_payload(session, audio)
        return {
            "session_id": session.id,
            "media_type": "audio",
            "strategy": "direct-first" if source["direct_eligible"] else "relay",
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
                "mp3_url": f"/api/v1/convert/audio/{session.id}/{audio.id}",
            },
        }

    progressive = [item for item in candidates if item.progressive]
    video_only = [item for item in candidates if item.has_video and not item.has_audio]
    audio_only = [item for item in candidates if item.has_audio and not item.has_video]

    progressive_pick = _pick_video_candidate(progressive, target_height)
    adaptive_video = _pick_video_candidate(video_only, target_height)
    adaptive_audio = _pick_audio_candidate(
        audio_only,
        preferred_exts=("m4a", "mp4", "webm")
        if adaptive_video and adaptive_video.ext.lower() == "mp4"
        else ("webm", "m4a", "mp4"),
    )

    # Se o formato progressivo já atende a mesma resolução (ou melhor dentro
    # do alvo), ele é preferível: um único stream, sem merge.
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
            "strategy": "direct-first" if source["direct_eligible"] else "relay",
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
        return {
            "session_id": session.id,
            "media_type": "video",
            "quality": adaptive_video.height,
            "strategy": "browser-merge",
            "output": {
                "container": "mp4" if adaptive_video.ext.lower() == "mp4" else adaptive_video.ext,
                "merge_required": True,
            },
            "sources": {
                "video": video_source,
                "audio": audio_source,
            },
            "fallback": {
                "type": "server-ffmpeg",
                "available": server_merge_eligible(adaptive_video, adaptive_audio),
                "url": (
                    f"/api/v1/merge/{session.id}/{adaptive_video.id}/{adaptive_audio.id}"
                    if server_merge_eligible(adaptive_video, adaptive_audio)
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
            "strategy": "direct-first" if source["direct_eligible"] else "relay",
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
