from __future__ import annotations

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.football_events import (
    captured_playlist_for_match,
    match_id_from_stream_detail_url,
    parse_football_events,
)


def _varint(value: int) -> bytes:
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _field_varint(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _field_bytes(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _localized(text: str) -> bytes:
    return _field_varint(1, 4) + _field_bytes(2, text.encode())


def _flow(
    url: str,
    *,
    content_type: str = "application/json",
    body: bytes = b"",
) -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id=url,
        method="GET",
        scheme="https",
        host="example.test",
        port=443,
        path="/",
        url=url,
        http_version="HTTP/2.0",
        status_code=200,
        reason="OK",
        request_headers=(),
        response_headers=(),
        request_body=b"",
        response_body=body,
        content_type=content_type,
        response_size=len(body),
        duration_ms=1.0,
    )


def test_parses_live_football_event_metadata() -> None:
    competition = _field_bytes(3, _localized("USL Championship"))
    title = _field_bytes(2, b"FC Tulsa vs Sacramento Republic FC")
    metadata = b"".join(
        (
            _field_bytes(20, b"fc-tulsa-vs-sacramento-republic-fc"),
            _field_bytes(21, b"usl-championship"),
            _field_bytes(22, b"2026"),
        )
    )
    event = b"".join(
        (
            _field_varint(1, 4337957),
            _field_varint(3, 1785976200000),
            _field_bytes(10, competition),
            _field_bytes(30, title),
            _field_bytes(150, metadata),
        )
    )
    payload = _field_bytes(1, event)
    response = _field_bytes(3, b"Success") + _field_bytes(10, payload)

    events = parse_football_events(response)

    assert len(events) == 1
    parsed = events[0]
    assert parsed.match_id == 4337957
    assert parsed.competition == "USL Championship"
    assert parsed.home == "FC Tulsa"
    assert parsed.away == "Sacramento Republic FC"
    assert parsed.match_slug == "fc-tulsa-vs-sacramento-republic-fc"
    assert parsed.competition_slug == "usl-championship"
    assert parsed.season_slug == "2026"


def test_extracts_match_id_from_stream_detail_url() -> None:
    url = (
        "https://api.example/api/stream/detail?streamId=761151&matchId=4460343"
        "&sportType=1"
    )

    assert match_id_from_stream_detail_url(url) == 4460343
    assert match_id_from_stream_detail_url("https://api.example/api/match/live") is None


def test_correlates_playlist_after_stream_detail_request() -> None:
    flows = [
        _flow("https://api.example/api/stream/detail?matchId=4460343&streamId=1"),
        _flow(
            "https://cdn.example/live/index.m3u8",
            content_type="application/vnd.apple.mpegurl",
            body=b"#EXTM3U\n#EXTINF:2,\nsegment.ts\n",
        ),
        _flow("https://api.example/api/stream/detail?matchId=999&streamId=2"),
        _flow(
            "https://cdn.example/other/index.m3u8",
            content_type="application/vnd.apple.mpegurl",
            body=b"#EXTM3U\n",
        ),
    ]

    playlist = captured_playlist_for_match(flows, 4460343)

    assert playlist is not None
    assert playlist.url == "https://cdn.example/live/index.m3u8"
