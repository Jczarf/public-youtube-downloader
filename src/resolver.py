from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote_plus, urlparse

import yt_dlp


class LinkType:
    DIRETO = "direto"
    PESQUISA_URL = "pesquisa_url"
    PESQUISA_TEXTO = "pesquisa_texto"
    PLAYLIST = "playlist"
    INVALIDO = "invalido"


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}


@dataclass(frozen=True)
class ResolvedInput:
    urls: list[str]
    label: str
    kind: str


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


def classificar_link(entrada: str) -> tuple[str, str]:
    value = entrada.strip()
    if not value:
        return LinkType.INVALIDO, ""

    normalized = "https://" + value if value.startswith("www.") else value
    if normalized.startswith(("http://", "https://")):
        if not is_youtube_url(normalized):
            return LinkType.INVALIDO, normalized
        parsed = urlparse(normalized)
        params = parse_qs(parsed.query)
        if parsed.path == "/playlist" or ("list" in params and "v" not in params):
            return LinkType.PLAYLIST, normalized
        if parsed.path == "/results":
            query = unquote_plus(params.get("search_query", [""])[0]).strip()
            return LinkType.PESQUISA_URL, query
        return LinkType.DIRETO, normalized

    return LinkType.PESQUISA_TEXTO, value


def _ydl_metadata_options() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "retries": 2,
    }


def buscar_primeiro_video(query: str) -> str | None:
    query = query.strip()
    if not query:
        return None
    try:
        with yt_dlp.YoutubeDL(_ydl_metadata_options()) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = list((result or {}).get("entries") or [])
        first = entries[0] if entries else result
        if not first:
            return None
        video_id = first.get("id")
        webpage_url = first.get("webpage_url") or first.get("url")
        if isinstance(webpage_url, str) and webpage_url.startswith("http"):
            return webpage_url
        return f"https://www.youtube.com/watch?v={video_id}" if video_id else None
    except Exception:
        return None


def resolver_playlist(url: str, max_items: int = 200) -> list[str]:
    try:
        with yt_dlp.YoutubeDL(_ydl_metadata_options()) as ydl:
            result = ydl.extract_info(url, download=False)
        urls: list[str] = []
        for entry in list((result or {}).get("entries") or [])[:max_items]:
            if not entry:
                continue
            video_id = entry.get("id")
            webpage_url = entry.get("webpage_url") or entry.get("url")
            if isinstance(webpage_url, str) and webpage_url.startswith("http"):
                urls.append(webpage_url)
            elif video_id:
                urls.append(f"https://www.youtube.com/watch?v={video_id}")
        return urls
    except Exception:
        return []


def resolver_entrada(entrada: str) -> ResolvedInput:
    kind, value = classificar_link(entrada)
    if kind == LinkType.INVALIDO:
        raise ValueError("Informe um link do YouTube ou um texto para pesquisa.")
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
