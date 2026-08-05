"""Lanzamiento controlado de ffplay/ffmpeg para streams autorizados."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_HLS_SEGMENT_EXTENSIONS = (
    "json,3gp,aac,avi,ac3,eac3,flac,mkv,m3u8,m4a,m4s,m4v,mpg,mov,"
    "mp2,mp3,mp4,mpeg,mpegts,ogg,ogv,oga,ts,vob,vtt,wav,webvtt,"
    "cmfv,cmfa,ec3,fmp4"
)


@dataclass(frozen=True, slots=True)
class PlaybackCommand:
    executable: str
    arguments: tuple[str, ...]

    @property
    def argv(self) -> list[str]:
        return [self.executable, *self.arguments]


def _header_values(
    request_headers: tuple[tuple[str, str], ...] | None,
    *,
    include_sensitive_headers: bool,
) -> tuple[str, str]:
    user_agent = ""
    extra: list[str] = []
    allowed = {"referer", "origin"}
    if include_sensitive_headers:
        allowed.update({"cookie", "authorization"})
    for name, value in request_headers or ():
        lower = name.lower()
        if not value:
            continue
        if lower == "user-agent" and not user_agent:
            user_agent = value
        elif lower in allowed:
            canonical = "-".join(part.capitalize() for part in lower.split("-"))
            extra.append(f"{canonical}: {value}")
    return user_agent, "\r\n".join(extra) + ("\r\n" if extra else "")


def find_ffplay() -> str | None:
    return shutil.which("ffplay")


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _hls_http_compat_args() -> list[str]:
    """Adapta FFmpeg a HLS tokenizado que cambia de host y usa MIME/extensión falsa."""
    return [
        "-http_persistent",
        "0",
        "-http_multiple",
        "0",
        "-seg_max_retry",
        "3",
        "-allowed_segment_extensions",
        _ALLOWED_HLS_SEGMENT_EXTENSIONS,
        # La aplicación ya comprobó por firma que el segmento es MPEG-TS/fMP4.
        # FFmpeg, aun permitiendo .json, rechaza el desajuste extensión/formato
        # mientras extension_picky permanece activo.
        "-extension_picky",
        "0",
    ]


def build_ffplay_command(
    url: str,
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
    executable: str = "ffplay",
) -> PlaybackCommand:
    user_agent, headers = _header_values(
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )
    args: list[str] = [
        "-hide_banner",
        "-loglevel",
        "info",
        "-window_title",
        "StreamInspector - reproduccion HLS",
        *_hls_http_compat_args(),
    ]
    if user_agent:
        args.extend(["-user_agent", user_agent])
    if headers:
        args.extend(["-headers", headers])
    args.extend(["-i", url])
    return PlaybackCommand(executable=executable, arguments=tuple(args))


def build_record_command(
    url: str,
    output_path: str | Path,
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
    executable: str = "ffmpeg",
) -> PlaybackCommand:
    user_agent, headers = _header_values(
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )
    args: list[str] = [
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        *_hls_http_compat_args(),
    ]
    if user_agent:
        args.extend(["-user_agent", user_agent])
    if headers:
        args.extend(["-headers", headers])
    args.extend(["-i", url, "-c", "copy", str(output_path)])
    return PlaybackCommand(executable=executable, arguments=tuple(args))


def launch_command(command: PlaybackCommand) -> subprocess.Popen[bytes]:
    """Lanza sin shell para evitar interpretar tokens o caracteres de la URL."""
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if Path(command.executable).name.lower().startswith("ffplay"):
        creationflags |= getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        stdout = None
        stderr = None
    else:
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL
    return subprocess.Popen(  # noqa: S603 - argv controlado, sin shell
        command.argv,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        shell=False,
        creationflags=creationflags,
    )
