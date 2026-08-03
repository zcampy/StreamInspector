from streaminspector.gui.main_window import _format_bytes


def test_format_bytes() -> None:
    assert _format_bytes(0) == "0 B"
    assert _format_bytes(1023) == "1023 B"
    assert _format_bytes(1024) == "1.0 KB"
    assert _format_bytes(1024 * 1024) == "1.0 MB"
