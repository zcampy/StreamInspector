"""Cliente HTTP de la pestaña Partidos, independiente del proxy local."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from streaminspector.football_events import FootballEvent, parse_football_events
from streaminspector.media_utils import decode_response_body
from streaminspector.telegram_source_resolver import (
    football_page_from_site,
    resolve_latest_public_site,
)

# Se mantiene solo como respaldo si Telegram no se puede consultar.
FOOTBALL_PAGE_URL = "https://jack37eo.mpcourageny9zzipper.my/es/football.html"
API_ORIGIN = "https://apis-data-defra10.tcdru136ovur.ru"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
_M3U8_RE = re.compile(rb"https?://[^\x00-\x20\"'<>]+?\.m3u8(?:\?[^\x00-\x20\"'<>]*)?", re.I)
_SFVER_RE = re.compile(r"(?:https?://[^\"'\s<>]+)?(/sfver[0-9a-f]{16,})", re.I)
_SCRIPT_RE = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)


@dataclass(frozen=True, slots=True)
class BackendContext:
    api_base: str
    request_headers: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    events: list[FootballEvent]
    context: BackendContext | None
    message: str


@dataclass(frozen=True, slots=True)
class DirectPlaylistResult:
    match_id: int
    url: str | None
    message: str
    request_headers: tuple[tuple[str, str], ...] = ()


def _headers(page_url: str = FOOTBALL_PAGE_URL) -> tuple[tuple[str, str], ...]:
    origin = f"{urlsplit(page_url).scheme}://{urlsplit(page_url).netloc}"
    return (
        ("User-Agent", _USER_AGENT),
        ("Accept", "application/json, text/plain, */*"),
        ("Accept-Language", "es-ES,es;q=0.9"),
        ("Origin", origin),
        ("Referer", origin + "/"),
    )


def _get(url: str, headers: tuple[tuple[str, str], ...], timeout: float = 10.0) -> tuple[bytes, tuple[tuple[str, str], ...]]:
    # ProxyHandler({}) evita tanto el proxy interno de StreamInspector como el proxy del sistema.
    opener = build_opener(ProxyHandler({}))
    request = Request(url, headers=dict(headers), method="GET")
    with opener.open(request, timeout=timeout) as response:  # noqa: S310 - endpoints HTTPS configurados
        return response.read(4_000_000), tuple(response.headers.items())


def extract_direct_m3u8(body: bytes, response_headers: tuple[tuple[str, str], ...]) -> str | None:
    decoded = decode_response_body(body, response_headers)
    for candidate in (decoded, decoded.replace(b"\\/", b"/")):
        match = _M3U8_RE.search(candidate)
        if match:
            return match.group(0).decode("utf-8", errors="strict")
    return None


def _versioned_bases(page_url: str, headers: tuple[tuple[str, str], ...]) -> list[str]:
    bases: list[str] = [API_ORIGIN]
    try:
        page_body, page_headers = _get(page_url, headers)
        html = decode_response_body(page_body, page_headers).decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError):
        return bases

    documents = [html]
    for src in _SCRIPT_RE.findall(html)[:12]:
        try:
            body, response_headers = _get(urljoin(page_url, unescape(src)), headers, timeout=6.0)
            documents.append(decode_response_body(body, response_headers).decode("utf-8", errors="replace"))
        except (HTTPError, URLError, TimeoutError, OSError):
            continue

    for document in documents:
        for path in _SFVER_RE.findall(document):
            candidate = API_ORIGIN + path.rstrip("/")
            if candidate not in bases:
                bases.insert(0, candidate)
    return bases


def _resolve_page_url(page_url: str | None) -> tuple[str, str]:
    if page_url:
        return page_url, "Fuente indicada manualmente"

    resolution = resolve_latest_public_site()
    if resolution.url:
        return football_page_from_site(resolution.url), resolution.message
    return FOOTBALL_PAGE_URL, f"{resolution.message}; usando la fuente de respaldo"


def load_backend_schedule(page_url: str | None = None) -> ScheduleResult:
    resolved_page_url, source_message = _resolve_page_url(page_url)
    headers = _headers(resolved_page_url)
    last_error = "La API no devolvió partidos"
    for base in _versioned_bases(resolved_page_url, headers):
        url = base + "/api/match/live?sportType=1&language=4&stream=true"
        try:
            body, response_headers = _get(url, headers)
            events = parse_football_events(body, response_headers)
        except HTTPError as exc:
            last_error = f"HTTP {exc.code} al cargar el calendario"
            continue
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = str(exc)
            continue
        if events:
            return ScheduleResult(
                events,
                BackendContext(base, headers),
                f"{source_message}. Calendario cargado en segundo plano",
            )
    return ScheduleResult([], None, f"{source_message}. {last_error}")


def discover_direct_playlist(
    context: BackendContext,
    match_id: int,
    *,
    timeout: float = 8.0,
) -> DirectPlaylistResult:
    url = (
        context.api_base
        + f"/api/match/detail?matchId={match_id}&sportType=1&language=4&stream=true"
    )
    try:
        body, response_headers = _get(url, context.request_headers, timeout)
    except HTTPError as exc:
        return DirectPlaylistResult(match_id, None, f"HTTP {exc.code}", context.request_headers)
    except (URLError, TimeoutError, OSError) as exc:
        return DirectPlaylistResult(match_id, None, str(exc), context.request_headers)

    direct = extract_direct_m3u8(body, response_headers)
    if direct:
        return DirectPlaylistResult(match_id, direct, "M3U8 directo encontrado", context.request_headers)
    return DirectPlaylistResult(
        match_id,
        None,
        "La respuesta no contiene un M3U8 directo",
        context.request_headers,
    )
