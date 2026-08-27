from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

import yt_dlp
from yt_dlp.utils import download_range_func


SUPPORTED_COOKIE_BROWSERS = {
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
}


@dataclass(frozen=True)
class DownloadSpec:
    url: str
    formato: str
    destino: Path
    qualidade_audio: str = "192"
    qualidade_video: str = "1080p"
    tempo_inicio: str | None = None
    tempo_fim: str | None = None


@dataclass(frozen=True)
class Progress:
    percent: float
    speed: float
    downloaded: int
    total: int
    status: str


def parse_time(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    parts = value.strip().split(":")
    if len(parts) > 3 or not all(p.isdigit() for p in parts):
        raise ValueError("Tempo inválido. Use SS, MM:SS ou HH:MM:SS.")
    nums = [int(p) for p in parts]
    if len(nums) == 3:
        h, m, s = nums
    elif len(nums) == 2:
        h, m, s = 0, nums[0], nums[1]
    else:
        h, m, s = 0, 0, nums[0]
    if m >= 60 or s >= 60:
        raise ValueError("Minutos e segundos devem ser menores que 60.")
    return float(h * 3600 + m * 60 + s)


def validate_clip(start: str | None, end: str | None) -> tuple[float | None, float | None]:
    start_s = parse_time(start)
    end_s = parse_time(end)
    if start_s is not None and end_s is not None and end_s <= start_s:
        raise ValueError("O tempo final precisa ser maior que o inicial.")
    return start_s, end_s


def retry_sleep(attempt: int) -> float:
    """Backoff curto e limitado para não martelar o servidor em retries."""

    try:
        number = max(1, int(attempt))
    except (TypeError, ValueError):
        number = 1
    return float(min(2 ** (number - 1), 20))


def configured_cookie_browser() -> str | None:
    browser = os.getenv("YT_DLP_COOKIES_FROM_BROWSER", "").strip().lower()
    if not browser:
        return None
    if browser not in SUPPORTED_COOKIE_BROWSERS:
        supported = ", ".join(sorted(SUPPORTED_COOKIE_BROWSERS))
        raise ValueError(
            "Navegador inválido em YT_DLP_COOKIES_FROM_BROWSER. "
            f"Use um destes valores: {supported}."
        )
    return browser


def friendly_download_error(exc: Exception) -> str:
    raw = str(exc).strip()
    lowered = raw.lower()
    auth_markers = (
        "sign in to confirm you're not a bot",
        "sign in to confirm you’re not a bot",
        "cookies-from-browser",
        "cookies for the authentication",
    )
    if any(marker in lowered for marker in auth_markers):
        return (
            "O YouTube pediu verificação da sessão. Feche o app e execute novamente "
            "com os cookies do navegador que já está autenticado, por exemplo: "
            "env YT_DLP_COOKIES_FROM_BROWSER=firefox ./run.sh. "
            "O aplicativo só lê cookies quando essa variável é definida explicitamente."
        )
    return raw or "Falha no download."


def build_options(spec: DownloadSpec, progress_hook: Callable[[dict], None]) -> dict:
    spec.destino.mkdir(parents=True, exist_ok=True)
    start_s, end_s = validate_clip(spec.tempo_inicio, spec.tempo_fim)

    opts: dict = {
        "paths": {"home": str(spec.destino)},
        "outtmpl": {"default": "%(title).180B [%(id)s].%(ext)s"},
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "continuedl": True,
        "overwrites": False,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "retry_sleep_functions": {
            "http": retry_sleep,
            "fragment": retry_sleep,
            "extractor": retry_sleep,
        },
        "concurrent_fragment_downloads": 1,
        "sleep_interval_requests": 1.0,
        "socket_timeout": 30,
        "progress_hooks": [progress_hook],
    }

    browser = configured_cookie_browser()
    if browser:
        opts["cookiesfrombrowser"] = (browser,)

    if spec.formato.lower() == "mp3":
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(spec.qualidade_audio),
            }],
        })
    else:
        limits = {"480p": 480, "720p": 720, "1080p": 1080}
        height = limits.get(spec.qualidade_video)
        if height:
            opts["format"] = (
                f"bestvideo[ext=mp4][height<={height}]+bestaudio[ext=m4a]/"
                f"best[ext=mp4][height<={height}]/best[height<={height}]"
            )
        else:
            opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        opts["merge_output_format"] = "mp4"

    if start_s is not None or end_s is not None:
        opts["download_ranges"] = download_range_func(
            None,
            [(start_s or 0.0, end_s or float("inf"))],
        )
        opts["force_keyframes_at_cuts"] = True

    return opts


class Downloader:
    def __init__(self, spec: DownloadSpec) -> None:
        self.spec = spec
        self._cancel = Event()

    def cancelar(self) -> None:
        self._cancel.set()

    def baixar(
        self,
        progress_callback: Callable[[Progress], None] | None = None,
        info_callback: Callable[[dict], None] | None = None,
    ) -> bool:
        title_sent = False

        def hook(data: dict) -> None:
            nonlocal title_sent
            if self._cancel.is_set():
                raise RuntimeError("Download cancelado pelo usuário")

            info = data.get("info_dict")
            if info_callback and not title_sent and isinstance(info, dict):
                info_callback(info)
                title_sent = True

            if not progress_callback:
                return
            downloaded = int(data.get("downloaded_bytes") or 0)
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
            percent = downloaded / total if total > 0 else 0.0
            progress_callback(Progress(
                percent=max(0.0, min(percent, 1.0)),
                speed=float(data.get("speed") or 0.0),
                downloaded=downloaded,
                total=total,
                status=str(data.get("status") or "downloading"),
            ))

        try:
            if self._cancel.is_set():
                return False
            with yt_dlp.YoutubeDL(build_options(self.spec, hook)) as ydl:
                info = ydl.extract_info(self.spec.url, download=True)
                if info_callback and info and not title_sent:
                    info_callback(info)
            return not self._cancel.is_set()
        except Exception as exc:
            if self._cancel.is_set() or "cancelado" in str(exc).lower():
                return False
            raise RuntimeError(friendly_download_error(exc)) from exc
