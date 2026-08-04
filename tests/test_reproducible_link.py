from __future__ import annotations

import brotli

from streaminspector.media_utils import (
    M3u8Playlist,
    M3u8Variant,
    appears_temporary_or_signed,
    build_reproducible_link_info,
    decode_response_body,
    is_m3u8_response,
    select_best_variant,
)


def test_brotli_playlist_is_decoded_and_detected() -> None:
    plain = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:3,\nsegment.ts\n"
    compressed = brotli.compress(plain)
    headers = (("Content-Encoding", "br"),)

    assert decode_response_body(compressed, headers) == plain
    assert is_m3u8_response("text/plain", compressed, headers)


def test_select_best_variant_prefers_bandwidth_then_resolution() -> None:
    playlist = M3u8Playlist(
        is_master=True,
        variants=(
            M3u8Variant(
                url="https://cdn.example/720.m3u8",
                bandwidth=2_000_000,
                resolution="1280x720",
            ),
            M3u8Variant(
                url="https://cdn.example/1080.m3u8",
                bandwidth=4_000_000,
                resolution="1920x1080",
            ),
            M3u8Variant(
                url="https://cdn.example/1080-60.m3u8",
                bandwidth=4_000_000,
                resolution="1920x1080",
                frame_rate=60.0,
            ),
        ),
    )

    best = select_best_variant(playlist)
    assert best is not None
    assert best.url.endswith("1080-60.m3u8")


def test_signed_url_is_detected() -> None:
    assert appears_temporary_or_signed(
        "https://cdn.example/token-abc/index.m3u8?sig=xyz"
    )
    assert not appears_temporary_or_signed("https://cdn.example/live/index.m3u8")


def test_reproducible_link_uses_best_variant_and_reports_headers() -> None:
    playlist = M3u8Playlist(
        is_master=True,
        variants=(
            M3u8Variant(
                url="https://cdn.example/low.m3u8",
                bandwidth=800_000,
                resolution="640x360",
            ),
            M3u8Variant(
                url="https://cdn.example/token-best/high.m3u8?expires=9999999999",
                bandwidth=5_000_000,
                resolution="1920x1080",
            ),
        ),
    )
    headers = (
        ("User-Agent", "Browser/1"),
        ("Referer", "https://site.example/watch"),
        ("Origin", "https://site.example"),
        ("Cookie", "session=secret"),
    )

    info = build_reproducible_link_info(
        "https://cdn.example/master.m3u8",
        playlist,
        headers,
    )

    assert info.url.endswith("high.m3u8?expires=9999999999")
    assert info.appears_temporary
    assert info.required_headers == ("Referer", "Origin", "User-Agent")
    assert info.sensitive_headers == ("Cookie",)
    assert "Referer:" in info.command
    assert "Origin:" in info.command
    assert "Cookie:" not in info.command


def test_sensitive_headers_only_enter_command_with_opt_in() -> None:
    headers = (
        ("Cookie", "session=secret"),
        ("Authorization", "Bearer secret"),
    )
    safe = build_reproducible_link_info(
        "https://cdn.example/live.m3u8",
        None,
        headers,
    )
    full = build_reproducible_link_info(
        "https://cdn.example/live.m3u8",
        None,
        headers,
        include_sensitive_headers=True,
    )

    assert "Cookie:" not in safe.command
    assert "Authorization:" not in safe.command
    assert "Cookie: session=secret" in full.command
    assert "Authorization: Bearer secret" in full.command
