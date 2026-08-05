"""Descubrimiento limitado de playlists HLS expuestas directamente por la API.

Este módulo no ejecuta JavaScript, no descifra cargas y no reutiliza Cookie ni
Authorization. Solo repite una plantilla de petición ya capturada y acepta URLs
M3U8 presentes literalmente en una respuesta accesible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.media_utils import decode_response_body

_SAFE_HEADERS = {"user-agent", "referer", "origin", "accept", "accept-language"}
_M3U8_RE = re.compile(rb"https?://[^\x00-\x20\"'<>]+?\.m3u8(?:\?[^\x00-\x20\"'<>]*)?", re.I)


@dataclass(frozen=True, slots=True)
class DirectPlaylistResult:
    match_id: int
    url: str | None
    message: str
    request_headers: tuple[tuple[str, str], ...] = ()


def latest_match_detail_template(flows: list[HttpFlowCaptured]) -> HttpFlowCaptured | None:
    for flow in reversed(flows):
        if "/api/match/detail" in urlsplit(flow.url).path.lower():
            return flow
    return None


def replace_match_id(url: str, match_id: int) -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    replaced = False
    output: list[tuple[str, str]] = []
    for name, value in query:
        if name.lower() == "matchid":
            output.append((name, str(match_id)))
            replaced = True
        else:
            output.append((name, value))
    if not replaced:
        output.append(("matchId", str(match_id)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(output), parts.fragment))


def safe_request_headers(headers: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    return tuple((name, value) for name, value in headers if name.lower() in _SAFE_HEADERS)


def extract_direct_m3u8(body: bytes, response_headers: tuple[tuple[str, str], ...]) -> str | None:
    decoded = decode_response_body(body, response_headers)
    candidates = [decoded]
    # Algunas respuestas incluyen barras escapadas dentro de texto JSON/protobuf.
    candidates.append(decoded.replace(b"\\/", b"/"))
    for candidate in candidates:
        match = _M3U8_RE.search(candidate)
        if match:
            return match.group(0).decode("utf-8", errors="strict")
    return None


def discover_direct_playlist(
    template: HttpFlowCaptured,
    match_id: int,
    *,
    timeout: float = 8.0,
) -> DirectPlaylistResult:
    headers = safe_request_headers(template.request_headers)
    request = Request(
        replace_match_id(template.url, match_id),
        headers={name: value for name, value in headers},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL comes from captured HTTPS request
            body = response.read(2_000_000)
            response_headers = tuple(response.headers.items())
    except HTTPError as exc:
        return DirectPlaylistResult(match_id, None, f"HTTP {exc.code}", headers)
    except (URLError, TimeoutError, OSError) as exc:
        return DirectPlaylistResult(match_id, None, str(exc), headers)

    url = extract_direct_m3u8(body, response_headers)
    if url is None:
        return DirectPlaylistResult(
            match_id,
            None,
            "La API no expone un M3U8 directo; puede requerir la página o JavaScript",
            headers,
        )
    return DirectPlaylistResult(match_id, url, "M3U8 directo encontrado", headers)
