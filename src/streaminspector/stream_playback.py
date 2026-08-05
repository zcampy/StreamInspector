"""Lanzamiento seguro de reproductores y grabación de streams autorizados."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class PlaybackTool:
    name: str
    executable: str


def _header_values(
    request_headers: tuple[tuple[str, str], ...] | None,
    *,
    include_sensitive_headers: bool,
) -> dict[str, str]:
    allowed = {"user-agent", "referer", "origin"}
    if include_sensitive_headers:
        allowed.update({"cookie", "authorization"})
    values: dict[str, str] = {}
    for name, value in request_headers or ():
        lower = name.lower()
        if lower in allowed and value and lower not in values:
            values[lower] = value
    values.setdefault("user-agent", _DEFAULT_USER_AGENT)
    return values


def find_playback_tool() -> PlaybackTool | None:
    """Prefiere ffplay, después mpv y finalmente VLC."""
    for name, candidates in (
        ("ffplay", ("ffplay", "ffplay.exe")),
        ("mpv", ("mpv", "mpv.exe")),
        ("VLC", ("vlc", "vlc.exe")),
    ):
        for candidate in candidates:
            executable = shutil.which(candidate)
            if executable:
                return PlaybackTool(name=name, executable=executable)
    return None


def find_ffmpeg() -> str | None:
    for candidate in ("ffmpeg", "ffmpeg.exe"):
        executable = shutil.which(candidate)
        if executable:
            return executable
    return None


def build_ffplay_args(
    executable: str,
    url: str,
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
) -> list[str]:
    values = _header_values(
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )
    args = [
        executable,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-user_agent",
        values["user-agent"],
    ]
    header_lines = []
    for key, label in (
        ("referer", "Referer"),
        ("origin", "Origin"),
        ("cookie", "Cookie"),
        ("authorization", "Authorization"),
    ):
        if key in values:
            header_lines.append(f"{label}: {values[key]}")
    if header_lines:
        args.extend(["-headers", "\r\n".join(header_lines) + "\r\n"])
    args.extend(["-i", url])
    return args


def build_mpv_args(
    executable: str,
    url: str,
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
) -> list[str]:
    values = _header_values(
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )
    args = [executable, f"--user-agent={values['user-agent']}"]
    fields = []
    for key, label in (
        ("referer", "Referer"),
        ("origin", "Origin"),
        ("cookie", "Cookie"),
        ("authorization", "Authorization"),
    ):
        if key in values:
            fields.append(f"{label}: {values[key]}")
    if fields:
        args.append("--http-header-fields=" + ",".join(fields))
    args.extend(["--cache=yes", "--demuxer-lavf-o=fflags=+nobuffer", url])
    return args


def build_vlc_args(
    executable: str,
    url: str,
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
) -> list[str]:
    values = _header_values(
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )
    args = [executable, "--network-caching=1000"]
    if values.get("user-agent"):
        args.append(f"--http-user-agent={values['user-agent']}")
    if values.get("referer"):
        args.append(f"--http-referrer={values['referer']}")
    # VLC no ofrece una opción CLI uniforme para Origin/Cookie/Authorization.
    args.append(url)
    return args


def build_player_args(
    tool: PlaybackTool,
    url: str,
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
) -> list[str]:
    if tool.name == "ffplay":
        return build_ffplay_args(
            tool.executable,
            url,
            request_headers,
            include_sensitive_headers=include_sensitive_headers,
        )
    if tool.name == "mpv":
        return build_mpv_args(
            tool.executable,
            url,
            request_headers,
            include_sensitive_headers=include_sensitive_headers,
        )
    return build_vlc_args(
        tool.executable,
        url,
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )


def build_recording_args(
    executable: str,
    url: str,
    output_path: str | Path,
    request_headers: tuple[tuple[str, str], ...] | None = None,
    *,
    include_sensitive_headers: bool = False,
) -> list[str]:
    values = _header_values(
        request_headers,
        include_sensitive_headers=include_sensitive_headers,
    )
    args = [
        executable,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-user_agent",
        values["user-agent"],
    ]
    header_lines = []
    for key, label in (
        ("referer", "Referer"),
        ("origin", "Origin"),
        ("cookie", "Cookie"),
        ("authorization", "Authorization"),
    ):
        if key in values:
            header_lines.append(f"{label}: {values[key]}")
    if header_lines:
        args.extend(["-headers", "\r\n".join(header_lines) + "\r\n"])
    args.extend(["-i", url, "-c", "copy", str(output_path)])
    return args


def launch_process(args: list[str]) -> subprocess.Popen[bytes]:
    """Lanza el reproductor/grabador sin pasar por un shell."""
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "shell": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    return subprocess.Popen(args, **kwargs)  # type: ignore[arg-type]
