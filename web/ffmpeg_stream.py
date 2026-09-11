from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator

from web.service import MediaCandidate


def _concurrency() -> int:
    try:
        return max(1, min(int(os.getenv("WEB_FFMPEG_CONCURRENCY", "2")), 8))
    except (TypeError, ValueError):
        return 2


FFMPEG_SEMAPHORE = asyncio.Semaphore(_concurrency())
DROP_UPSTREAM_HEADERS = {
    "accept-encoding",
    "connection",
    "content-length",
    "host",
    "range",
    "transfer-encoding",
}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def server_merge_eligible(video: MediaCandidate, audio: MediaCandidate) -> bool:
    return (
        video.has_video
        and not video.has_audio
        and video.ext.lower() == "mp4"
        and audio.has_audio
        and not audio.has_video
        and audio.ext.lower() in {"m4a", "mp4"}
    )


def _header_blob(candidate: MediaCandidate) -> str:
    lines: list[str] = []
    for raw_key, raw_value in candidate.http_headers.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        if not key or key.lower() in DROP_UPSTREAM_HEADERS:
            continue
        # Defesa em profundidade: headers vieram do extractor, mas não
        # permitimos que CR/LF criem novos argumentos/cabeçalhos.
        if "\r" in key or "\n" in key or "\r" in value or "\n" in value:
            continue
        lines.append(f"{key}: {value}\r\n")
    return "".join(lines)


def _input_args(candidate: MediaCandidate) -> list[str]:
    args: list[str] = []
    headers = _header_blob(candidate)
    if headers:
        args.extend(["-headers", headers])
    args.extend(["-i", candidate.url])
    return args


def merge_mp4_command(video: MediaCandidate, audio: MediaCandidate) -> list[str]:
    if not server_merge_eligible(video, audio):
        raise ValueError("O fallback inicial suporta somente vídeo MP4 + áudio M4A/MP4.")

    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *_input_args(video),
        *_input_args(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
        "-f",
        "mp4",
        "pipe:1",
    ]


def audio_mp3_command(audio: MediaCandidate, bitrate: int = 192) -> list[str]:
    if not audio.has_audio:
        raise ValueError("O formato selecionado não possui áudio.")
    bitrate = max(64, min(int(bitrate), 320))

    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *_input_args(audio),
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        f"{bitrate}k",
        "-f",
        "mp3",
        "pipe:1",
    ]


async def _drain_stderr(stream: asyncio.StreamReader | None) -> bytes:
    if stream is None:
        return b""
    # Mantém o pipe drenado para FFmpeg nunca bloquear por stderr cheio.
    data = bytearray()
    while True:
        chunk = await stream.read(16 * 1024)
        if not chunk:
            break
        if len(data) < 64 * 1024:
            data.extend(chunk[: 64 * 1024 - len(data)])
    return bytes(data)


async def stream_command(command: list[str]) -> AsyncIterator[bytes]:
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg não está instalado no servidor.")

    async with FFMPEG_SEMAPHORE:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_task = asyncio.create_task(_drain_stderr(process.stderr))

        try:
            if process.stdout is None:
                raise RuntimeError("FFmpeg não abriu o pipe de saída.")

            while True:
                chunk = await process.stdout.read(256 * 1024)
                if not chunk:
                    break
                yield chunk

            return_code = await process.wait()
            stderr = await stderr_task
            if return_code != 0:
                detail = stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(detail or f"FFmpeg encerrou com código {return_code}.")
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            if not stderr_task.done():
                stderr_task.cancel()
