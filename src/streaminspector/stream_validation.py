"""Validación ligera de enlaces HLS con las cabeceras de la captura."""

from __future__ import annotations

import gzip
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from streaminspector.media_utils import parse_m3u8, select_best_variant

_MAX_PLAYLIST_BYTES = 2 * 1024 * 1024
_MAX_SEGMENT_BYTES = 4096
_SEGMENTS_TO_TRY = 4
_PLAYLIST_REFRESHES = 2
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class HttpFetchResult:
    status: int
    final_url: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class StreamValidationResult:
    ok: bool
    stage: str
    message: str
    playlist_url: str
    media_playlist_url: str | None = None
    segment_url: str | None = None
    status_code: int | None = None
    used_sensitive_headers: bool = False
    media_format: str | None = None
    playable: bool = False


Fetcher = Callable[[str, Mapping[str, str], int, str | None], HttpFetchResult]


def _header_map(request_headers, *, include_sensitive_headers: bool) -> dict[str, str]:
    allowed = {"user-agent", "referer", "origin", "accept", "accept-language"}
    if include_sensitive_headers:
        allowed.update({"cookie", "authorization"})
    result: dict[str, str] = {}
    for name, value in request_headers or ():
        lower = name.lower()
        if value and lower in allowed and lower not in result:
            result[lower] = value
    result.setdefault("user-agent", _DEFAULT_USER_AGENT)
    result.setdefault("accept", "*/*")
    result["accept-encoding"] = "gzip, deflate, br"
    return result


def _decode_content(body: bytes, headers: Mapping[str, str]) -> bytes:
    encoding = headers.get("content-encoding", "").lower().strip()
    try:
        if encoding == "gzip":
            return gzip.decompress(body)
        if encoding == "deflate":
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
        if encoding == "br":
            import brotli
            return brotli.decompress(body)
    except (OSError, ValueError, zlib.error):
        return body
    return body


def detect_media_format(body: bytes) -> str:
    """Reconoce formatos multimedia por firma, sin confiar en extensión o MIME."""
    if not body:
        return "empty"
    if body[0] == 0x47 and (len(body) < 189 or body[188] == 0x47):
        return "mpeg-ts"
    if len(body) >= 8 and body[4:8] in {b"ftyp", b"styp", b"moof", b"moov"}:
        return "fmp4"
    if any(marker in body[:64] for marker in (b"ftyp", b"styp", b"moof", b"moov")):
        return "fmp4"
    stripped = body.lstrip()
    if stripped.startswith((b"{", b"[")):
        return "json"
    if stripped.lower().startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "html"
    if stripped.startswith(b"#EXTM3U"):
        return "hls-playlist"
    return "unknown-binary"


def _fetch_http(url: str, headers: Mapping[str, str], max_bytes: int, byte_range: str | None) -> HttpFetchResult:
    request_headers = {name.title(): value for name, value in headers.items()}
    if byte_range:
        request_headers["Range"] = byte_range
    request = Request(url, headers=request_headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            raw_headers = {name.lower(): value for name, value in response.headers.items()}
            return HttpFetchResult(int(response.status), response.geturl(), raw_headers, response.read(max_bytes))
    except HTTPError as exc:
        raw_headers = {name.lower(): value for name, value in exc.headers.items()}
        return HttpFetchResult(int(exc.code), exc.geturl(), raw_headers, exc.read(max_bytes))


def _validate_http_url(url: str) -> bool:
    try:
        return urlsplit(url).scheme.lower() in {"http", "https"}
    except ValueError:
        return False


def _playlist_from_result(result: HttpFetchResult):
    decoded = _decode_content(result.body, result.headers)
    try:
        text = decoded.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if not text.lstrip().startswith("#EXTM3U"):
        return None
    return parse_m3u8(text, base_url=result.final_url)


def _failure(*, message: str, playlist_url: str, media_url: str | None, segment_url: str | None = None,
             status: int | None = None, sensitive: bool = False, stage: str = "segment") -> StreamValidationResult:
    return StreamValidationResult(False, stage, message, playlist_url, media_url, segment_url, status, sensitive)


def validate_reproducible_link(playlist_url: str, request_headers=None, *, include_sensitive_headers: bool = False,
                               fetcher: Fetcher = _fetch_http) -> StreamValidationResult:
    """Comprueba playlist, mejor variante y varios segmentos recientes de un directo."""
    if not _validate_http_url(playlist_url):
        return _failure(message="La URL no utiliza HTTP o HTTPS.", playlist_url=playlist_url,
                        media_url=None, sensitive=include_sensitive_headers, stage="url")

    headers = _header_map(request_headers, include_sensitive_headers=include_sensitive_headers)
    try:
        root_result = fetcher(playlist_url, headers, _MAX_PLAYLIST_BYTES, None)
    except (OSError, URLError, TimeoutError) as exc:
        return _failure(message=f"No se pudo conectar con la playlist: {exc}", playlist_url=playlist_url,
                        media_url=None, sensitive=include_sensitive_headers, stage="playlist")
    if root_result.status not in {200, 206}:
        return _failure(message=f"La playlist respondió HTTP {root_result.status}.", playlist_url=playlist_url,
                        media_url=None, status=root_result.status, sensitive=include_sensitive_headers, stage="playlist")

    playlist = _playlist_from_result(root_result)
    if playlist is None:
        return _failure(message="La respuesta no contiene una playlist HLS válida.", playlist_url=root_result.final_url,
                        media_url=None, status=root_result.status, sensitive=include_sensitive_headers, stage="playlist")

    media_url = root_result.final_url
    if playlist.is_master:
        variant = select_best_variant(playlist)
        if variant is None:
            return _failure(message="La playlist maestra no contiene variantes utilizables.",
                            playlist_url=root_result.final_url, media_url=None,
                            sensitive=include_sensitive_headers, stage="variant")
        media_url = variant.url
        try:
            media_result = fetcher(media_url, headers, _MAX_PLAYLIST_BYTES, None)
        except (OSError, URLError, TimeoutError) as exc:
            return _failure(message=f"No se pudo cargar la mejor variante: {exc}",
                            playlist_url=root_result.final_url, media_url=media_url,
                            sensitive=include_sensitive_headers, stage="variant")
        if media_result.status not in {200, 206}:
            return _failure(message=f"La mejor variante respondió HTTP {media_result.status}.",
                            playlist_url=root_result.final_url, media_url=media_url,
                            status=media_result.status, sensitive=include_sensitive_headers, stage="variant")
        playlist = _playlist_from_result(media_result)
        if playlist is None:
            return _failure(message="La mejor variante no contiene una playlist HLS válida.",
                            playlist_url=root_result.final_url, media_url=media_result.final_url,
                            sensitive=include_sensitive_headers, stage="variant")
        media_url = media_result.final_url

    last_status: int | None = None
    last_segment_url: str | None = None
    last_format: str | None = None

    for refresh in range(_PLAYLIST_REFRESHES + 1):
        if refresh:
            try:
                refreshed = fetcher(media_url, headers, _MAX_PLAYLIST_BYTES, None)
            except (OSError, URLError, TimeoutError):
                continue
            if refreshed.status not in {200, 206}:
                last_status = refreshed.status
                continue
            refreshed_playlist = _playlist_from_result(refreshed)
            if refreshed_playlist is None:
                continue
            playlist = refreshed_playlist
            media_url = refreshed.final_url

        if not playlist.segments:
            continue

        for segment in reversed(playlist.segments[-_SEGMENTS_TO_TRY:]):
            last_segment_url = segment.url
            try:
                result = fetcher(segment.url, headers, _MAX_SEGMENT_BYTES, "bytes=0-4095")
            except (OSError, URLError, TimeoutError):
                continue
            last_status = result.status
            if result.status not in {200, 206}:
                continue

            decoded = _decode_content(result.body, result.headers)
            last_format = detect_media_format(decoded)
            if last_format in {"mpeg-ts", "fmp4"}:
                display = "MPEG-TS" if last_format == "mpeg-ts" else "fMP4/CMAF"
                return StreamValidationResult(
                    True, "complete",
                    f"Playlist válida y segmento reproducible detectado como {display}.",
                    root_result.final_url, media_url, result.final_url, result.status,
                    include_sensitive_headers, last_format, True,
                )

    if last_status == 404:
        message = (
            "Los segmentos recientes respondieron HTTP 404 incluso después de refrescar la playlist. "
            "El token puede haber caducado o el servidor elimina los segmentos demasiado rápido."
        )
    elif last_format:
        labels = {"json": "JSON real", "html": "HTML", "hls-playlist": "otra playlist HLS",
                  "unknown-binary": "binario desconocido", "empty": "contenido vacío"}
        message = f"Los segmentos son accesibles, pero el formato detectado es {labels.get(last_format, last_format)}."
    elif last_status is not None:
        message = f"Ninguno de los segmentos recientes fue accesible. Último HTTP: {last_status}."
    else:
        message = "No se pudo obtener ningún segmento reciente de la playlist."

    return StreamValidationResult(False, "segment", message, root_result.final_url, media_url,
                                  last_segment_url, last_status, include_sensitive_headers,
                                  last_format, False)
