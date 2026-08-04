"""Tests para el detector de vídeo/audio, parser m3u8 y generación de ffmpeg."""
from __future__ import annotations

from streaminspector.media_utils import (
    build_ffmpeg_command,
    is_m3u8_response,
    is_video_content_type,
    is_video_url,
    parse_m3u8,
)

# ------------------------ is_video_content_type --------------------------


def test_video_content_type_recognizes_hls() -> None:
    assert is_video_content_type("application/vnd.apple.mpegurl")
    assert is_video_content_type("application/x-mpegurl")


def test_video_content_type_recognizes_dash() -> None:
    assert is_video_content_type("application/dash+xml")


def test_video_content_type_recognizes_progressive() -> None:
    assert is_video_content_type("video/mp4")
    assert is_video_content_type("video/webm")
    assert is_video_content_type("video/quicktime")


def test_video_content_type_recognizes_segments() -> None:
    assert is_video_content_type("video/mp2t")  # .ts


def test_video_content_type_recognizes_audio_streams() -> None:
    assert is_video_content_type("audio/mpeg")
    assert is_video_content_type("audio/aac")


def test_video_content_type_ignores_charset() -> None:
    assert is_video_content_type("video/mp4; charset=utf-8")
    assert is_video_content_type("application/vnd.apple.mpegurl; charset=utf-8")


def test_video_content_type_rejects_html_and_json() -> None:
    assert not is_video_content_type("text/html")
    assert not is_video_content_type("text/html; charset=utf-8")
    assert not is_video_content_type("application/json")
    assert not is_video_content_type("text/css")
    assert not is_video_content_type("text/javascript")
    assert not is_video_content_type("")


def test_video_content_type_is_case_insensitive() -> None:
    assert is_video_content_type("VIDEO/MP4")
    assert is_video_content_type("Application/VND.Apple.MPEGURL")


# ----------------------------- is_video_url ------------------------------


def test_video_url_recognizes_m3u8() -> None:
    assert is_video_url("https://example.com/playlist.m3u8")
    assert is_video_url("https://example.com/master.m3u")


def test_video_url_recognizes_progressive_formats() -> None:
    for ext in ("mp4", "webm", "mov", "ts", "mkv", "flv", "3gp", "mpd"):
        assert is_video_url(f"https://cdn.example.com/video.{ext}"), ext


def test_video_url_ignores_unrelated_urls() -> None:
    assert not is_video_url("https://example.com/index.html")
    assert not is_video_url("https://api.example.com/users")
    assert not is_video_url("https://example.com/style.css")


def test_video_url_with_empty_string_is_false() -> None:
    assert not is_video_url("")


# --------------------------- is_m3u8_response ----------------------------


def test_m3u8_detected_by_content_type() -> None:
    assert is_m3u8_response("application/vnd.apple.mpegurl", b"")
    assert is_m3u8_response("application/x-mpegurl", b"")


def test_m3u8_detected_by_body_signature() -> None:
    body = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:5.0,\nseg.ts\n"
    assert is_m3u8_response("", body)
    assert is_m3u8_response("text/plain", body)


def test_m3u8_not_detected_for_other_bodies() -> None:
    assert not is_m3u8_response("", b"<html><body>not a playlist</body></html>")
    assert not is_m3u8_response("application/json", b'{"hello": "world"}')
    assert not is_m3u8_response("", b"")
    # Si el cuerpo empieza por #EXTM3U, lo tratamos como m3u8 aunque el resto
    # esté corrupto. El parser luego dirá "0 segmentos" si no hay nada válido.
    assert not is_m3u8_response("", b"some random bytes")


# ------------------------------ parse_m3u8 -------------------------------


def test_parse_simple_media_playlist() -> None:
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:6\n"
        "#EXTINF:5.0,\n"
        "seg1.ts\n"
        "#EXTINF:5.0,\n"
        "seg2.ts\n"
        "#EXT-X-ENDLIST\n"
    )
    playlist = parse_m3u8(text)
    assert playlist.version == 3
    assert playlist.target_duration == 6
    assert playlist.is_live is False
    assert playlist.is_master is False
    assert playlist.segment_count == 2
    assert playlist.total_duration == 10.0
    assert playlist.segments[0].url == "seg1.ts"
    assert playlist.segments[1].url == "seg2.ts"
    assert playlist.segments[0].duration == 5.0


def test_parse_live_playlist_has_no_endlist() -> None:
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:6\n"
        "#EXTINF:5.0,\n"
        "seg1.ts\n"
    )
    playlist = parse_m3u8(text)
    assert playlist.is_live is True
    assert playlist.segment_count == 1


def test_parse_master_playlist() -> None:
    text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=720x480\n"
        "720p.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2560000,RESOLUTION=1920x1080\n"
        "1080p.m3u8\n"
    )
    playlist = parse_m3u8(text)
    assert playlist.is_master is True
    assert playlist.is_live is False
    # El parser trata las URLs de variantes como entradas (sin duración).
    # El flag `is_master` permite a la UI distinguirlas de segmentos reales.
    assert playlist.segment_count == 2
    assert playlist.segments[0].url == "720p.m3u8"
    assert playlist.segments[0].duration is None


def test_parse_resolves_relative_urls() -> None:
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:6\n"
        "#EXTINF:5.0,\n"
        "seg1.ts\n"
    )
    playlist = parse_m3u8(
        text, base_url="https://cdn.example.com/streams/abc/master.m3u8"
    )
    assert playlist.segments[0].url == (
        "https://cdn.example.com/streams/abc/seg1.ts"
    )


def test_parse_keeps_absolute_urls_unchanged() -> None:
    text = "#EXTM3U\n#EXTINF:5.0,\nhttps://other.example.com/seg.ts\n"
    playlist = parse_m3u8(text, base_url="https://cdn.example.com/")
    assert playlist.segments[0].url == "https://other.example.com/seg.ts"


def test_parse_empty_playlist() -> None:
    playlist = parse_m3u8("#EXTM3U\n")
    assert playlist.segments == ()
    assert playlist.segment_count == 0
    assert playlist.total_duration == 0.0


def test_parse_handles_segments_without_extinf() -> None:
    text = "#EXTM3U\nseg1.ts\nseg2.ts\n"
    playlist = parse_m3u8(text)
    assert playlist.segment_count == 2
    assert all(s.duration is None for s in playlist.segments)


def test_parse_ignores_comments_and_blank_lines() -> None:
    text = (
        "#EXTM3U\n"
        "\n"
        "# comment line\n"
        "#EXTINF:5.0,\n"
        "\n"
        "seg1.ts\n"
    )
    playlist = parse_m3u8(text)
    assert playlist.segment_count == 1


# ------------------------- build_ffmpeg_command --------------------------


def test_ffmpeg_for_m3u8_uses_ts_container() -> None:
    cmd = build_ffmpeg_command(
        "https://cdn.example.com/playlist.m3u8",
        "application/vnd.apple.mpegurl",
    )
    assert "ffmpeg" in cmd
    assert "playlist.m3u8" in cmd
    assert "output.ts" in cmd
    assert "-c copy" in cmd


def test_ffmpeg_for_dash_uses_mp4() -> None:
    cmd = build_ffmpeg_command(
        "https://cdn.example.com/manifest.mpd",
        "application/dash+xml",
    )
    assert "output.mp4" in cmd
    assert ".mpd" in cmd


def test_ffmpeg_for_mp4_uses_mp4() -> None:
    cmd = build_ffmpeg_command(
        "https://cdn.example.com/video.mp4", "video/mp4"
    )
    assert "output.mp4" in cmd


def test_ffmpeg_for_webm_uses_webm() -> None:
    cmd = build_ffmpeg_command(
        "https://cdn.example.com/video.webm", "video/webm"
    )
    assert "output.webm" in cmd


def test_ffmpeg_handles_url_without_content_type() -> None:
    """Si no hay content-type, ffmpeg infiere por extensión."""
    assert "output.ts" in build_ffmpeg_command("https://x.com/x.m3u8", "")
    assert "output.mp4" in build_ffmpeg_command("https://x.com/x.mp4", "")
    assert "output.webm" in build_ffmpeg_command("https://x.com/x.webm", "")
    assert "output.ts" in build_ffmpeg_command("https://x.com/x.ts", "")


def test_ffmpeg_escapes_url_with_quotes() -> None:
    """URLs con comillas no deben romper la línea de comandos."""
    cmd = build_ffmpeg_command('https://x.com/foo".m3u8', "")
    # Las comillas se escapan para evitar inyección en el shell del usuario
    assert '\\"' in cmd
