"""Test de integración: la acción de menú aplica el preset de ads a la
política de captura y la persiste en QSettings."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from streaminspector import __version__
from streaminspector.ad_presets import COMMON_AD_DOMAINS
from streaminspector.core.events import EventBus, StatusMessage
from streaminspector.gui.deep_search_window import DeepSearchWindow
from streaminspector.storage import StorageService


@pytest.fixture(autouse=True)
def _clean_qsettings() -> None:
    """Limpia TODAS las claves de QSettings entre tests para que la
    política de captura y los flags de onboarding no se filtren entre
    tests."""
    settings = QSettings("StreamInspector", "StreamInspector")
    settings.clear()
    settings.setValue(f"onboarding/{__version__}", True)
    settings.setValue("startup_notice/0.1.0a19", True)
    yield
    settings.clear()


@pytest.fixture
def window(qtbot, tmp_path: Path):
    _ = QApplication.instance() or QApplication([])
    bus = EventBus()
    storage = StorageService(bus, tmp_path / "test.sqlite3")
    win = DeepSearchWindow(bus, storage, initial_flows=[])
    qtbot.addWidget(win)
    yield win
    storage.close()


def test_load_ad_preset_adds_domains_to_empty_policy(window) -> None:
    captured: list[StatusMessage] = []
    window._event_bus.subscribe(StatusMessage, lambda e: captured.append(e))

    assert window._capture_policy.excluded_domains == ()
    window._load_ad_preset()

    assert set(window._capture_policy.excluded_domains) == set(COMMON_AD_DOMAINS)
    # Persiste en QSettings para la siguiente sesión
    settings = QSettings("StreamInspector", "StreamInspector")
    saved = settings.value("capture/excluded_domains", "")
    assert all(d in saved for d in COMMON_AD_DOMAINS)


def test_load_ad_preset_is_additive(window) -> None:
    """Si el usuario ya tenía dominios propios, se preservan al añadir el preset."""
    window._capture_policy.excluded_domains = ("mis-dominios.com",)
    window._capture_settings.setValue(
        "capture/excluded_domains", "mis-dominios.com"
    )
    window._load_ad_preset()

    merged = window._capture_policy.excluded_domains
    # Los del usuario primero
    assert merged[0] == "mis-dominios.com"
    # Y luego el preset completo
    assert set(merged[1:]) == set(COMMON_AD_DOMAINS)


def test_load_ad_preset_no_op_when_already_loaded(window) -> None:
    """Si el usuario ya cargó el preset, el segundo click informa en vez de duplicar."""
    window._load_ad_preset()
    captured: list[StatusMessage] = []
    window._event_bus.subscribe(StatusMessage, lambda e: captured.append(e))

    window._load_ad_preset()  # segunda vez

    # El segundo click NO añade nada nuevo
    assert len(window._capture_policy.excluded_domains) == len(COMMON_AD_DOMAINS)
    # Y avisa al usuario
    assert any("ya estaba incluida" in e.message for e in captured)


def test_ad_preset_action_is_in_capture_menu(window) -> None:
    """La acción aparece en el menú Captura con el texto correcto."""
    from PySide6.QtWidgets import QMenu

    capture_menus = [
        m for m in window.menuBar().findChildren(QMenu) if m.title() == "Captura"
    ]
    assert len(capture_menus) == 1
    menu = capture_menus[0]
    labels = [a.text() for a in menu.actions() if a.text()]
    assert "Cargar lista de exclusión de ads (preset)…" in labels
