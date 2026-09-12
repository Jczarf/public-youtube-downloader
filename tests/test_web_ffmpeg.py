from web.ffmpeg_stream import audio_mp3_command, merge_mp4_command
from web.service import MediaCandidate


def media(
    *,
    id: str,
    ext: str,
    video: bool,
    audio: bool,
    headers: dict[str, str] | None = None,
) -> MediaCandidate:
    return MediaCandidate(
        id=id,
        format_id=id,
        ext=ext,
        protocol="https",
        url=f"https://r1---sn.example.googlevideo.com/{id}",
        http_headers=headers or {"User-Agent": "test"},
        filesize=4 * 1024 * 1024,
        height=1080 if video else None,
        abr=128.0 if audio else None,
        vcodec="avc1" if video else "none",
        acodec="mp4a" if audio else "none",
    )


def test_merge_command_uses_pipe_without_shell():
    video = media(id="137", ext="mp4", video=True, audio=False)
    audio = media(id="140", ext="m4a", video=False, audio=True)

    command = merge_mp4_command(video, audio)

    assert command[0] == "ffmpeg"
    assert command[-1] == "pipe:1"
    assert "-c:v" in command
    assert "copy" in command
    assert video.url in command
    assert audio.url in command


def test_audio_command_clamps_bitrate():
    audio = media(id="140", ext="m4a", video=False, audio=True)

    command = audio_mp3_command(audio, bitrate=999)

    bitrate_index = command.index("-b:a")
    assert command[bitrate_index + 1] == "320k"
    assert command[-1] == "pipe:1"


def test_crlf_header_is_not_forwarded_to_ffmpeg():
    video = media(
        id="137",
        ext="mp4",
        video=True,
        audio=False,
        headers={"User-Agent": "ok", "X-Bad": "ok\r\nInjected: yes"},
    )
    audio = media(id="140", ext="m4a", video=False, audio=True)

    command = merge_mp4_command(video, audio)
    joined = "\n".join(command)

    assert "User-Agent: ok" in joined
    assert "Injected: yes" not in joined
