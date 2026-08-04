"""Tests del panel inferior `VideoLinksPanel` y su integración con MainWindow.

El panel es lo más cercano a "lo que el usuario vino a buscar" en la app:
mostrar SÓLO los enlaces a streams de vídeo/audio (m3u8, mp4, ts…) y
facilitar copiarlos como URL o como comando ffmpeg.

Cubrimos:
- Filtrado: solo aparecen flows de vídeo/audio
- Dedupe por URL (las playlists HLS en vivo se relisten cada pocos segundos)
- Estado de los 4 botones según selección
- Clasificación de la columna "Tipo" (m3u8, mp4, ts…)
- Botón "Limpiar panel" sin tocar la captura principal
- Acciones de copia (URL y ffmpeg) vía monkeypatch del clipboard
- Integración con `MainWindow` (los hooks en `_append_flow` / `_clear_view`)
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from streaminspector import __version__
from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.gui.deep_search_window import DeepSearchWindow
from streaminspector.gui.video_links_panel import VideoLinksPanel
from streaminspector.storage import StorageService


@pytest.fixture(autouse=True)
def _suppress_onboarding() -> None:
    settings = QSettings("StreamInspector", "StreamInspector")
    settings.setValue(f"onboarding/{__version__}", True)
    settings.setValue("startup_notice/0.1.0a19", True)
    yield
    settings.remove(f"onboarding/{__version__}")
    settings.remove("startup_notice/0.1.0a19")


def _flow(
    flow_id: str,
    *,
    url: str,
    method: str = "GET",
    host: str = "cdn.example",
    path: str = "/",
    status_code: int | None = 200,
    content_type: str = "",
    response_body: bytes = b"",
    request_body: bytes = b"",
) -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id=flow_id,
        method=method,
        scheme="https",
        host=host,
        port=443,
        path=path,
        url=url,
        http_version="HTTP/2",
        status_code=status_code,
        reason="OK" if status_code == 200 else "Error",
        content_type=content_type,
        request_headers=(),
        response_headers=(),
        request_body=request_body,
        response_body=response_body,
        request_size=len(request_body),
        response_size=len(response_body),
        duration_ms=10.0,
    )


# ---------------------------------------------------------------- helpers


def _make_panel(qtbot, flows: list[HttpFlowCaptured]) -> VideoLinksPanel:
    """Construye un panel con un flows_provider en memoria (no usa SQLite)."""
    state = {"flows": list(flows)}

    def provider() -> list[HttpFlowCaptured]:
        return state["flows"]

    panel = VideoLinksPanel(provider)
    qtbot.addWidget(panel)
    panel.refresh()
    return panel


# ---------------------------------------------------------------- filtros


def test_panel_only_shows_video_flows(qtbot) -> None:
    """Una mezcla de HTML, JSON y un .m3u8 debe acabar con 1 sola fila."""
    panel = _make_panel(
        qtbot,
        [
            _flow("html-1", url="https://example.com/page", content_type="text/html"),
            _flow(
                "json-1",
                url="https://api.example.com/data",
                content_type="application/json",
            ),
            _flow(
                "m3u8-1",
                url="https://cdn.example.com/playlist.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
        ],
    )

    assert panel.table.rowCount() == 1
    url_item = panel.table.item(0, 4)
    assert url_item is not None
    assert url_item.text() == "https://cdn.example.com/playlist.m3u8"
    assert panel.header_label.text() == "Streams de vídeo (1)"


def test_panel_detects_video_by_url_only(qtbot) -> None:
    """Si la URL termina en .mp4 sin content-type, sigue contando como vídeo."""
    panel = _make_panel(
        qtbot,
        [
            _flow(
                "mp4-1",
                url="https://cdn.example.com/seguro-es-video.mp4",
                content_type="application/octet-stream",
            ),
        ],
    )

    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 3).text() == "mp4"


def test_panel_detects_m3u8_via_body_signature(qtbot) -> None:
    """Servidores que devuelven m3u8 con `text/html` siguen siendo m3u8."""
    body = (
        b"#EXTM3U\n"
        b"#EXT-X-VERSION:3\n"
        b"#EXT-X-TARGETDURATION:10\n"
        b"#EXTINF:9.5,\nseg1.ts\n"
        b"#EXT-X-ENDLIST\n"
    )
    panel = _make_panel(
        qtbot,
        [
            _flow(
                "obf-1",
                url="https://servidor-raro.example/obfuscated.m3u8?token=abc",
                content_type="text/html; charset=utf-8",
                response_body=body,
            ),
        ],
    )

    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 3).text() == "m3u8"


def test_panel_empty_state(qtbot) -> None:
    """Sin flows la tabla queda vacía y el header dice 0."""
    panel = _make_panel(qtbot, [])
    assert panel.table.rowCount() == 0
    assert panel.header_label.text() == "Streams de vídeo (0)"
    assert panel.summary_label.text() == ""


# ---------------------------------------------------------------- dedupe


def test_panel_dedupes_by_url(qtbot) -> None:
    """La misma URL de playlist no debe aparecer duplicada aunque llegue
    varias veces (común en streams en vivo que se relisten cada pocos segundos).
    """
    panel = _make_panel(
        qtbot,
        [
            _flow(
                "live-1",
                url="https://cdn.example.com/live.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
            _flow(
                "live-2",
                url="https://cdn.example.com/live.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
            _flow(
                "live-3",
                url="https://cdn.example.com/live.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
        ],
    )
    assert panel.table.rowCount() == 1


# ---------------------------------------------------------------- clasificación


def test_panel_classifies_by_extension() -> None:
    """La columna 'Tipo' usa la extensión de la URL, ignorando query string."""
    flow_mp4 = _flow(
        "a", url="https://cdn.example.com/track.mp4?token=xyz", content_type=""
    )
    flow_ts = _flow(
        "b", url="https://cdn.example.com/seg-00001.ts", content_type=""
    )
    flow_webm = _flow(
        "c", url="https://cdn.example.com/clip.webm", content_type=""
    )
    flow_mpd = _flow(
        "d", url="https://cdn.example.com/manifest.mpd", content_type=""
    )
    for flow, expected in [
        (flow_mp4, "mp4"),
        (flow_ts, "ts"),
        (flow_webm, "webm"),
        (flow_mpd, "mpd"),
    ]:
        assert VideoLinksPanel._classify(flow) == expected


def test_panel_classify_prefers_m3u8_body_signature() -> None:
    """Si la URL no termina en .m3u8 pero el body lo es, la columna dice m3u8."""
    body = b"#EXTM3U\n#EXT-X-VERSION:3\nseg1.ts\n"
    flow = _flow(
        "x",
        url="https://cdn.example.com/playlist?cb=1",
        content_type="text/html",
        response_body=body,
    )
    assert VideoLinksPanel._classify(flow) == "m3u8"


def test_panel_summary_breaks_down_by_type(qtbot) -> None:
    """El summary_label desglosa cuántos de cada tipo hay."""
    panel = _make_panel(
        qtbot,
        [
            _flow(
                "a",
                url="https://cdn.example.com/a.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
            _flow(
                "b",
                url="https://cdn.example.com/b.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
            _flow("c", url="https://cdn.example.com/c.mp4", content_type=""),
            _flow("d", url="https://cdn.example.com/d.ts", content_type=""),
            _flow("e", url="https://cdn.example.com/e.ts", content_type=""),
        ],
    )
    summary = panel.summary_label.text()
    # Orden alfabético por tipo en la implementación
    assert "2 m3u8" in summary
    assert "1 mp4" in summary
    assert "2 ts" in summary


# ---------------------------------------------------------------- botones


def test_buttons_disabled_with_no_selection(qtbot) -> None:
    """Sin selección, los 4 botones de fila están deshabilitados."""
    panel = _make_panel(
        qtbot,
        [
            _flow(
                "a",
                url="https://cdn.example.com/x.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
        ],
    )
    assert panel.play_button.isEnabled() is False
    assert panel.copy_url_button.isEnabled() is False
    assert panel.copy_ffmpeg_button.isEnabled() is False
    assert panel.view_m3u8_button.isEnabled() is False
    # El botón Limpiar siempre está disponible si hay filas
    assert panel.clear_button.isEnabled() is True


def test_buttons_enable_with_selection(qtbot) -> None:
    """Seleccionando una fila, los 4 botones se habilitan."""
    panel = _make_panel(
        qtbot,
        [
            _flow(
                "a",
                url="https://cdn.example.com/x.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
        ],
    )
    panel.table.selectRow(0)
    panel._update_button_state()
    assert panel.play_button.isEnabled() is True
    assert panel.copy_url_button.isEnabled() is True
    assert panel.copy_ffmpeg_button.isEnabled() is True
    assert panel.view_m3u8_button.isEnabled() is True


def test_view_m3u8_button_only_enabled_for_m3u8(qtbot) -> None:
    """Un .mp4 NO habilita el botón de ver segmentos m3u8,
    pero SÍ habilita 'Probar en navegador'."""
    panel = _make_panel(
        qtbot,
        [
            _flow("a", url="https://cdn.example.com/clip.mp4", content_type=""),
        ],
    )
    panel.table.selectRow(0)
    panel._update_button_state()
    assert panel.play_button.isEnabled() is True
    assert panel.copy_url_button.isEnabled() is True
    assert panel.copy_ffmpeg_button.isEnabled() is True
    assert panel.view_m3u8_button.isEnabled() is False


# ----------------------------- Probar en navegador ---------------------------


def test_play_button_label_is_descriptive() -> None:
    """El botón debe identificarse claramente para que el usuario sepa
    qué va a pasar al pulsarlo."""
    from streaminspector.gui.video_links_panel import VideoLinksPanel

    # Solo necesitamos el widget, no un panel funcional. Mockeamos el
    # flows_provider para no tocar la red.
    panel = VideoLinksPanel(lambda: [])
    assert "Probar" in panel.play_button.text()
    assert "navegador" in panel.play_button.text()


def test_play_button_opens_url_in_default_browser(qtbot, monkeypatch) -> None:
    """Al pulsar 'Probar en navegador', se llama a QDesktopServices.openUrl
    con la URL del flow seleccionado."""
    opened_urls: list[str] = []
    monkeypatch.setattr(
        "streaminspector.gui.video_links_panel.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toString()) or True,
    )

    panel = _make_panel(
        qtbot,
        [
            _flow(
                "a",
                url="https://cdn.example.com/playlist.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
        ],
    )
    panel.table.selectRow(0)
    panel._open_selected_in_browser()
    assert opened_urls == ["https://cdn.example.com/playlist.m3u8"]


def test_play_button_works_for_mp4_too(qtbot, monkeypatch) -> None:
    """'Probar' también funciona con MP4 directo (no solo m3u8)."""
    opened_urls: list[str] = []
    monkeypatch.setattr(
        "streaminspector.gui.video_links_panel.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toString()) or True,
    )

    panel = _make_panel(
        qtbot,
        [
            _flow("a", url="https://cdn.example.com/clip.mp4", content_type=""),
        ],
    )
    panel.table.selectRow(0)
    panel._open_selected_in_browser()
    assert opened_urls == ["https://cdn.example.com/clip.mp4"]


def test_play_button_no_selection_does_nothing(qtbot, monkeypatch) -> None:
    """Sin selección, el botón está deshabilitado y la acción no se llama."""
    opened_urls: list[str] = []
    monkeypatch.setattr(
        "streaminspector.gui.video_links_panel.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toString()) or True,
    )
    # Evitar que el QMessageBox bloquee el test
    monkeypatch.setattr(
        "streaminspector.gui.video_links_panel.QMessageBox.information",
        lambda *a, **kw: 0,
    )

    panel = _make_panel(
        qtbot,
        [
            _flow(
                "a",
                url="https://cdn.example.com/x.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
        ],
    )
    # NO seleccionamos nada
    panel._open_selected_in_browser()
    assert opened_urls == []


# ---------------------------------------------------------------- acciones


def test_copy_url_action_copies_to_clipboard(qtbot, monkeypatch) -> None:
    """La acción 'Copiar URL' pone la URL exacta en el clipboard."""
    captured: list[str] = []
    monkeypatch.setattr(
        QApplication.clipboard(), "setText", lambda text: captured.append(text)
    )

    panel = _make_panel(
        qtbot,
        [
            _flow(
                "a",
                url="https://cdn.example.com/stream.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
        ],
    )
    panel.table.selectRow(0)
    panel._copy_selected_url()
    assert captured == ["https://cdn.example.com/stream.m3u8"]


def test_copy_ffmpeg_action_uses_build_ffmpeg_command(qtbot, monkeypatch) -> None:
    """La acción 'Copiar como ffmpeg' usa `build_ffmpeg_command` y mete
    el comando completo en el clipboard."""
    captured: list[str] = []
    monkeypatch.setattr(
        QApplication.clipboard(), "setText", lambda text: captured.append(text)
    )

    panel = _make_panel(
        qtbot,
        [
            _flow(
                "a",
                url="https://cdn.example.com/clip.mp4",
                content_type="video/mp4",
            ),
        ],
    )
    panel.table.selectRow(0)
    panel._copy_selected_ffmpeg()
    assert len(captured) == 1
    cmd = captured[0]
    assert "ffmpeg" in cmd
    assert "https://cdn.example.com/clip.mp4" in cmd
    # mp4 por defecto en build_ffmpeg_command → contenedor .mp4
    assert ".mp4" in cmd


def test_copy_ffmpeg_action_includes_referer_from_flow(qtbot, monkeypatch) -> None:
    """Si el flow capturado llevaba `Referer`, el comando ffmpeg lo incluye
    en `-headers`. Sin esto, los streams protegidos devuelven 403 al
    pegar el comando en una terminal."""
    captured: list[str] = []
    monkeypatch.setattr(
        QApplication.clipboard(), "setText", lambda text: captured.append(text)
    )

    # Construimos un flow a mano con Referer en los headers del request.
    # La URL tiene .m3u8 (vía hint en URL) para que pase el filtro del
    # panel, pero el caso real es un segmento .avi/.doc con .m3u8
    # capturado en el mismo flujo.
    flow = HttpFlowCaptured(
        flow_id="prot-1",
        method="GET",
        scheme="https",
        host="cdn.example",
        port=443,
        path="/playlist.m3u8",
        url="https://cdn.example/playlist.m3u8",
        http_version="HTTP/2",
        status_code=200,
        reason="OK",
        content_type="application/vnd.apple.mpegurl",
        request_headers=(
            ("Referer", "https://fctv33hd.fit/eventos/newport-county-vs-roma/"),
            ("User-Agent", "Mozilla/5.0 Test"),
        ),
        response_headers=(),
        request_body=b"",
        response_body=b"",
        request_size=0,
        response_size=0,
        duration_ms=10.0,
    )
    panel = _make_panel(qtbot, [flow])
    assert panel.table.rowCount() == 1
    panel.table.selectRow(0)
    panel._copy_selected_ffmpeg()

    assert len(captured) == 1
    cmd = captured[0]
    # El Referer capturado viaja en el comando
    assert "Referer: https://fctv33hd.fit/eventos/newport-county-vs-roma/" in cmd
    # El User-Agent capturado también
    assert "Mozilla/5.0 Test" in cmd


def test_copy_url_no_selection_does_not_copy(qtbot, monkeypatch) -> None:
    """Sin selección no se copia nada y se muestra info (sin bloquear)."""
    captured: list[str] = []
    monkeypatch.setattr(
        QApplication.clipboard(), "setText", lambda text: captured.append(text)
    )
    # Sin selección la acción muestra un QMessageBox modal que bloquearía
    # el test en offscreen. Lo parcheamos para que sea no-op.
    monkeypatch.setattr(
        "streaminspector.gui.video_links_panel.QMessageBox.information",
        lambda *a, **kw: 0,
    )
    panel = _make_panel(
        qtbot,
        [
            _flow(
                "a",
                url="https://cdn.example.com/stream.m3u8",
                content_type="application/vnd.apple.mpegurl",
            ),
        ],
    )
    # No llamamos a selectRow; currentRow() es -1
    panel._copy_selected_url()
    assert captured == []


# ---------------------------------------------------------------- limpiar


def test_clear_panel_empties_table_but_keeps_source(qtbot) -> None:
    """'Limpiar panel' vacía la tabla pero NO toca el `flows_provider`."""
    state_flows = [
        _flow(
            "a",
            url="https://cdn.example.com/x.m3u8",
            content_type="application/vnd.apple.mpegurl",
        ),
        _flow("b", url="https://cdn.example.com/y.mp4", content_type=""),
    ]

    def provider() -> list[HttpFlowCaptured]:
        return state_flows

    panel = VideoLinksPanel(provider)
    qtbot.addWidget(panel)
    panel.refresh()
    assert panel.table.rowCount() == 2

    panel._clear_panel()
    assert panel.table.rowCount() == 0
    assert panel.header_label.text() == "Streams de vídeo (0)"
    # La fuente sigue teniendo los 2 flows
    assert len(provider()) == 2
    # Re-refrescar los recupera
    panel.refresh()
    assert panel.table.rowCount() == 2


# ---------------------------------------------------------------- integración


def _make_window(qtbot, tmp_path: Path):
    _ = QApplication.instance() or QApplication([])
    bus = EventBus()
    storage = StorageService(bus, tmp_path / "test.sqlite3")
    win = DeepSearchWindow(bus, storage, initial_flows=[])
    qtbot.addWidget(win)
    return win, bus, storage


def test_main_window_has_video_links_panel(qtbot, tmp_path: Path) -> None:
    """El MainWindow expone `video_links_panel` y su dock al inicializar."""
    win, _bus, storage = _make_window(qtbot, tmp_path)
    try:
        assert hasattr(win, "video_links_panel")
        assert isinstance(win.video_links_panel, VideoLinksPanel)
        assert hasattr(win, "video_links_dock")
    finally:
        storage.close()


def test_publishing_video_flow_populates_panel(qtbot, tmp_path: Path) -> None:
    """Publicar un flow de vídeo por el bus hace que el panel lo muestre."""
    win, bus, storage = _make_window(qtbot, tmp_path)
    try:
        bus.publish(
            _flow(
                "live-1",
                url="https://cdn.example.com/live.m3u8",
                content_type="application/vnd.apple.mpegurl",
            )
        )
        panel = win.video_links_panel
        assert panel.table.rowCount() == 1
        assert (
            panel.table.item(0, 4).text() == "https://cdn.example.com/live.m3u8"
        )
    finally:
        storage.close()


def test_publishing_non_video_flow_does_not_populate_panel(
    qtbot, tmp_path: Path
) -> None:
    """HTML/JSON no entran al panel aunque entren al MainWindow."""
    win, bus, storage = _make_window(qtbot, tmp_path)
    try:
        bus.publish(
            _flow(
                "html-1",
                url="https://example.com/page",
                content_type="text/html",
            )
        )
        bus.publish(
            _flow(
                "json-1",
                url="https://api.example.com/data",
                content_type="application/json",
            )
        )
        # Sí entran al MainWindow…
        assert win.history.rowCount() == 2
        # …pero NO al panel de streams.
        assert win.video_links_panel.table.rowCount() == 0
    finally:
        storage.close()


def test_clear_view_empties_panel(qtbot, tmp_path: Path) -> None:
    """`Limpiar vista` (acción del menú) vacía también el panel."""
    win, bus, storage = _make_window(qtbot, tmp_path)
    try:
        bus.publish(
            _flow(
                "a",
                url="https://cdn.example.com/x.m3u8",
                content_type="application/vnd.apple.mpegurl",
            )
        )
        assert win.video_links_panel.table.rowCount() == 1

        # La acción "Limpiar vista" llama directamente a `_clear_view`.
        win.action_clear_view.trigger()
        assert win.video_links_panel.table.rowCount() == 0
    finally:
        storage.close()
