from web.service import MediaCandidate, ResolveSession, public_session


def test_public_session_does_not_expose_origin_url():
    candidate = MediaCandidate(
        id="fmt1",
        format_id="18",
        ext="mp4",
        protocol="https",
        url="https://example.googlevideo.com/private-token",
        http_headers={"User-Agent": "test"},
        filesize=123,
        height=360,
        abr=96.0,
        vcodec="avc1",
        acodec="mp4a",
    )
    session = ResolveSession(
        id="session1",
        created_at=0.0,
        title="Vídeo",
        webpage_url="https://www.youtube.com/watch?v=abc12345",
        thumbnail=None,
        duration=10.0,
        candidates={"fmt1": candidate},
    )

    payload = public_session(session)

    assert payload["formats"][0]["stream_url"] == "/api/v1/stream/session1/fmt1"
    assert "googlevideo" not in repr(payload)
    assert payload["strategy"]["direct_or_proxy_ready"] is True
    assert payload["strategy"]["browser_merge_ready"] is False


def test_strategy_detects_adaptive_pair():
    video = MediaCandidate(
        id="video",
        format_id="137",
        ext="mp4",
        protocol="https",
        url="https://video.invalid",
        http_headers={},
        filesize=None,
        height=1080,
        abr=None,
        vcodec="avc1",
        acodec="none",
    )
    audio = MediaCandidate(
        id="audio",
        format_id="140",
        ext="m4a",
        protocol="https",
        url="https://audio.invalid",
        http_headers={},
        filesize=None,
        height=None,
        abr=128.0,
        vcodec="none",
        acodec="mp4a",
    )
    session = ResolveSession(
        id="session2",
        created_at=0.0,
        title="Vídeo",
        webpage_url="https://www.youtube.com/watch?v=abc12345",
        thumbnail=None,
        duration=None,
        candidates={"video": video, "audio": audio},
    )

    strategy = public_session(session)["strategy"]

    assert strategy["direct_or_proxy_ready"] is False
    assert strategy["browser_merge_ready"] is True
    assert strategy["server_ffmpeg_fallback"] is True
