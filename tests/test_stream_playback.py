from streaminspector.stream_playback import (
    PlaybackTool,
    build_ffplay_args,
    build_player_args,
    build_recording_args,
)


HEADERS = (
    ("User-Agent", "Captured/1.0"),
    ("Referer", "https://example.com/page"),
    ("Origin", "https://example.com"),
    ("Cookie", "session=secret"),
    ("Authorization", "Bearer secret"),
)


def test_ffplay_reuses_safe_headers_without_secrets() -> None:
    args = build_ffplay_args("ffplay", "https://cdn.example/live.m3u8", HEADERS)
    joined = " ".join(args)
    assert "Captured/1.0" in joined
    assert "Referer: https://example.com/page" in joined
    assert "Origin: https://example.com" in joined
    assert "session=secret" not in joined
    assert "Bearer secret" not in joined


def test_ffplay_includes_secrets_only_with_opt_in() -> None:
    args = build_ffplay_args(
        "ffplay",
        "https://cdn.example/live.m3u8",
        HEADERS,
        include_sensitive_headers=True,
    )
    joined = " ".join(args)
    assert "Cookie: session=secret" in joined
    assert "Authorization: Bearer secret" in joined


def test_recording_uses_copy_and_output_path() -> None:
    args = build_recording_args(
        "ffmpeg",
        "https://cdn.example/live.m3u8",
        "capture.ts",
        HEADERS,
    )
    assert args[-3:] == ["-c", "copy", "capture.ts"]
    assert "session=secret" not in " ".join(args)


def test_player_dispatches_to_mpv() -> None:
    args = build_player_args(
        PlaybackTool("mpv", "mpv"),
        "https://cdn.example/live.m3u8",
        HEADERS,
    )
    assert args[0] == "mpv"
    assert any(arg.startswith("--http-header-fields=") for arg in args)
    assert args[-1] == "https://cdn.example/live.m3u8"


def test_no_shell_metacharacter_interpretation_is_needed() -> None:
    url = 'https://cdn.example/live.m3u8?token=a&x="quoted"'
    args = build_ffplay_args("ffplay", url, HEADERS)
    assert args[-1] == url
