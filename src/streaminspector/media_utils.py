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


# User-Agent por defecto: un Chrome reciente. Sin esto muchos CDNs
# (Cloudflare, etc.) rechazan la request de ffmpeg porque su UA por
# defecto ("Lavf/...") es identificable como herramienta.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _extract_referer_and_ua(
    request_headers: tuple[tuple[str, str], ...] | None,
) -> tuple[str | None, str | None]:
    """Saca `Referer` y `User-Agent` de los headers del request original.

    Muchos streams protegidos validan el `Referer` y/o el `User-Agent`
    del cliente. Si los capturamos, el comando ffmpeg que copiamos puede
    reutilizarlos y la descarga funciona a la primera.
    """
    if not request_headers:
        return None, None
    referer: str | None = None
    user_agent: str | None = None
    for name, value in request_headers:
        if not name or not value:
            continue
        lower = name.lower()
        if lower == "referer" and referer is None:
            referer = value
        elif lower == "user-agent" and user_agent is None:
            user_agent = value
    return referer, user_agent


def _format_ffmpeg_prefix(
    url: str,
    request_headers: tuple[tuple[str, str], ...] | None = None,
) -> str:
    """Construye el prefijo del comando ffmpeg con headers y URL.

    Devuelve algo como:
        ffmpeg -hide_banner -loglevel error -user_agent "..." \\
            -headers "Referer: ...\r\n" -i "URL"
    """
    referer, user_agent = _extract_referer_and_ua(request_headers)
    ua = user_agent or _DEFAULT_USER_AGENT
    safe_ua = ua.replace('"', '\\"')
    parts = [
        "ffmpeg -hide_banner -loglevel error",
        f'-user_agent "{safe_ua}"',
    ]
    if referer:
        safe_referer = referer.replace('"', '\\"')
        parts.append(f'-headers "Referer: {safe_referer}\\r\\n"')
    parts.append(f'-i "{url.replace(chr(34), chr(92) + chr(34))}"')
    return " ".join(parts)


def build_ffmpeg_command(
    url: str,
    content_type: str = "",
    request_headers: tuple[tuple[str, str], ...] | None = None,
) -> str:
    """Genera un comando ffmpeg de UNA línea para capturar la URL.

    Para m3u8 (HLS) usamos `-c copy` con `.ts` como contenedor — el más
    universal. Para mp4/webm y similares, el contenedor se infiere del
    content-type o de la extensión de la URL.

    Si se pasan `request_headers` (los headers del request original
    capturado por el proxy), se extraen `Referer` y `User-Agent` y se
    incluyen en el comando. Esto es CRÍTICO para los streams protegidos
    de sitios como fctv33hd / adair.sworfa.kdns.fr que validan el
    Referer — sin él, ffmpeg recibe 403.

    Las comillas dobles en la URL y headers se escapan para que el comando
    resultante sea seguro de pegar en PowerShell o bash sin que rompa la
    sintaxis.

    Fallback: cuando ni el content-type ni la extensión aclaran el formato
    (típico en streams obfuscados: el servidor devuelve
    `application/octet-stream` y la URL acaba en `.doc` u otra extensión
    falsa), usamos `.mp4` porque es el contenedor más universal y lo abren
    todos los players. Antes caíamos a `output.bin`, que ningún player
    abre directamente.
    """
    prefix = _format_ffmpeg_prefix(url, request_headers)
    lower_ct = content_type.lower() if content_type else ""
    lower_url = url.lower()
    if "mpegurl" in lower_ct or lower_url.endswith((".m3u8", ".m3u")):
        return f"{prefix} -c copy -bsf:a aac_adtstoasc output.ts"
    if "dash" in lower_ct or lower_url.endswith(".mpd"):
        return f"{prefix} -c copy -bsf:a aac_adtstoasc output.mp4"
    if "mp4" in lower_ct or lower_url.endswith((
        ".mp4",
        ".m4s",   # segmento DASH
        ".mov",
        ".ism",
        ".ism/manifest",  # SmoothStreaming
        ".f4m",   # HDS Flash
    )):
        return f"{prefix} -c copy output.mp4"
    if "webm" in lower_ct or lower_url.endswith(".webm"):
        return f"{prefix} -c copy output.webm"
    if "matroska" in lower_ct or lower_url.endswith(".mkv"):
        return f"{prefix} -c copy output.mkv"
    if "flv" in lower_ct or lower_url.endswith(".flv"):
        return f"{prefix} -c copy output.flv"
    if "3gpp" in lower_ct or lower_url.endswith(".3gp"):
        return f"{prefix} -c copy output.3gp"
    if lower_url.endswith(".ts"):
        return f"{prefix} -c copy output.ts"
    # Fallback universal: cualquier stream que no pudimos clasificar va a
    # .mp4 (en lugar del antiguo .bin que ningún player abría).
    return f"{prefix} -c copy output.mp4"
