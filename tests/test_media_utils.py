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


def test_ffmpeg_obfuscated_doc_url_falls_back_to_mp4() -> None:
    """El bug que reportó el user: streams que llegan con extensión
    falsa tipo `.doc` y content-type `application/octet-stream` caían al
    genérico `output.bin`, que ningún player abre. Ahora el fallback
    universal es `.mp4`.
    """
    cmd = build_ffmpeg_command(
        "https://adair.sworfa.kdns.fr/cfall/s2001/v3b/9o3n25o3nUE0pQbiY3OfLKxhZGO4p3EgZv50o3N%3D"
        "/hedy/sx_761151/1785867568249.doc?_ver=1785867570&_s1=2bb96eba&_s2=5e77e6fde204928ffa0cd2fe2a8d78e1",
        "application/octet-stream",
    )
    assert "output.mp4" in cmd
    assert "output.bin" not in cmd
    assert "1785867568249.doc" in cmd  # la URL se preserva


def test_ffmpeg_obfuscated_url_without_content_type_uses_mp4() -> None:
    """URL obfuscada sin content-type: fallback a .mp4."""
    cmd = build_ffmpeg_command("https://cdn.example.com/abc123def.bin", "")
    assert "output.mp4" in cmd
    assert "output.bin" not in cmd


def test_ffmpeg_dash_segment_url_uses_mp4() -> None:
    """Los segmentos DASH (.m4s) van a .mp4."""
    cmd = build_ffmpeg_command("https://cdn.example.com/seg-00001.m4s", "")
    assert "output.mp4" in cmd


def test_ffmpeg_mov_url_uses_mp4() -> None:
    """Quicktime (.mov) se reempaqueta en .mp4 (mismo codec)."""
    cmd = build_ffmpeg_command("https://cdn.example.com/clip.mov", "")
    assert "output.mp4" in cmd


def test_ffmpeg_mkv_url_uses_mkv() -> None:
    cmd = build_ffmpeg_command("https://cdn.example.com/movie.mkv", "")
    assert "output.mkv" in cmd


def test_ffmpeg_flv_url_uses_flv() -> None:
    cmd = build_ffmpeg_command("https://cdn.example.com/stream.flv", "")
    assert "output.flv" in cmd


def test_ffmpeg_3gp_url_uses_3gp() -> None:
    cmd = build_ffmpeg_command("https://cdn.example.com/clip.3gp", "")
    assert "output.3gp" in cmd


def test_ffmpeg_smoothstreaming_url_uses_mp4() -> None:
    """Manifests SmoothStreaming (.ism) y (.ism/manifest) van a .mp4."""
    cmd = build_ffmpeg_command("https://cdn.example.com/manifest.ism", "")
    assert "output.mp4" in cmd
    cmd = build_ffmpeg_command(
        "https://cdn.example.com/manifest.ism/manifest", ""
    )
    assert "output.mp4" in cmd


def test_ffmpeg_hds_url_uses_mp4() -> None:
    """HDS Flash (.f4m) va a .mp4 (f4m ya no es habitual, .mp4 es lo
    más cercano que reproduce ffmpeg con `-c copy`)."""
    cmd = build_ffmpeg_command("https://cdn.example.com/manifest.f4m", "")
    assert "output.mp4" in cmd


def test_ffmpeg_never_produces_output_bin() -> None:
    """El fallback universal es .mp4, .bin ya no aparece nunca."""
    for url in [
        "https://x.com/random",
        "https://x.com/file.xyz",
        "https://x.com/segment",
        "https://x.com/foo.bin",
    ]:
        cmd = build_ffmpeg_command(url, "application/octet-stream")
        assert "output.bin" not in cmd, f"output.bin shouldn't appear for {url}"
        assert "output.mp4" in cmd, f"output.mp4 should appear for {url}"


# ---------------------- build_ffmpeg_command con request_headers --------------


def test_ffmpeg_includes_default_user_agent() -> None:
    """Sin headers capturados, ffmpeg lleva un UA de Chrome real (no Lavf/...).
    Sin esto, muchos CDNs (Cloudflare, etc.) rechazan la request."""
    cmd = build_ffmpeg_command("https://x.com/playlist.m3u8", "")
    assert "Mozilla" in cmd
    assert "Chrome" in cmd
    # El UA de ffmpeg por defecto (Lavf/...) NO debe aparecer.
    assert "Lavf" not in cmd


def test_ffmpeg_uses_user_agent_from_captured_headers() -> None:
    """Si el flow capturado llevaba un User-Agent, ese se reusa."""
    headers = (
        ("User-Agent", "MyApp/1.2.3"),
        ("Referer", "https://example.com/page"),
    )
    cmd = build_ffmpeg_command("https://x.com/playlist.m3u8", "", headers)
    assert "MyApp/1.2.3" in cmd
    assert "Mozilla" not in cmd  # el default no debe pisar al capturado


def test_ffmpeg_includes_referer_from_captured_headers() -> None:
    """El Referer capturado se mete en `-headers` para que ffmpeg lo envíe.
    Sin esto, los streams protegidos devuelven 403."""
    headers = (
        ("Referer", "https://fctv33hd.fit/eventos/newport-county-vs-roma/"),
    )
    cmd = build_ffmpeg_command(
        "https://adair.sworfa.kdns.fr/cfall/s2001/v3b/9o3n25o3nUE0pQbiY3OfLKxhZGO4p3EgZv50o3N/hedy/sx_761151/1785867564125.avi",
        "application/octet-stream",
        headers,
    )
    assert "-headers" in cmd
    assert "Referer: https://fctv33hd.fit/eventos/newport-county-vs-roma/" in cmd
    assert "output.mp4" in cmd


def test_ffmpeg_escapes_quotes_in_referer() -> None:
    """Si el Referer trae comillas, se escapan para no romper PowerShell."""
    headers = (("Referer", 'https://x.com/p"age'),)
    cmd = build_ffmpeg_command("https://x.com/v.mp4", "", headers)
    # Las comillas en el Referer deben quedar escapadas con backslash
    assert '\\"' in cmd


def test_ffmpeg_ignores_empty_header_values() -> None:
    """Headers con valor vacío no se incluyen en el comando."""
    headers = (
        ("Referer", ""),
        ("User-Agent", ""),
    )
    cmd = build_ffmpeg_command("https://x.com/v.mp4", "", headers)
    # Caemos al default
    assert "Mozilla" in cmd
    assert "-headers" not in cmd


def test_ffmpeg_referer_is_case_insensitive_lookup() -> None:
    """Los headers HTTP son case-insensitive; el panel los pasa tal cual
    del addon, así que tenemos que buscar 'referer' o 'Referer' igual."""
    headers = (("referer", "https://lowercase.example/"),)
    cmd = build_ffmpeg_command("https://x.com/v.mp4", "", headers)
    assert "Referer: https://lowercase.example/" in cmd


def test_ffmpeg_works_without_request_headers_kwarg() -> None:
    """Llamada legacy sin `request_headers` no rompe (backwards compat)."""
    cmd = build_ffmpeg_command("https://x.com/v.mp4", "video/mp4")
    assert "output.mp4" in cmd
    # No hay -headers si no se pasaron headers
    assert "-headers" not in cmd


def test_ffmpeg_url_with_quotes_still_escaped_with_headers() -> None:
    """URL con comillas sigue escapándose aunque se le pasen headers."""
    headers = (("Referer", "https://x.com/page"),)
    cmd = build_ffmpeg_command('https://x.com/v".mp4', "", headers)
    assert '\\"' in cmd
    assert "Referer: https://x.com/page" in cmd
