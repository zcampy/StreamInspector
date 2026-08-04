from streaminspector.media_utils import (
    build_ffmpeg_command,
    is_m3u8_response,
    is_video_url,
    parse_m3u8,
)


def test_m3u8_detected_by_signature() -> None:
    assert is_m3u8_response("application/json", b"#EXTM3U\n#EXTINF:3,\na.json\n")


def test_video_extension_uses_url_path_not_query() -> None:
    assert is_video_url("https://cdn.example/index.m3u8?token=abc")
    assert not is_video_url("https://example.com/api?next=file.m3u8")


def test_media_playlist_preserves_segments_and_live_state() -> None:
    playlist = parse_m3u8(
        "#EXTM3U\n#EXT-X-TARGETDURATION:3\n#EXTINF:3,\na.json\n",
        "https://cdn.example/live/index.m3u8",
    )
    assert playlist.is_master is False
    assert playlist.is_live is True
    assert playlist.segment_count == 1
    assert playlist.segments[0].url == "https://cdn.example/live/a.json"


def test_master_playlist_separates_variants_from_segments() -> None:
    playlist = parse_m3u8(
        '#EXTM3U\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720,'
        'CODECS="avc1.4d401f,mp4a.40.2",FRAME-RATE=50\n'
        '720p/index.m3u8\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=2560000,RESOLUTION=1920x1080\n'
        '1080p/index.m3u8\n',
        "https://cdn.example/master.m3u8",
    )
    assert playlist.is_master is True
    assert playlist.is_live is None
    assert playlist.segments == ()
    assert playlist.segment_count == 0
    assert len(playlist.variants) == 2
    assert playlist.variants[0].url == "https://cdn.example/720p/index.m3u8"
    assert playlist.variants[0].bandwidth == 1280000
    assert playlist.variants[0].resolution == "1280x720"
    assert playlist.variants[0].codecs == "avc1.4d401f,mp4a.40.2"
    assert playlist.variants[0].frame_rate == 50.0


def test_vod_playlist_has_endlist() -> None:
    playlist = parse_m3u8("#EXTM3U\n#EXTINF:3,\na.ts\n#EXT-X-ENDLIST\n")
    assert playlist.is_live is False


def test_ffmpeg_detects_extension_before_query_string() -> None:
    command = build_ffmpeg_command("https://cdn.example/index.m3u8?token=abc")
    assert "output.ts" in command


def test_ffmpeg_includes_referer_origin_and_user_agent() -> None:
    headers = (
        ("User-Agent", "Browser/1"),
        ("Referer", "https://site.example/watch"),
        ("Origin", "https://site.example"),
    )
    command = build_ffmpeg_command(
        "https://cdn.example/index.m3u8", request_headers=headers
    )
    assert "Browser/1" in command
    assert "Referer: https://site.example/watch" in command
    assert "Origin: https://site.example" in command


def test_ffmpeg_excludes_sensitive_headers_by_default() -> None:
    headers = (
        ("Cookie", "session=secret"),
        ("Authorization", "Bearer secret"),
    )
    command = build_ffmpeg_command(
        "https://cdn.example/index.m3u8", request_headers=headers
    )
    assert "session=secret" not in command
    assert "Bearer secret" not in command


def test_ffmpeg_sensitive_headers_require_explicit_opt_in() -> None:
    headers = (
        ("Cookie", "session=secret"),
        ("Authorization", "Bearer secret"),
    )
    command = build_ffmpeg_command(
        "https://cdn.example/index.m3u8",
        request_headers=headers,
        include_sensitive_headers=True,
    )
    assert "Cookie: session=secret" in command
    assert "Authorization: Bearer secret" in command
