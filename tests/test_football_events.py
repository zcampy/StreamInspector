from __future__ import annotations

from streaminspector.football_events import parse_football_events


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
