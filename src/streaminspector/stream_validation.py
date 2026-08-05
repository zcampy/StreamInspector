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


def _header_map(
    request_headers: tuple[tuple[str, str], ...] | None,
    *,
    include_sensitive_headers: bool,
) -> dict[str, str]:
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

    # MPEG-TS usa paquetes de 188 bytes cuyo primer byte es siempre 0x47.
    if body[0] == 0x47:
        if len(body) < 189 or body[188] == 0x47:
            return "mpeg-ts"

    # ISO Base Media File Format: MP4/fMP4/CMAF.
    if len(body) >= 8 and body[4:8] in {b"ftyp", b"styp", b"moof", b"moov"}:
        return "fmp4"
    for marker in (b"ftyp", b"styp", b"moof", b"moov"):
        if marker in body[:64]:
            return "fmp4"

    stripped = body.lstrip()
    if stripped.startswith((b"{", b"[")):
        return "json"
    if stripped.lower().startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "html"
    if stripped.startswith(b"#EXTM3U"):
        return "hls-playlist"
    return "unknown-binary"


def _fetch_http(
    url: str,
    headers: Mapping[str, str],
    max_bytes: int,
    byte_range: str | None,
) -> HttpFetchResult:
    request_headers = {name.title(): value for name, value in headers.items()}
    if byte_range:
        request_headers["Range"] = byte_range
    request = Request(url, headers=request_headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - URL capturada
            raw_headers = {name.lower(): value for name, value in response.headers.items()}
            return HttpFetchResult(
                status=int(response.status),
                final_url=response.geturl(),
                headers=raw_headers,
                body=response.read(max_bytes),
            )
    except HTTPError as exc:
        raw_headers = {name.lower(): value for name, value in exc.headers.items()}
        return HttpFetchResult(
            status=int(exc.code),
            final_url=exc.geturl(),
            headers=raw_headers,
            body=exc.read(max_bytes),
        )


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


def validate_reproducible_link(
    playlist_url: str,
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
    fetcher: Fetcher = _fetch_http,
) -> StreamValidationResult:
    """Comprueba playlist, mejor variante y formato real de un segmento."""
    if not _validate_http_url(playlist_url):
        return StreamValidationResult(
            ok=False,
            stage="url",
            message="La URL no utiliza HTTP o HTTPS.",
            playlist_url=playlist_url,
            used_sensitive_headers=include_sensitive_headers,
        )

    headers = _header_map(
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )
    try:
        root_result = fetcher(playlist_url, headers, _MAX_PLAYLIST_BYTES, None)
    except (OSError, URLError, TimeoutError) as exc:
        return StreamValidationResult(
            ok=False,
            stage="playlist",
            message=f"No se pudo conectar con la playlist: {exc}",
            playlist_url=playlist_url,
            used_sensitive_headers=include_sensitive_headers,
        )

    if root_result.status not in {200, 206}:
        return StreamValidationResult(
            ok=False,
            stage="playlist",
            message=f"La playlist respondió HTTP {root_result.status}.",
            playlist_url=playlist_url,
            status_code=root_result.status,
            used_sensitive_headers=include_sensitive_headers,
        )

    playlist = _playlist_from_result(root_result)
    if playlist is None:
        return StreamValidationResult(
            ok=False,
            stage="playlist",
            message="La respuesta no contiene una playlist HLS válida.",
            playlist_url=root_result.final_url,
            status_code=root_result.status,
            used_sensitive_headers=include_sensitive_headers,
        )

    media_url = root_result.final_url
    if playlist.is_master:
        variant = select_best_variant(playlist)
        if variant is None:
            return StreamValidationResult(
                ok=False,
                stage="variant",
                message="La playlist maestra no contiene variantes utilizables.",
                playlist_url=root_result.final_url,
                used_sensitive_headers=include_sensitive_headers,
            )
        media_url = variant.url
        try:
            media_result = fetcher(media_url, headers, _MAX_PLAYLIST_BYTES, None)
        except (OSError, URLError, TimeoutError) as exc:
            return StreamValidationResult(
                ok=False,
                stage="variant",
                message=f"No se pudo cargar la mejor variante: {exc}",
                playlist_url=root_result.final_url,
                media_playlist_url=media_url,
                used_sensitive_headers=include_sensitive_headers,
            )
        if media_result.status not in {200, 206}:
            return StreamValidationResult(
                ok=False,
                stage="variant",
                message=f"La mejor variante respondió HTTP {media_result.status}.",
                playlist_url=root_result.final_url,
                media_playlist_url=media_url,
                status_code=media_result.status,
                used_sensitive_headers=include_sensitive_headers,
            )
        playlist = _playlist_from_result(media_result)
        if playlist is None:
            return StreamValidationResult(
                ok=False,
                stage="variant",
                message="La mejor variante no contiene una playlist HLS válida.",
                playlist_url=root_result.final_url,
                media_playlist_url=media_result.final_url,
                used_sensitive_headers=include_sensitive_headers,
            )
        media_url = media_result.final_url

    if not playlist.segments:
        return StreamValidationResult(
            ok=False,
            stage="segment",
            message="La playlist no contiene segmentos comprobables.",
            playlist_url=root_result.final_url,
            media_playlist_url=media_url,
            used_sensitive_headers=include_sensitive_headers,
        )

    segment_url = playlist.segments[-1].url
    try:
        segment_result = fetcher(
            segment_url,
            headers,
            _MAX_SEGMENT_BYTES,
            "bytes=0-4095",
        )
    except (OSError, URLError, TimeoutError) as exc:
        return StreamValidationResult(
            ok=False,
            stage="segment",
            message=f"No se pudo cargar un segmento: {exc}",
            playlist_url=root_result.final_url,
            media_playlist_url=media_url,
            segment_url=segment_url,
            used_sensitive_headers=include_sensitive_headers,
        )

    if segment_result.status not in {200, 206}:
        return StreamValidationResult(
            ok=False,
            stage="segment",
            message=f"El segmento respondió HTTP {segment_result.status}.",
            playlist_url=root_result.final_url,
            media_playlist_url=media_url,
            segment_url=segment_url,
            status_code=segment_result.status,
            used_sensitive_headers=include_sensitive_headers,
        )

    decoded_segment = _decode_content(segment_result.body, segment_result.headers)
    media_format = detect_media_format(decoded_segment)
    if media_format == "empty":
        return StreamValidationResult(
            ok=False,
            stage="segment",
            message="El segmento respondió sin contenido.",
            playlist_url=root_result.final_url,
            media_playlist_url=media_url,
            segment_url=segment_result.final_url,
            status_code=segment_result.status,
            used_sensitive_headers=include_sensitive_headers,
            media_format=media_format,
        )

    playable = media_format in {"mpeg-ts", "fmp4"}
    if not playable:
        labels = {
            "json": "JSON real",
            "html": "HTML, probablemente una página de error",
            "hls-playlist": "otra playlist HLS",
            "unknown-binary": "binario desconocido",
        }
        label = labels.get(media_format, media_format)
        return StreamValidationResult(
            ok=False,
            stage="format",
            message=f"El segmento es accesible, pero su formato es {label}.",
            playlist_url=root_result.final_url,
            media_playlist_url=media_url,
            segment_url=segment_result.final_url,
            status_code=segment_result.status,
            used_sensitive_headers=include_sensitive_headers,
            media_format=media_format,
            playable=False,
        )

    display_format = "MPEG-TS" if media_format == "mpeg-ts" else "fMP4/CMAF"
    return StreamValidationResult(
        ok=True,
        stage="complete",
        message=f"Playlist válida y segmento reproducible detectado como {display_format}.",
        playlist_url=root_result.final_url,
        media_playlist_url=media_url,
        segment_url=segment_result.final_url,
        status_code=segment_result.status,
        used_sensitive_headers=include_sensitive_headers,
        media_format=media_format,
        playable=True,
    )
