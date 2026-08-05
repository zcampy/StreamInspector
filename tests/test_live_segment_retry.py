from __future__ import annotations

from collections.abc import Mapping

from streaminspector.stream_validation import HttpFetchResult, validate_reproducible_link


def _result(url: str, body: bytes, status: int = 200) -> HttpFetchResult:
    return HttpFetchResult(status=status, final_url=url, headers={}, body=body)


def _ts_payload() -> bytes:
    packet = bytes([0x47]) + b"\x00" * 187
    return packet + packet


class SequenceFetcher:
    def __init__(self, responses: dict[str, list[HttpFetchResult]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        max_bytes: int,
        byte_range: str | None,
    ) -> HttpFetchResult:
        self.calls.append(url)
        queue = self.responses[url]
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]


def test_tries_older_recent_segment_when_latest_is_404() -> None:
    playlist = "https://cdn.example/live.m3u8"
    old = "https://cdn.example/100.json"
    latest = "https://cdn.example/101.json"
    fetcher = SequenceFetcher(
        {
            playlist: [_result(playlist, b"#EXTM3U\n#EXTINF:3,\n100.json\n#EXTINF:3,\n101.json\n")],
            latest: [_result(latest, b"not found", 404)],
            old: [_result(old, _ts_payload(), 206)],
        }
    )

    result = validate_reproducible_link(playlist, fetcher=fetcher)

    assert result.ok is True
    assert result.segment_url == old
    assert fetcher.calls == [playlist, latest, old]


def test_refreshes_live_playlist_after_all_current_segments_expire() -> None:
    playlist = "https://cdn.example/live.m3u8"
    expired = "https://cdn.example/101.json"
    fresh = "https://cdn.example/102.json"
    fetcher = SequenceFetcher(
        {
            playlist: [
                _result(playlist, b"#EXTM3U\n#EXTINF:3,\n101.json\n"),
                _result(playlist, b"#EXTM3U\n#EXTINF:3,\n102.json\n"),
            ],
            expired: [_result(expired, b"not found", 404)],
            fresh: [_result(fresh, _ts_payload(), 206)],
        }
    )

    result = validate_reproducible_link(playlist, fetcher=fetcher)

    assert result.ok is True
    assert result.segment_url == fresh
    assert fetcher.calls == [playlist, expired, playlist, fresh]


def test_reports_expired_token_after_refreshes_still_return_404() -> None:
    playlist = "https://cdn.example/live.m3u8"
    segment = "https://cdn.example/101.json"
    playlist_body = b"#EXTM3U\n#EXTINF:3,\n101.json\n"
    fetcher = SequenceFetcher(
        {
            playlist: [_result(playlist, playlist_body)],
            segment: [_result(segment, b"not found", 404)],
        }
    )

    result = validate_reproducible_link(playlist, fetcher=fetcher)

    assert result.ok is False
    assert result.status_code == 404
    assert "token puede haber caducado" in result.message
    assert fetcher.calls.count(playlist) == 3
