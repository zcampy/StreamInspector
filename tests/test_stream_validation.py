from __future__ import annotations

from collections.abc import Mapping

from streaminspector.stream_validation import (
    HttpFetchResult,
    detect_media_format,
    validate_reproducible_link,
)


class FakeFetcher:
    def __init__(self, responses: dict[str, HttpFetchResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Mapping[str, str], int, str | None]] = []

    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        max_bytes: int,
        byte_range: str | None,
    ) -> HttpFetchResult:
        self.calls.append((url, headers, max_bytes, byte_range))
        return self.responses[url]


def _result(
    url: str,
    body: bytes,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
) -> HttpFetchResult:
    return HttpFetchResult(
        status=status,
        final_url=url,
        headers=headers or {},
        body=body,
    )


def _ts_payload() -> bytes:
    packet = bytes([0x47]) + b"\x00" * 187
    return packet + packet


def test_detects_mpeg_ts_even_when_extension_is_json() -> None:
    assert detect_media_format(_ts_payload()) == "mpeg-ts"


def test_detects_fragmented_mp4_signature() -> None:
    assert detect_media_format(b"\x00\x00\x00\x18ftypisompayload") == "fmp4"
    assert detect_media_format(b"\x00\x00\x00\x10moofpayload") == "fmp4"


def test_classifies_json_and_html_error_payloads() -> None:
    assert detect_media_format(b'{"error":"forbidden"}') == "json"
    assert detect_media_format(b"<html>Forbidden</html>") == "html"


def test_validates_media_playlist_and_latest_segment() -> None:
    playlist_url = "https://cdn.example/live.m3u8"
    segment1 = "https://cdn.example/100.json"
    segment2 = "https://cdn.example/101.json"
    fetcher = FakeFetcher(
        {
            playlist_url: _result(
                playlist_url,
                b"#EXTM3U\n#EXTINF:3,\n100.json\n#EXTINF:3,\n101.json\n",
            ),
            segment2: _result(segment2, _ts_payload(), 206),
        }
    )

    validation = validate_reproducible_link(playlist_url, fetcher=fetcher)

    assert validation.ok is True
    assert validation.playable is True
    assert validation.media_format == "mpeg-ts"
    assert validation.stage == "complete"
    assert validation.segment_url == segment2
    assert fetcher.calls[-1][3] == "bytes=0-4095"


def test_master_playlist_selects_highest_bandwidth_variant() -> None:
    master = "https://cdn.example/master.m3u8"
    low = "https://cdn.example/low.m3u8"
    high = "https://cdn.example/high.m3u8"
    segment = "https://cdn.example/segment.m4s"
    fetcher = FakeFetcher(
        {
            master: _result(
                master,
                (
                    b"#EXTM3U\n"
                    b"#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=640x360\n"
                    b"low.m3u8\n"
                    b"#EXT-X-STREAM-INF:BANDWIDTH=5000,RESOLUTION=1920x1080\n"
                    b"high.m3u8\n"
                ),
            ),
            high: _result(high, b"#EXTM3U\n#EXTINF:4,\nsegment.m4s\n"),
            segment: _result(segment, b"\x00\x00\x00\x18ftypisomdata", 200),
        }
    )

    validation = validate_reproducible_link(master, fetcher=fetcher)

    assert validation.ok is True
    assert validation.playable is True
    assert validation.media_format == "fmp4"
    assert validation.media_playlist_url == high
    assert [call[0] for call in fetcher.calls] == [master, high, segment]


def test_does_not_send_cookie_without_opt_in() -> None:
    playlist = "https://cdn.example/live.m3u8"
    segment = "https://cdn.example/seg.ts"
    headers = (("Cookie", "session=secret"), ("Referer", "https://site.example/"))
    fetcher = FakeFetcher(
        {
            playlist: _result(playlist, b"#EXTM3U\n#EXTINF:3,\nseg.ts\n"),
            segment: _result(segment, _ts_payload()),
        }
    )

    validate_reproducible_link(playlist, headers, fetcher=fetcher)

    sent = fetcher.calls[0][1]
    assert "cookie" not in sent
    assert sent["referer"] == "https://site.example/"


def test_sends_cookie_with_explicit_opt_in() -> None:
    playlist = "https://cdn.example/live.m3u8"
    segment = "https://cdn.example/seg.ts"
    headers = (("Cookie", "session=secret"),)
    fetcher = FakeFetcher(
        {
            playlist: _result(playlist, b"#EXTM3U\n#EXTINF:3,\nseg.ts\n"),
            segment: _result(segment, _ts_payload()),
        }
    )

    validation = validate_reproducible_link(
        playlist,
        headers,
        include_sensitive_headers=True,
        fetcher=fetcher,
    )

    assert validation.ok is True
    assert validation.used_sensitive_headers is True
    assert fetcher.calls[0][1]["cookie"] == "session=secret"


def test_rejects_accessible_json_segment_as_not_playable() -> None:
    playlist = "https://cdn.example/live.m3u8"
    segment = "https://cdn.example/seg.json"
    fetcher = FakeFetcher(
        {
            playlist: _result(playlist, b"#EXTM3U\n#EXTINF:3,\nseg.json\n"),
            segment: _result(segment, b'{"error":"expired"}'),
        }
    )

    validation = validate_reproducible_link(playlist, fetcher=fetcher)

    assert validation.ok is False
    assert validation.playable is False
    assert validation.stage == "format"
    assert validation.media_format == "json"


def test_reports_http_403_on_playlist() -> None:
    playlist = "https://cdn.example/expired.m3u8"
    fetcher = FakeFetcher({playlist: _result(playlist, b"Forbidden", 403)})

    validation = validate_reproducible_link(playlist, fetcher=fetcher)

    assert validation.ok is False
    assert validation.stage == "playlist"
    assert validation.status_code == 403
    assert "403" in validation.message


def test_rejects_non_hls_response() -> None:
    playlist = "https://cdn.example/not-hls"
    fetcher = FakeFetcher({playlist: _result(playlist, b"<html>no</html>")})

    validation = validate_reproducible_link(playlist, fetcher=fetcher)

    assert validation.ok is False
    assert validation.stage == "playlist"
    assert "HLS válida" in validation.message
