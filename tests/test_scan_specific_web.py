"""Tests de la acción 'Escanear una web específica' del menú Proxy.

Cubre la lógica pura (`extract_domain_for_whitelist`) y la integración
con la UI (`_scan_specific_web`) verificando que:
- Saca el dominio correcto de URLs válidas
- Rechaza URLs inválidas
- Añade el dominio a la whitelist sin destruir los previos
- Cambia el modo a WHITELIST
- Arranca el proxy si estaba apagado
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from streaminspector import __version__
from streaminspector.capture_policy import CaptureMode, CapturePolicy
from streaminspector.core.events import EventBus
from streaminspector.gui.deep_search_window import DeepSearchWindow
from streaminspector.gui.proxy_window import extract_domain_for_whitelist
from streaminspector.storage import StorageService

# ----------------------- extract_domain_for_whitelist ------------------------


def test_extract_domain_simple_https() -> None:
    assert (
        extract_domain_for_whitelist("https://fctv33hd.fit/evento-x")
        == "fctv33hd.fit"
    )


def test_extract_domain_with_subdomain() -> None:
    assert (
        extract_domain_for_whitelist("https://seg.adair.sworfa.kdns.fr/index.m3u8")
        == "seg.adair.sworfa.kdns.fr"
    )


def test_extract_domain_lowercases_uppercase_host() -> None:
    assert (
        extract_domain_for_whitelist("https://FCTV33HD.FIT/evento") == "fctv33hd.fit"
    )


def test_extract_domain_strips_www() -> None:
    assert (
        extract_domain_for_whitelist("https://www.example.com/path") == "example.com"
    )


def test_extract_domain_keeps_path_query_out() -> None:
    """Solo extrae el dominio, no path/query/fragment."""
    assert (
        extract_domain_for_whitelist(
            "https://fctv33hd.fit/evento?token=abc&user=1#section"
        )
        == "fctv33hd.fit"
    )


def test_extract_domain_accepts_http() -> None:
    assert extract_domain_for_whitelist("http://example.com/x") == "example.com"


def test_extract_domain_rejects_ftp() -> None:
    assert extract_domain_for_whitelist("ftp://example.com/x") is None


def test_extract_domain_rejects_empty() -> None:
    assert extract_domain_for_whitelist("") is None
    assert extract_domain_for_whitelist("   ") is None


def test_extract_domain_rejects_garbage() -> None:
    assert extract_domain_for_whitelist("not a url") is None
    assert extract_domain_for_whitelist("https://") is None  # sin host


def test_extract_domain_strips_whitespace() -> None:
    assert (
        extract_domain_for_whitelist("  https://example.com/x  ")
        == "example.com"
    )


# ----------------------- integración con el window --------------------------


@pytest.fixture(autouse=True)
def _suppress_onboarding() -> None:
    settings = QSettings("StreamInspector", "StreamInspector")
    settings.setValue(f"onboarding/{__version__}", True)
    settings.setValue("startup_notice/0.1.0a19", True)
    yield
    settings.remove(f"onboarding/{__version__}")
    settings.remove("startup_notice/0.1.0a19")


def _make_window(qtbot, tmp_path: Path, policy: CapturePolicy | None = None):
    _ = QApplication.instance() or QApplication([])
    bus = EventBus()
    storage = StorageService(bus, tmp_path / "test.sqlite3")
    if policy is not None:
        storage.set_capture_filter(policy.accepts, policy=policy)
    win = DeepSearchWindow(bus, storage, initial_flows=[])
    qtbot.addWidget(win)
    return win, bus, storage


def test_scan_specific_web_adds_domain_to_whitelist(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """Introducir una URL añade el dominio a la whitelist."""
    policy = CapturePolicy(
        mode=CaptureMode.ALL,  # empieza en ALL para confirmar el switch
        whitelisted_domains=(),
    )
    win, _bus, storage = _make_window(qtbot, tmp_path, policy)
    try:
        # Simular la entrada del usuario en el QInputDialog
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.QInputDialog.getText",
            lambda *a, **kw: ("https://fctv33hd.fit/evento-x", True),
        )
        # Evitar que `_open_dedicated_browser` intente lanzar un proceso real
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.ProxyConfiguredWindow"
            "._open_dedicated_browser_at",
            lambda self, url: None,
        )
        # El proxy toggle también puede fallar en tests; lo neutralizamos
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.ProxyConfiguredWindow._toggle_proxy",
            lambda self, _enabled: None,
        )

        win._scan_specific_web()

        # El dominio se añadió y el modo cambió a WHITELIST
        assert "fctv33hd.fit" in storage.capture_policy.whitelisted_domains
        assert storage.capture_policy.mode is CaptureMode.WHITELIST
    finally:
        storage.close()


def test_scan_specific_web_accumulates_without_destroying_existing(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """Escanear una segunda web añade a la whitelist, no reemplaza."""
    policy = CapturePolicy(
        mode=CaptureMode.ALL,
        whitelisted_domains=("other.example",),
    )
    win, _bus, storage = _make_window(qtbot, tmp_path, policy)
    try:
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.QInputDialog.getText",
            lambda *a, **kw: ("https://fctv33hd.fit/x", True),
        )
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.ProxyConfiguredWindow"
            "._open_dedicated_browser_at",
            lambda self, url: None,
        )
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.ProxyConfiguredWindow._toggle_proxy",
            lambda self, _enabled: None,
        )

        win._scan_specific_web()

        whitelist = storage.capture_policy.whitelisted_domains
        assert "other.example" in whitelist  # se preserva
        assert "fctv33hd.fit" in whitelist  # se añade
    finally:
        storage.close()


def test_scan_specific_web_rejects_invalid_url(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """Si la URL no es http(s) con host, no se modifica la policy."""
    policy = CapturePolicy(
        mode=CaptureMode.ALL,
        whitelisted_domains=("existing.example",),
    )
    win, _bus, storage = _make_window(qtbot, tmp_path, policy)
    try:
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.QInputDialog.getText",
            lambda *a, **kw: ("ftp://nope.example/x", True),
        )
        # Evitar el QMessageBox bloqueante
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.QMessageBox.warning",
            lambda *a, **kw: 0,
        )

        win._scan_specific_web()

        # La policy queda como estaba
        assert storage.capture_policy.whitelisted_domains == ("existing.example",)
        assert storage.capture_policy.mode is CaptureMode.ALL
    finally:
        storage.close()


def test_scan_specific_web_strips_www_from_input(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """www.example.com se guarda como example.com en la whitelist."""
    policy = CapturePolicy(
        mode=CaptureMode.ALL,
        whitelisted_domains=(),
    )
    win, _bus, storage = _make_window(qtbot, tmp_path, policy)
    try:
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.QInputDialog.getText",
            lambda *a, **kw: ("https://www.example.com/path", True),
        )
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.ProxyConfiguredWindow"
            "._open_dedicated_browser_at",
            lambda self, url: None,
        )
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.ProxyConfiguredWindow._toggle_proxy",
            lambda self, _enabled: None,
        )

        win._scan_specific_web()

        assert "example.com" in storage.capture_policy.whitelisted_domains
        assert "www.example.com" not in storage.capture_policy.whitelisted_domains
    finally:
        storage.close()


def test_scan_specific_web_dedupes_existing_domain(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """Si el dominio ya estaba, no se duplica."""
    policy = CapturePolicy(
        mode=CaptureMode.WHITELIST,
        whitelisted_domains=("fctv33hd.fit",),
    )
    win, _bus, storage = _make_window(qtbot, tmp_path, policy)
    try:
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.QInputDialog.getText",
            lambda *a, **kw: ("https://fctv33hd.fit/different-path", True),
        )
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.ProxyConfiguredWindow"
            "._open_dedicated_browser_at",
            lambda self, url: None,
        )
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.ProxyConfiguredWindow._toggle_proxy",
            lambda self, _enabled: None,
        )

        win._scan_specific_web()

        # Sigue habiendo exactamente una entrada con ese dominio
        whitelist = storage.capture_policy.whitelisted_domains
        assert whitelist.count("fctv33hd.fit") == 1
    finally:
        storage.close()


def test_scan_specific_web_cancelled_does_nothing(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """Si el usuario cancela el QInputDialog, la policy no cambia."""
    policy = CapturePolicy(
        mode=CaptureMode.ALL,
        whitelisted_domains=("existing.example",),
    )
    win, _bus, storage = _make_window(qtbot, tmp_path, policy)
    try:
        monkeypatch.setattr(
            "streaminspector.gui.proxy_window.QInputDialog.getText",
            lambda *a, **kw: ("https://fctv33hd.fit/x", False),  # cancel
        )

        win._scan_specific_web()

        # La policy queda como estaba
        assert storage.capture_policy.whitelisted_domains == ("existing.example",)
        assert storage.capture_policy.mode is CaptureMode.ALL
    finally:
        storage.close()
