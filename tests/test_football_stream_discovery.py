from __future__ import annotations

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.football_stream_discovery import (
    extract_direct_m3u8,
    latest_match_detail_template,
    replace_match_id,
    safe_request_headers,
)


def test_replaces_match_id_without_changing_other_parameters() -> None:
    url = (
        "https://api.example/sfver123/api/match/detail?"
        "matchId=10&sportType=1&language=4&stream=true"
    )

    updated = replace_match_id(url, 99)

    assert "matchId=99" in updated
    assert "sportType=1" in updated
    assert "language=4" in updated
    assert "stream=true" in updated


def test_safe_headers_exclude_cookie_and_authorization() -> None:
    headers = (
        ("User-Agent", "Browser"),
        ("Referer", "https://example.test/"),
        ("Origin", "https://example.test"),
        ("Cookie", "secret=1"),
        ("Authorization", "Bearer secret"),
    )

    safe = dict(safe_request_headers(headers))

    assert safe["User-Agent"] == "Browser"
    assert "Cookie" not in safe
    assert "Authorization" not in safe


def test_extracts_literal_and_json_escaped_m3u8() -> None:
    literal = b'{"url":"https://cdn.example/live/index.m3u8?token=abc"}'
    escaped = b'{"url":"https:\\/\\/cdn.example\\/live\\/index.m3u8?token=abc"}'

    assert extract_direct_m3u8(literal, ()) == (
        "https://cdn.example/live/index.m3u8?token=abc"
    )
    assert extract_direct_m3u8(escaped, ()) == (
        "https://cdn.example/live/index.m3u8?token=abc"
    )


def test_uses_latest_captured_match_detail_as_template() -> None:
    flows = [
        HttpFlowCaptured(url="https://api.example/api/match/detail?matchId=1"),
        HttpFlowCaptured(url="https://api.example/api/match/live?sportType=1"),
        HttpFlowCaptured(url="https://api.example/api/match/detail?matchId=2"),
    ]

    template = latest_match_detail_template(flows)

    assert template is flows[2]
