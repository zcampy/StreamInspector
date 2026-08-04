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

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from streaminspector import __version__
from streaminspector.core.events import EventBus
from streaminspector.gui.deep_search_window import DeepSearchWindow
from streaminspector.storage import StorageService


@pytest.fixture(autouse=True)
def _suppress_onboarding() -> None:
    """Evita que el QTimer.singleShot del __init__ abra el OnboardingDialog,
    que en offscreen puede dejar timers pendientes y colgar el test runner."""
    settings = QSettings("StreamInspector", "StreamInspector")
    settings.setValue(f"onboarding/{__version__}", True)
    settings.setValue("startup_notice/0.1.0a19", True)
    yield
    settings.remove(f"onboarding/{__version__}")
    settings.remove("startup_notice/0.1.0a19")


@pytest.fixture
def window(tmp_path: Path):
    _ = QApplication.instance() or QApplication([])
    bus = EventBus()
    storage = StorageService(bus, tmp_path / "test.sqlite3")
    win = DeepSearchWindow(bus, storage, initial_flows=[])
    yield win
    storage.close()


def test_har_view_resets_after_return_to_live(window) -> None:
    window._clear_view()
    window._visible_session_id = -1
    assert window._visible_session_id == -1

    window._return_to_live_session()

    assert window._visible_session_id is None


def test_clear_view_resets_visible_session_id(window) -> None:
    window._visible_session_id = 999
    window._clear_view()
    assert window._visible_session_id is None


def test_clear_view_resets_after_har_sentinel(window) -> None:
    """`Limpiar vista` debe sacar al usuario del modo HAR, no requerir un reinicio."""
    window._visible_session_id = -1  # sentinel usado por Importar HAR
    window._clear_view()
    assert window._visible_session_id is None
