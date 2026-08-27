from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from itertools import islice
from urllib.parse import parse_qs, unquote_plus, urlparse

import yt_dlp


class LinkType(str, Enum):
    DIRETO = "direto"
    PESQUISA_URL = "pesquisa_url"
    PESQUISA_TEXTO = "pesquisa_texto"
    PLAYLIST = "playlist"
    INVALIDO = "invalido"


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "music.youtube.com",
}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


@dataclass(frozen=True)
class ResolvedInput:
    urls: list[str]
    label: str
    kind: LinkType


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_youtube_url(value: str) -> bool:
    raw = value.strip()
    if raw.startswith("www."):
        raw = "https://" + raw
    return _host(raw) in YOUTUBE_HOSTS


def _canonical_video_url(parsed) -> str | None:
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    params = parse_qs(parsed.query)

    video_id = ""
    if host == "youtu.be":
        video_id = path.lstrip("/").split("/", 1)[0]
    elif path == "/watch":
        video_id = params.get("v", [""])[0]
    else:
        match = re.fullmatch(r"/(?:shorts|live|embed)/([A-Za-z0-9_-]{6,32})", path)
        if match:
            video_id = match.group(1)

    if not VIDEO_ID_RE.fullmatch(video_id or ""):
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def _canonical_playlist_url(parsed) -> str | None:
    if parsed.path.rstrip("/") != "/playlist":
        return None
    playlist_id = parse_qs(parsed.query).get("list", [""])[0]
    if not PLAYLIST_ID_RE.fullmatch(playlist_id or ""):
        return None
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def classificar_link(entrada: str) -> tuple[LinkType, str]:
    value = entrada.strip()
    if not value:
        return LinkType.INVALIDO, ""

    normalized = "https://" + value if value.startswith("www.") else value
    if normalized.startswith(("http://", "https://")):
        if not is_youtube_url(normalized):
            return LinkType.INVALIDO, normalized

        parsed = urlparse(normalized)
        if parsed.path.rstrip("/") == "/results":
            query = unquote_plus(parse_qs(parsed.query).get("search_query", [""])[0]).strip()
            return (LinkType.PESQUISA_URL, query) if query else (LinkType.INVALIDO, normalized)

        playlist = _canonical_playlist_url(parsed)
        if playlist:
            return LinkType.PLAYLIST, playlist

        direct = _canonical_video_url(parsed)
        if direct:
            return LinkType.DIRETO, direct

        return LinkType.INVALIDO, normalized

    return LinkType.PESQUISA_TEXTO, value


def _ydl_metadata_options() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "retries": 2,
        "socket_timeout": 15,
    }


def _canonicalize_extracted_url(value: str) -> str | None:
    kind, normalized = classificar_link(value)
    return normalized if kind == LinkType.DIRETO else None


def buscar_primeiro_video(query: str) -> str | None:
    query = query.strip()
    if not query:
        return None
    try:
        with yt_dlp.YoutubeDL(_ydl_metadata_options()) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = (result or {}).get("entries") or []
        first = next(iter(entries), result)
        if not first:
            return None
        video_id = str(first.get("id") or "")
        webpage_url = first.get("webpage_url") or first.get("url")
        if isinstance(webpage_url, str) and webpage_url.startswith("http"):
            canonical = _canonicalize_extracted_url(webpage_url)
            if canonical:
                return canonical
        if VIDEO_ID_RE.fullmatch(video_id):
            return f"https://www.youtube.com/watch?v={video_id}"
        return None
    except Exception:
        return None


def resolver_playlist(url: str, max_items: int = 200) -> list[str]:
    try:
        with yt_dlp.YoutubeDL(_ydl_metadata_options()) as ydl:
            result = ydl.extract_info(url, download=False)
        urls: list[str] = []
        entries = (result or {}).get("entries") or []
        for entry in islice(entries, max(1, min(int(max_items), 200))):
            if not entry:
                continue
            webpage_url = entry.get("webpage_url") or entry.get("url")
            if isinstance(webpage_url, str) and webpage_url.startswith("http"):
                canonical = _canonicalize_extracted_url(webpage_url)
                if canonical:
                    urls.append(canonical)
                    continue
            video_id = str(entry.get("id") or "")
            if VIDEO_ID_RE.fullmatch(video_id):
                urls.append(f"https://www.youtube.com/watch?v={video_id}")
        return urls
    except Exception:
        return []


def resolver_entrada(entrada: str) -> ResolvedInput:
    kind, value = classificar_link(entrada)
    if kind == LinkType.INVALIDO:
        raise ValueError("Informe um link de vídeo/playlist do YouTube ou um texto para pesquisa.")
    if kind == LinkType.DIRETO:
        return ResolvedInput([value], "Link direto", kind)
    if kind == LinkType.PLAYLIST:
        urls = resolver_playlist(value)
        if not urls:
            raise ValueError("Não foi possível ler a playlist.")
        return ResolvedInput(urls, f"Playlist • {len(urls)} itens", kind)

    url = buscar_primeiro_video(value)
    if not url:
        raise ValueError("Nenhum vídeo foi encontrado para essa pesquisa.")
    return ResolvedInput([url], f"Pesquisa: {value}", kind)
