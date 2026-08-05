"""Extracción y correlación de eventos de fútbol capturados."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.media_utils import decode_response_body, is_m3u8_response


@dataclass(frozen=True, slots=True)
class FootballEvent:
    match_id: int
    starts_at_ms: int
    competition: str
    title: str
    home: str
    away: str
    match_slug: str
    competition_slug: str
    season_slug: str

    @property
    def local_time(self) -> datetime:
        return datetime.fromtimestamp(self.starts_at_ms / 1000).astimezone()


class ProtobufDecodeError(ValueError):
    pass


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            break
    raise ProtobufDecodeError("Varint protobuf inválido")


def _fields(data: bytes) -> list[tuple[int, int, int | bytes]]:
    fields: list[tuple[int, int, int | bytes]] = []
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        number = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ProtobufDecodeError("Campo fixed64 truncado")
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ProtobufDecodeError("Campo protobuf truncado")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ProtobufDecodeError("Campo fixed32 truncado")
            value = data[offset:end]
            offset = end
        else:
            raise ProtobufDecodeError(f"Wire type protobuf no soportado: {wire_type}")
        fields.append((number, wire_type, value))
    return fields


def _first_int(data: bytes, number: int, default: int = 0) -> int:
    for field_number, wire_type, value in _fields(data):
        if field_number == number and wire_type == 0 and isinstance(value, int):
            return value
    return default


def _messages(data: bytes, number: int) -> list[bytes]:
    return [
        value
        for field_number, wire_type, value in _fields(data)
        if field_number == number and wire_type == 2 and isinstance(value, bytes)
    ]


def _utf8(data: bytes, number: int) -> str:
    for value in _messages(data, number):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return ""


def _localized_text(data: bytes) -> str:
    for message in _messages(data, 3):
        text = _utf8(message, 2)
        if text:
            return text
    return ""


def _parse_event(data: bytes) -> FootballEvent | None:
    match_id = _first_int(data, 1)
    starts_at_ms = _first_int(data, 3)

    competition = ""
    competition_messages = _messages(data, 10)
    if competition_messages:
        competition = _localized_text(competition_messages[0])

    title = ""
    for localized in _messages(data, 30):
        candidate = _utf8(localized, 2)
        if candidate:
            title = candidate
            break

    metadata_messages = _messages(data, 150)
    metadata = metadata_messages[0] if metadata_messages else b""
    match_slug = _utf8(metadata, 20)
    competition_slug = _utf8(metadata, 21)
    season_slug = _utf8(metadata, 22)

    if not match_id or not starts_at_ms or not title:
        return None
    home, separator, away = title.partition(" vs ")
    if not separator:
        home, away = title, ""
    return FootballEvent(
        match_id=match_id,
        starts_at_ms=starts_at_ms,
        competition=competition,
        title=title,
        home=home.strip(),
        away=away.strip(),
        match_slug=match_slug,
        competition_slug=competition_slug,
        season_slug=season_slug,
    )


def parse_football_events(
    body: bytes,
    response_headers: tuple[tuple[str, str], ...] | None = None,
) -> list[FootballEvent]:
    """Decodifica la respuesta de `/api/match/live?...stream=true`."""
    decoded = decode_response_body(body, response_headers or ())
    top_level = _messages(decoded, 10)
    if not top_level:
        return []
    events = [
        event
        for raw_event in _messages(top_level[0], 1)
        if (event := _parse_event(raw_event)) is not None
    ]
    return sorted(events, key=lambda item: item.starts_at_ms)


def is_football_events_url(url: str) -> bool:
    lowered = url.lower()
    return (
        "/api/match/live" in lowered
        and "sporttype=1" in lowered
        and "stream=true" in lowered
    )


def match_id_from_stream_detail_url(url: str) -> int | None:
    """Obtiene el partido asociado a `/api/stream/detail`."""
    parsed = urlparse(url)
    if "/api/stream/detail" not in parsed.path.lower():
        return None
    values = parse_qs(parsed.query).get("matchId") or parse_qs(parsed.query).get("matchid")
    if not values:
        return None
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


def captured_playlist_for_match(
    flows: list[HttpFlowCaptured],
    match_id: int,
) -> HttpFlowCaptured | None:
    """Relaciona un partido con la playlist HLS capturada tras pedir su stream.

    El navegador solicita `/api/stream/detail?...matchId=...` y, a continuación,
    genera la playlist HLS. Se toma la última playlist capturada entre esa petición
    y la siguiente petición de detalle de otro partido.
    """
    candidate: HttpFlowCaptured | None = None
    active = False
    for flow in flows:
        detail_match_id = match_id_from_stream_detail_url(flow.url)
        if detail_match_id is not None:
            if active and detail_match_id != match_id:
                break
            active = detail_match_id == match_id
            candidate = None
            continue
        if not active:
            continue
        if is_m3u8_response(
            flow.content_type,
            flow.response_body,
            flow.response_headers,
        ):
            candidate = flow
    return candidate
