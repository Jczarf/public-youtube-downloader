from web.service import (
    MediaCandidate,
    ResolveSession,
    build_download_plan,
    direct_eligible,
    public_session,
    is_allowed_media_url,
    sanitize_upstream_headers,
)


def candidate(
    *,
    id: str,
    ext: str,
    height: int | None,
    abr: float | None,
    video: bool,
    audio: bool,
    url: str | None = None,
) -> MediaCandidate:
    return MediaCandidate(
        id=id,
        format_id=id,
        ext=ext,
        protocol="https",
        url=url or f"https://r1---sn.example.googlevideo.com/{id}",
        http_headers={"User-Agent": "test"},
        filesize=123,
        height=height,
        abr=abr,
        vcodec="avc1" if video else "none",
        acodec="mp4a" if audio else "none",
    )


def session_with(*items: MediaCandidate) -> ResolveSession:
    return ResolveSession(
        id="session1",
        created_at=0.0,
        title="Vídeo",
        webpage_url="https://www.youtube.com/watch?v=abc12345",
        thumbnail=None,
        duration=10.0,
        candidates={item.id: item for item in items},
    )


def test_public_session_does_not_expose_origin_url():
    item = candidate(
        id="fmt1",
        ext="mp4",
        height=360,
        abr=96.0,
        video=True,
        audio=True,
        url="https://example.googlevideo.com/private-token",
    )

    payload = public_session(session_with(item))

    assert payload["formats"][0]["relay_url"] == "/api/v1/stream/session1/fmt1"
    assert payload["formats"][0]["direct_url"] == "/api/v1/direct/session1/fmt1"
    assert "private-token" not in repr(payload)
    assert payload["strategy"]["progressive_ready"] is True
    assert payload["strategy"]["browser_merge_candidate"] is False


def test_strategy_detects_adaptive_pair():
    video = candidate(
        id="137",
        ext="mp4",
        height=1080,
        abr=None,
        video=True,
        audio=False,
    )
    audio = candidate(
        id="140",
        ext="m4a",
        height=None,
        abr=128.0,
        video=False,
        audio=True,
    )

    strategy = public_session(session_with(video, audio))["strategy"]

    assert strategy["progressive_ready"] is False
    assert strategy["browser_merge_candidate"] is True
    assert strategy["server_ffmpeg_fallback_required"] is True


def test_direct_first_only_accepts_googlevideo_without_sensitive_headers():
    ok = candidate(
        id="18",
        ext="mp4",
        height=360,
        abr=96.0,
        video=True,
        audio=True,
    )
    wrong_host = candidate(
        id="x",
        ext="mp4",
        height=360,
        abr=96.0,
        video=True,
        audio=True,
        url="https://cdn.example.com/video",
    )
    sensitive = candidate(
        id="y",
        ext="mp4",
        height=360,
        abr=96.0,
        video=True,
        audio=True,
    )
    sensitive.http_headers["Cookie"] = "secret"

    assert direct_eligible(ok) is True
    assert direct_eligible(wrong_host) is False
    assert direct_eligible(sensitive) is False


def test_plan_prefers_progressive_when_it_matches_adaptive_quality():
    progressive = candidate(
        id="22",
        ext="mp4",
        height=720,
        abr=128.0,
        video=True,
        audio=True,
    )
    video = candidate(
        id="136",
        ext="mp4",
        height=720,
        abr=None,
        video=True,
        audio=False,
    )
    audio = candidate(
        id="140",
        ext="m4a",
        height=None,
        abr=128.0,
        video=False,
        audio=True,
    )

    plan = build_download_plan(
        session_with(progressive, video, audio),
        media_type="video",
        target_height=720,
    )

    assert plan["strategy"] == "direct-first"
    assert plan["source"]["id"] == "22"
    assert plan["output"]["merge_required"] is False


def test_plan_uses_browser_merge_when_adaptive_has_better_quality():
    progressive = candidate(
        id="22",
        ext="mp4",
        height=720,
        abr=128.0,
        video=True,
        audio=True,
    )
    video = candidate(
        id="137",
        ext="mp4",
        height=1080,
        abr=None,
        video=True,
        audio=False,
    )
    audio = candidate(
        id="140",
        ext="m4a",
        height=None,
        abr=128.0,
        video=False,
        audio=True,
    )

    plan = build_download_plan(
        session_with(progressive, video, audio),
        media_type="video",
        target_height=1080,
    )

    assert plan["strategy"] == "browser-merge"
    assert plan["quality"] == 1080
    assert plan["sources"]["video"]["id"] == "137"
    assert plan["sources"]["audio"]["id"] == "140"
    assert plan["fallback"]["available"] is True
    assert plan["fallback"]["url"] == "/api/v1/merge/session1/137/140"


def test_audio_plan_prefers_m4a_and_marks_mp3_conversion():
    m4a = candidate(
        id="140",
        ext="m4a",
        height=None,
        abr=128.0,
        video=False,
        audio=True,
    )
    webm = candidate(
        id="251",
        ext="webm",
        height=None,
        abr=160.0,
        video=False,
        audio=True,
    )

    plan = build_download_plan(session_with(m4a, webm), media_type="audio")

    assert plan["source"]["id"] == "140"
    assert plan["output"]["container"] == "m4a"
    assert plan["output"]["conversion_required_for_mp3"] is True
    assert plan["conversion"]["mp3_available"] is True
    assert plan["conversion"]["mp3_url"] == "/api/v1/convert/audio/session1/140"


def test_media_url_allowlist_blocks_ssrf_shapes():
    assert is_allowed_media_url(
        "https://r1---sn.example.googlevideo.com/videoplayback?id=1"
    ) is True
    assert is_allowed_media_url("http://r1.googlevideo.com/video") is False
    assert is_allowed_media_url("https://googlevideo.com.evil.test/video") is False
    assert is_allowed_media_url("https://user:pass@googlevideo.com/video") is False
    assert is_allowed_media_url("https://googlevideo.com:8443/video") is False
    assert is_allowed_media_url("https://127.0.0.1/video") is False
    assert is_allowed_media_url("https://169.254.169.254/latest/meta-data/") is False


def test_upstream_headers_use_positive_allowlist():
    clean = sanitize_upstream_headers(
        {
            "User-Agent": "safe-agent",
            "Accept-Language": "pt-BR",
            "Cookie": "secret=1",
            "Authorization": "Bearer secret",
            "Host": "internal.local",
            "X-Forwarded-For": "127.0.0.1",
            "X-Bad": "ok\r\nInjected: yes",
        }
    )

    assert clean == {
        "User-Agent": "safe-agent",
        "Accept-Language": "pt-BR",
    }
