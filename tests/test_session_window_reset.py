"""Regression test for the HAR/session view lock-in bug.

After importing a HAR (or opening a historical session), `_visible_session_id`
is set to a sentinel and `SessionMainWindow._on_flow_captured` filters out new
flows. Previously the only way to leave that mode was to restart the app.

The fix: `SessionMainWindow._clear_view` resets the flag to `None`, and a new
"Volver a la sesión actual" action in the Importar menu does the same.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.gui.deep_search_window import DeepSearchWindow
from streaminspector.storage import StorageService


def _flow(flow_id: str, host: str = "example.com") -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id=flow_id,
        method="GET",
        scheme="https",
        host=host,
        port=443,
        path="/",
        url=f"https://{host}/",
        http_version="HTTP/2",
        status_code=200,
        reason="OK",
        content_type="application/json",
        request_body=b"",
        response_body=b"{}",
        response_size=2,
    )


def _build_window(tmp_path: Path) -> tuple[DeepSearchWindow, EventBus, StorageService]:
    _ = QApplication.instance() or QApplication([])
    bus = EventBus()
    storage = StorageService(bus, tmp_path / "test.sqlite3")
    win = DeepSearchWindow(bus, storage, initial_flows=[])
    return win, bus, storage


def test_har_view_resets_after_return_to_live(tmp_path: Path) -> None:
    win, bus, storage = _build_window(tmp_path)
    try:
        # Simulate importing a HAR: clears view and sets sentinel.
        win._import_har = lambda: None  # avoid dialog; just emulate the state change
        win._clear_view()
        win._visible_session_id = -1
        assert win._visible_session_id == -1

        # User clicks "Volver a la sesión actual".
        win._return_to_live_session()

        # The flag must be back to None so new flows are shown again.
        assert win._visible_session_id is None
    finally:
        storage.close()


def test_clear_view_resets_visible_session_id(tmp_path: Path) -> None:
    win, _bus, storage = _build_window(tmp_path)
    try:
        win._visible_session_id = 999
        win._clear_view()
        assert win._visible_session_id is None
    finally:
        storage.close()


def test_clear_view_resets_after_har_sentinel(tmp_path: Path) -> None:
    """`Limpiar vista` debe sacar al usuario del modo HAR, no requerir un reinicio."""
    win, _bus, storage = _build_window(tmp_path)
    try:
        win._visible_session_id = -1  # sentinel usado por Importar HAR
        win._clear_view()
        assert win._visible_session_id is None
    finally:
        storage.close()
