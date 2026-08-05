from __future__ import annotations

from streaminspector.football_stream_discovery import (
    API_ORIGIN,
    FOOTBALL_PAGE_URL,
    _headers,
    extract_direct_m3u8,
)


def test_backend_headers_do_not_include_sensitive_credentials() -> None:
    headers = dict(_headers())

    assert headers["Origin"] == "https://jack37eo.mpcourageny9i9zzipper.my"
    assert headers["Referer"] == "https://jack37eo.mpcourageny9i9zzipper.my/"
    assert "Cookie" not in headers
    assert "Authorization" not in headers


def test_backend_defaults_point_to_configured_public_endpoints() -> None:
    assert FOOTBALL_PAGE_URL.endswith("/es/football.html")
    assert API_ORIGIN.startswith("https://")


def test_extracts_literal_and_json_escaped_m3u8() -> None:
    literal = b'{"url":"https://cdn.example/live/index.m3u8?token=abc"}'
    escaped = b'{"url":"https:\\/\\/cdn.example\\/live\\/index.m3u8?token=abc"}'

    assert extract_direct_m3u8(literal, ()) == (
        "https://cdn.example/live/index.m3u8?token=abc"
    )
    assert extract_direct_m3u8(escaped, ()) == (
        "https://cdn.example/live/index.m3u8?token=abc"
    )
