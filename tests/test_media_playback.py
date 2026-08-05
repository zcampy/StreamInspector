from __future__ import annotations

from streaminspector.media_playback import (
    build_ffplay_command,
    build_record_command,
)


def test_ffplay_uses_safe_argv_and_non_sensitive_headers() -> None:
    headers = (
        ("User-Agent", "TestAgent/1.0"),
        ("Referer", "https://site.example/watch"),
        ("Origin", "https://site.example"),
        ("Cookie", "session=secret"),
    )
    command = build_ffplay_command(
        "https://cdn.example/live.m3u8?token=abc",
        headers,
        executable="C:/ffmpeg/bin/ffplay.exe",
    )

    assert command.executable.endswith("ffplay.exe")
    assert "-user_agent" in command.arguments
    assert "TestAgent/1.0" in command.arguments
    joined = "\n".join(command.arguments)
    assert "Referer: https://site.example/watch" in joined
    assert "Origin: https://site.example" in joined
    assert "session=secret" not in joined
    assert command.arguments[-2:] == (
        "-i",
        "https://cdn.example/live.m3u8?token=abc",
    )


def test_ffplay_allows_verified_json_segments_and_relaxes_format_match() -> None:
    command = build_ffplay_command("https://cdn.example/live.m3u8")
    option_index = command.arguments.index("-allowed_segment_extensions")
    allowed = command.arguments[option_index + 1].split(",")
    picky_index = command.arguments.index("-extension_picky")

    assert "json" in allowed
    assert "ts" in allowed
    assert "m4s" in allowed
    assert "ALL" not in allowed
    assert command.arguments[picky_index + 1] == "0"


def test_ffplay_can_include_cookie_only_with_explicit_opt_in() -> None:
    command = build_ffplay_command(
        "https://cdn.example/live.m3u8",
        (("Cookie", "session=secret"),),
        include_sensitive_headers=True,
    )
    assert "Cookie: session=secret" in "\n".join(command.arguments)


def test_record_command_copies_stream_without_reencoding() -> None:
    command = build_record_command(
        "https://cdn.example/live.m3u8",
        "capture.ts",
        executable="ffmpeg",
    )
    assert command.arguments[-3:] == ("-c", "copy", "capture.ts")
    assert command.arguments[-1] == "capture.ts"
