"""Utilidades para detectar y manejar URLs de vídeo/audio en streams.

Pensado para cazar los `.m3u8`/`.mp4`/DASH que los streamers esconden en
su HTML/JS y que solo aparecen como una request más en la captura. Una vez
identificada la URL, `build_ffmpeg_command` la convierte en un comando
copiable para descargar el stream con ffmpeg.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

# Content-Types que identifican streams de vídeo o audio. La lista es
# deliberadamente laxa: si parece vídeo, lo marcamos.
VIDEO_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        # HLS (Apple HTTP Live Streaming)
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        # MPEG-DASH
        "application/dash+xml",
        # Progressive download
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "video/x-matroska",
        "video/x-msvideo",
        "video/x-flv",
        "video/3gpp",
        "video/ogg",
        # Segmentos sueltos (no es playlist pero sí vídeo)
        "video/mp2t",
        "video/mp1s",
        # Audio-only streams (algunos streamers los usan para radio/podcast)
        "audio/mpeg",
        "audio/aac",
        "audio/ogg",
        "audio/x-m4a",
        "audio/mp4",
    }
)

# Substrings en la URL que también indican contenido multimedia, por si el
# servidor no envía Content-Type correcto (passes HLS sin mimetype, etc.).
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
    """True si el Content-Type indica un stream de vídeo o audio."""
    if not content_type:
        return False
    mime = content_type.split(";", 1)[0].strip().lower()
    return mime in VIDEO_CONTENT_TYPES or mime.startswith(("video/", "audio/"))


def is_video_url(url: str, content_type: str = "") -> bool:
    """True si la URL o su Content-Type sugieren un stream multimedia."""
    if is_video_content_type(content_type):
        return True
    lower = url.lower()
    return any(hint in lower for hint in VIDEO_PATH_HINTS)


def is_m3u8_response(content_type: str, body: bytes) -> bool:
    """True si la respuesta es una playlist HLS (m3u8)."""
    if is_video_content_type(content_type) and "mpegurl" in content_type.lower():
        return True
    # Sin Content-Type fiable, miramos la firma del cuerpo.
    if not body:
        return False
    head = body[:64].lstrip().decode("utf-8", errors="replace")
    return head.startswith("#EXTM3U")


# ---------------------------------------------------------------- m3u8 parser


@dataclass(frozen=True, slots=True)
class M3u8Segment:
    """Un segmento de una playlist HLS."""

    url: str
    duration: float | None  # segundos; None si el #EXTINF no estaba


@dataclass(frozen=True, slots=True)
class M3u8Playlist:
    """Playlist HLS parseada.

    `segments` está en el orden en que aparecen en el fichero original.
    `total_duration` es la suma de las duraciones de los segmentos; si algún
    segmento no tenía #EXTINF, se cuenta como 0.
    """

    version: int | None = None
    target_duration: int | None = None
    is_master: bool = False  # contiene #EXT-X-STREAM-INF (master playlist)
    is_live: bool = False    # NO contiene #EXT-X-ENDLIST
    segments: tuple[M3u8Segment, ...] = field(default_factory=tuple)
    raw_lines: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_duration(self) -> float:
        return sum(s.duration or 0.0 for s in self.segments)

    @property
    def segment_count(self) -> int:
        return len(self.segments)


_EXTINF_RE = re.compile(r"#EXTINF:\s*([0-9.]+)")


def parse_m3u8(text: str, base_url: str = "") -> M3u8Playlist:
    """Parsea una playlist HLS (m3u8) y devuelve sus segmentos.

    Si se pasa `base_url`, los segmentos con URL relativa se resuelven contra
    ella (típicamente la URL del propio .m3u8).
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    version: int | None = None
    target_duration: int | None = None
    is_master = False
    is_live = True
    segments: list[M3u8Segment] = []
    pending_duration: float | None = None

    for line in lines:
        if line.startswith("#EXT-X-VERSION:"):
            with contextlib.suppress(ValueError):
                version = int(line.split(":", 1)[1].strip())
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            with contextlib.suppress(ValueError):
                target_duration = int(line.split(":", 1)[1].strip())
        elif line.startswith("#EXT-X-STREAM-INF"):
            is_master = True
            is_live = False  # master playlists son VOD por definición
        elif line.startswith("#EXTINF:"):
            match = _EXTINF_RE.match(line)
            pending_duration = float(match.group(1)) if match else None
        elif line.startswith("#EXT-X-ENDLIST"):
            is_live = False
        elif not line.startswith("#"):
            # Línea de URL. Si la anterior era #EXTINF, esa es su duración.
            url = urljoin(base_url, line) if base_url else line
            segments.append(M3u8Segment(url=url, duration=pending_duration))
            pending_duration = None

    return M3u8Playlist(
        version=version,
        target_duration=target_duration,
        is_master=is_master,
        is_live=is_live,
        segments=tuple(segments),
        raw_lines=tuple(lines),
    )


# ---------------------------------------------------------------- ffmpeg


def build_ffmpeg_command(url: str, content_type: str = "") -> str:
    """Genera un comando ffmpeg de UNA línea para capturar la URL.

    Para m3u8 (HLS) usamos `-c copy` con `.ts` como contenedor — el más
    universal. Para mp4/webm y similares, el contenedor se infiere del
    content-type o de la extensión de la URL.

    Las comillas dobles en la URL se escapan para que el comando resultante
    sea seguro de pegar en PowerShell o bash sin que rompa la sintaxis.
    """
    safe_url = url.replace('"', '\\"')
    lower_ct = content_type.lower() if content_type else ""
    if "mpegurl" in lower_ct or url.lower().endswith((".m3u8", ".m3u")):
        return (
            f'ffmpeg -hide_banner -loglevel error -i "{safe_url}" '
            f'-c copy -bsf:a aac_adtstoasc output.ts'
        )
    if "dash" in lower_ct or url.lower().endswith(".mpd"):
        return (
            f'ffmpeg -hide_banner -loglevel error -i "{safe_url}" '
            f'-c copy -bsf:a aac_adtstoasc output.mp4'
        )
    if "mp4" in lower_ct or url.lower().endswith(".mp4"):
        return f'ffmpeg -hide_banner -loglevel error -i "{safe_url}" -c copy output.mp4'
    if "webm" in lower_ct or url.lower().endswith(".webm"):
        return f'ffmpeg -hide_banner -loglevel error -i "{safe_url}" -c copy output.webm'
    if url.lower().endswith(".ts"):
        return f'ffmpeg -hide_banner -loglevel error -i "{safe_url}" -c copy output.ts'
    # Genérico
    return f'ffmpeg -hide_banner -loglevel error -i "{safe_url}" -c copy output.bin'
