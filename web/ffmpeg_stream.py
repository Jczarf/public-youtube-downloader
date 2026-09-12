from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator

from web.runtime import ffmpeg_timeout_seconds
from web.service import (
    ALLOWED_UPSTREAM_HEADERS,
    MediaCandidate,
    is_allowed_media_url,
    server_merge_eligible,
    server_process_eligible,
)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _header_blob(candidate: MediaCandidate) -> str:
    lines: list[str] = []
    for raw_key, raw_value in candidate.http_headers.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        if key.lower() not in ALLOWED_UPSTREAM_HEADERS:
            continue
        if "\r" in key or "\n" in key or "\r" in value or "\n" in value:
            continue
        lines.append(f"{key}: {value}\r\n")
    return "".join(lines)


def _input_args(candidate: MediaCandidate) -> list[str]:
    if not is_allowed_media_url(candidate.url):
        raise ValueError("Destino remoto não permitido.")

    args: list[str] = [
        "-protocol_whitelist",
        "https,tls,tcp",
        "-rw_timeout",
        "15000000",
    ]
    headers = _header_blob(candidate)
    if headers:
        args.extend(["-headers", headers])
    args.extend(["-i", candidate.url])
    return args


def merge_mp4_command(
    video: MediaCandidate,
    audio: MediaCandidate,
) -> list[str]:
    if not server_merge_eligible(video, audio):
        raise ValueError(
            "O fallback aceita somente vídeo MP4 + áudio M4A/MP4 permitidos."
        )

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


def audio_mp3_command(
    audio: MediaCandidate,
    bitrate: int = 192,
) -> list[str]:
    if not audio.has_audio or not server_process_eligible(audio):
        raise ValueError("O formato selecionado não é permitido para áudio.")

    bitrate = max(64, min(int(bitrate), 320))

    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *_input_args(audio),
        "-vn",
        "-threads",
        "1",
        "-c:a",
        "libmp3lame",
        "-b:a",
        f"{bitrate}k",
        "-f",
        "mp3",
        "pipe:1",
    ]


async def _drain_stderr(
    stream: asyncio.StreamReader | None,
) -> bytes:
    if stream is None:
        return b""

    data = bytearray()
    while True:
        chunk = await stream.read(16 * 1024)
        if not chunk:
            break
        if len(data) < 32 * 1024:
            data.extend(chunk[: 32 * 1024 - len(data)])
    return bytes(data)


async def _read_process(
    process: asyncio.subprocess.Process,
    stderr_task: asyncio.Task[bytes],
) -> AsyncIterator[bytes]:
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
        # Do not return raw FFmpeg stderr to clients. It can contain source
        # URLs, tokens, or infrastructure details.
        raise RuntimeError(f"FFmpeg encerrou com código {return_code}.")


async def stream_command(command: list[str]) -> AsyncIterator[bytes]:
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg não está instalado no servidor.")

    timeout = ffmpeg_timeout_seconds()

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        },
    )
    stderr_task = asyncio.create_task(_drain_stderr(process.stderr))

    try:
        async def consume() -> AsyncIterator[bytes]:
            async for chunk in _read_process(process, stderr_task):
                yield chunk

        if timeout:
            deadline = asyncio.get_running_loop().time() + timeout
            iterator = consume().__aiter__()
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("FFmpeg excedeu o tempo máximo.")
                try:
                    chunk = await asyncio.wait_for(
                        iterator.__anext__(),
                        timeout=remaining,
                    )
                except StopAsyncIteration:
                    break
                yield chunk
        else:
            async for chunk in consume():
                yield chunk
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
