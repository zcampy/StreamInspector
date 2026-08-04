"""Detección, análisis y generación de comandos para streams multimedia."""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

VIDEO_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "application/dash+xml",
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "video/x-matroska",
        "video/x-msvideo",
        "video/x-flv",
        "video/3gpp",
        "video/ogg",
        "video/mp2t",
        "video/mp1s",
        "audio/mpeg",
        "audio/aac",
        "audio/ogg",
        "audio/x-m4a",
        "audio/mp4",
    }
)

VIDEO_PATH_HINTS: tuple[str, ...] = (
    ".m3u8",
    ".m3u",
    ".mp4",
    ".webm",
    ".mov",
    ".ts",
    ".m4s",
    ".mpd",
    ".ism",
    ".ism/manifest",
    ".f4m",
    ".flv",
    ".3gp",
    ".mkv",
)


def is_video_content_type(content_type: str) -> bool:
    if not content_type:
        return False
    mime = content_type.split(";", 1)[0].strip().lower()
    return mime in VIDEO_CONTENT_TYPES or mime.startswith(("video/", "audio/"))


def _url_path(url: str) -> str:
    try:
        return urlsplit(url).path.lower()
    except ValueError:
        return url.lower()


def is_video_url(url: str, content_type: str = "") -> bool:
    if is_video_content_type(content_type):
        return True
    path = _url_path(url)
    return any(hint in path for hint in VIDEO_PATH_HINTS)


def is_m3u8_response(content_type: str, body: bytes) -> bool:
    if is_video_content_type(content_type) and "mpegurl" in content_type.lower():
        return True
    if not body:
        return False
    try:
        head = body[:64].lstrip().decode("utf-8")
    except UnicodeDecodeError:
        return False
    return head.startswith("#EXTM3U")


@dataclass(frozen=True, slots=True)
class M3u8Segment:
    url: str
    duration: float | None


@dataclass(frozen=True, slots=True)
class M3u8Variant:
    url: str
    bandwidth: int | None = None
    resolution: str | None = None
    codecs: str | None = None
    frame_rate: float | None = None


@dataclass(frozen=True, slots=True)
class M3u8Playlist:
    version: int | None = None
    target_duration: int | None = None
    is_master: bool = False
    is_live: bool | None = None
    segments: tuple[M3u8Segment, ...] = field(default_factory=tuple)
    variants: tuple[M3u8Variant, ...] = field(default_factory=tuple)
    raw_lines: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_duration(self) -> float:
        return sum(segment.duration or 0.0 for segment in self.segments)

    @property
    def segment_count(self) -> int:
        return len(self.segments)


_EXTINF_RE = re.compile(r"#EXTINF:\s*([0-9.]+)")
_ATTRIBUTE_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _parse_stream_attributes(line: str) -> dict[str, str]:
    _, _, raw = line.partition(":")
    result: dict[str, str] = {}
    for key, value in _ATTRIBUTE_RE.findall(raw):
        result[key] = value.strip().strip('"')
    return result


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    with contextlib.suppress(ValueError):
        return int(value)
    return None


def _optional_float(value: str | None) -> float | None:
    if not value:
        return None
    with contextlib.suppress(ValueError):
        return float(value)
    return None


def parse_m3u8(text: str, base_url: str = "") -> M3u8Playlist:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    version: int | None = None
    target_duration: int | None = None
    has_endlist = False
    segments: list[M3u8Segment] = []
    variants: list[M3u8Variant] = []
    pending_duration: float | None = None
    pending_variant: dict[str, str] | None = None

    for line in lines:
        if line.startswith("#EXT-X-VERSION:"):
            with contextlib.suppress(ValueError):
                version = int(line.split(":", 1)[1].strip())
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            with contextlib.suppress(ValueError):
                target_duration = int(line.split(":", 1)[1].strip())
        elif line.startswith("#EXT-X-STREAM-INF"):
            pending_variant = _parse_stream_attributes(line)
        elif line.startswith("#EXTINF:"):
            match = _EXTINF_RE.match(line)
            pending_duration = float(match.group(1)) if match else None
        elif line.startswith("#EXT-X-ENDLIST"):
            has_endlist = True
        elif not line.startswith("#"):
            resolved = urljoin(base_url, line) if base_url else line
            if pending_variant is not None:
                variants.append(
                    M3u8Variant(
                        url=resolved,
                        bandwidth=_optional_int(pending_variant.get("BANDWIDTH")),
                        resolution=pending_variant.get("RESOLUTION"),
                        codecs=pending_variant.get("CODECS"),
                        frame_rate=_optional_float(pending_variant.get("FRAME-RATE")),
                    )
                )
                pending_variant = None
            else:
                segments.append(M3u8Segment(url=resolved, duration=pending_duration))
                pending_duration = None

    is_master = bool(variants)
    is_live: bool | None = None if is_master else not has_endlist
    return M3u8Playlist(
        version=version,
        target_duration=target_duration,
        is_master=is_master,
        is_live=is_live,
        segments=tuple(segments),
        variants=tuple(variants),
        raw_lines=tuple(lines),
    )


_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _extract_command_headers(
    request_headers: tuple[tuple[str, str], ...] | None,
    *,
    include_sensitive_headers: bool,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    referer = None
    user_agent = None
    origin = None
    cookie = None
    authorization = None
    for name, value in request_headers or ():
        if not name or not value:
            continue
        lower = name.lower()
        if lower == "referer" and referer is None:
            referer = value
        elif lower == "user-agent" and user_agent is None:
            user_agent = value
        elif lower == "origin" and origin is None:
            origin = value
        elif include_sensitive_headers and lower == "cookie" and cookie is None:
            cookie = value
        elif (
            include_sensitive_headers
            and lower == "authorization"
            and authorization is None
        ):
            authorization = value
    return referer, user_agent, origin, cookie, authorization


def _escape_command_value(value: str) -> str:
    return value.replace('"', '\\"')


def _format_ffmpeg_prefix(
    url: str,
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
) -> str:
    referer, user_agent, origin, cookie, authorization = _extract_command_headers(
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )
    parts = [
        "ffmpeg -hide_banner -loglevel error",
        f'-user_agent "{_escape_command_value(user_agent or _DEFAULT_USER_AGENT)}"',
    ]
    extra_headers: list[str] = []
    if referer:
        extra_headers.append(f"Referer: {referer}")
    if origin:
        extra_headers.append(f"Origin: {origin}")
    if cookie:
        extra_headers.append(f"Cookie: {cookie}")
    if authorization:
        extra_headers.append(f"Authorization: {authorization}")
    if extra_headers:
        joined = "\\r\\n".join(_escape_command_value(item) for item in extra_headers)
        parts.append(f'-headers "{joined}\\r\\n"')
    parts.append(f'-i "{_escape_command_value(url)}"')
    return " ".join(parts)


def build_ffmpeg_command(
    url: str,
    content_type: str = "",
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
) -> str:
    """Genera un comando ffmpeg; cookies/auth solo se incluyen con opt-in."""
    prefix = _format_ffmpeg_prefix(
        url,
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )
    lower_ct = content_type.lower() if content_type else ""
    path = _url_path(url)

    if "mpegurl" in lower_ct or path.endswith((".m3u8", ".m3u")):
        return f"{prefix} -c copy -bsf:a aac_adtstoasc output.ts"
    if "dash" in lower_ct or path.endswith(".mpd"):
        return f"{prefix} -c copy -bsf:a aac_adtstoasc output.mp4"
    if "mp4" in lower_ct or path.endswith(
        (".mp4", ".m4s", ".mov", ".ism", ".ism/manifest", ".f4m")
    ):
        return f"{prefix} -c copy output.mp4"
    if "webm" in lower_ct or path.endswith(".webm"):
        return f"{prefix} -c copy output.webm"
    if "matroska" in lower_ct or path.endswith(".mkv"):
        return f"{prefix} -c copy output.mkv"
    if "flv" in lower_ct or path.endswith(".flv"):
        return f"{prefix} -c copy output.flv"
    if "3gpp" in lower_ct or path.endswith(".3gp"):
        return f"{prefix} -c copy output.3gp"
    if path.endswith(".ts"):
        return f"{prefix} -c copy output.ts"
    return f"{prefix} -c copy output.mp4"
