"""Pestaña con los eventos de fútbol emitidos por la página observada."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.football_events import (
    FootballEvent,
    captured_playlist_for_match,
    is_football_events_url,
    parse_football_events,
)
from streaminspector.football_stream_discovery import (
    DirectPlaylistResult,
    discover_direct_playlist,
    latest_match_detail_template,
)
from streaminspector.media_playback import build_ffplay_command, find_ffplay, launch_command
from streaminspector.stream_validation import validate_reproducible_link

_MATCH_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_MAX_BACKGROUND_MATCHES = 20


class _DiscoveryThread(QThread):
    found = Signal(object)
    progress = Signal(int, int)

    def __init__(self, template: HttpFlowCaptured, events: list[FootballEvent]) -> None:
        super().__init__()
        self._template = template
        self._events = events[:_MAX_BACKGROUND_MATCHES]

    def run(self) -> None:
        total = len(self._events)
        for index, event in enumerate(self._events, start=1):
            if self.isInterruptionRequested():
                break
            self.progress.emit(index, total)
            self.found.emit(discover_direct_playlist(self._template, event.match_id))


class FootballEventsPanel(QWidget):
    def __init__(
        self,
        flows_provider: Callable[[], list[HttpFlowCaptured]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._flows_provider = flows_provider
        self._events: list[FootballEvent] = []
        self._direct_playlists: dict[int, HttpFlowCaptured] = {}
        self._lookup_messages: dict[int, str] = {}
        self._discovery_thread: _DiscoveryThread | None = None
        self._auto_started_template = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.summary = QLabel("Partidos disponibles: 0")
        header.addWidget(self.summary)
        header.addStretch(1)
        self.search_button = QPushButton("Buscar enlaces")
        self.search_button.clicked.connect(self._start_background_discovery)
        header.addWidget(self.search_button)
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Hora", "Competición", "Equipo local", "Equipo visitante", "Estado", "ID"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_play_state)
        self.table.doubleClicked.connect(lambda _index: self._play_selected())
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        controls = QHBoxLayout()
        self.play_button = QPushButton("▶ Reproducir")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._play_selected)
        controls.addWidget(self.play_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.note = QLabel(
            "Los enlaces directos se buscan en segundo plano sin abrir navegadores. "
            "Las respuestas que requieran JavaScript, descifrado o autenticación se marcan "
            "como no directas."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #888c95;")
        layout.addWidget(self.note)

    def refresh(self) -> None:
        flows = self._flows_provider()
        latest: HttpFlowCaptured | None = None
        for flow in flows:
            if is_football_events_url(flow.url) and flow.status_code == 200:
                latest = flow
        if latest is None:
            self._events = []
            self._render()
            self.note.setText(
                "Abre una vez la página de fútbol con el proxy activo para capturar la "
                "lista y una plantilla de la API. Después la búsqueda se hace en segundo plano."
            )
            return
        try:
            self._events = parse_football_events(latest.response_body, latest.response_headers)
        except (OSError, ValueError) as exc:
            self._events = []
            self.note.setText(f"No se pudo interpretar la respuesta de eventos: {exc}")
        self._render()

        template = latest_match_detail_template(flows)
        if (
            template is not None
            and template.url != self._auto_started_template
            and self._discovery_thread is None
        ):
            self._auto_started_template = template.url
            self._start_background_discovery()

    def _playlist_for_match(self, match_id: int) -> HttpFlowCaptured | None:
        captured = captured_playlist_for_match(self._flows_provider(), match_id)
        return captured or self._direct_playlists.get(match_id)

    def _status_for_match(self, match_id: int) -> str:
        if self._playlist_for_match(match_id) is not None:
            return "Disponible"
        return self._lookup_messages.get(match_id, "Pendiente")

    def _render(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._events))
        available = 0
        for row, event in enumerate(self._events):
            if self._playlist_for_match(event.match_id) is not None:
                available += 1
            time_item = QTableWidgetItem(event.local_time.strftime("%d/%m %H:%M"))
            time_item.setData(Qt.ItemDataRole.UserRole, event.starts_at_ms)
            time_item.setData(_MATCH_ID_ROLE, event.match_id)
            self.table.setItem(row, 0, time_item)
            self.table.setItem(row, 1, QTableWidgetItem(event.competition or "—"))
            self.table.setItem(row, 2, QTableWidgetItem(event.home))
            self.table.setItem(row, 3, QTableWidgetItem(event.away or "—"))
            self.table.setItem(row, 4, QTableWidgetItem(self._status_for_match(event.match_id)))
            self.table.setItem(row, 5, QTableWidgetItem(str(event.match_id)))
        self.table.setSortingEnabled(True)
        self.summary.setText(f"Partidos: {len(self._events)} · Reproducibles: {available}")
        self._update_play_state()

    def _start_background_discovery(self) -> None:
        if self._discovery_thread is not None:
            return
        template = latest_match_detail_template(self._flows_provider())
        if template is None:
            QMessageBox.information(
                self,
                "Falta una plantilla de la API",
                "Abre una sola página de partido con el proxy activo. Después StreamInspector "
                "podrá consultar los demás partidos en segundo plano.",
            )
            return
        pending = [event for event in self._events if self._playlist_for_match(event.match_id) is None]
        if not pending:
            return
        for event in pending[:_MAX_BACKGROUND_MATCHES]:
            self._lookup_messages[event.match_id] = "Buscando…"
        self._render()
        self.search_button.setEnabled(False)
        self._discovery_thread = _DiscoveryThread(template, pending)
        self._discovery_thread.found.connect(self._on_direct_result)
        self._discovery_thread.progress.connect(self._on_discovery_progress)
        self._discovery_thread.finished.connect(self._on_discovery_finished)
        self._discovery_thread.start()

    def _on_direct_result(self, result: DirectPlaylistResult) -> None:
        if result.url:
            self._direct_playlists[result.match_id] = HttpFlowCaptured(
                flow_id=f"direct-{result.match_id}",
                method="GET",
                url=result.url,
                request_headers=result.request_headers,
                content_type="application/vnd.apple.mpegurl",
            )
            self._lookup_messages[result.match_id] = "Disponible"
        else:
            self._lookup_messages[result.match_id] = "No directo"
        self._render()

    def _on_discovery_progress(self, current: int, total: int) -> None:
        self.note.setText(f"Buscando enlaces directos en segundo plano: {current}/{total}")

    def _on_discovery_finished(self) -> None:
        thread = self._discovery_thread
        self._discovery_thread = None
        if thread is not None:
            thread.deleteLater()
        self.search_button.setEnabled(True)
        self.note.setText(
            "Búsqueda terminada. Disponible indica un M3U8 directo; No directo indica "
            "que la respuesta requiere la página, JavaScript o protección adicional."
        )
        self._render()

    def _selected_match_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        value = item.data(_MATCH_ID_ROLE)
        return int(value) if value is not None else None

    def _selected_playlist(self) -> HttpFlowCaptured | None:
        match_id = self._selected_match_id()
        return None if match_id is None else self._playlist_for_match(match_id)

    def _update_play_state(self) -> None:
        self.play_button.setEnabled(self._selected_playlist() is not None)

    def _play_selected(self) -> None:
        playlist = self._selected_playlist()
        if playlist is None:
            QMessageBox.information(
                self,
                "Stream no disponible",
                "La API no ha devuelto un M3U8 directo para este partido.",
            )
            return
        executable = find_ffplay()
        if executable is None:
            QMessageBox.warning(self, "ffplay no está instalado", "No se encontró ffplay en PATH.")
            return

        original_text = self.play_button.text()
        self.play_button.setText("Validando…")
        self.play_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = validate_reproducible_link(playlist.url, playlist.request_headers)
        finally:
            QApplication.restoreOverrideCursor()
            self.play_button.setText(original_text)
            self._update_play_state()

        if not result.ok or not result.playable:
            QMessageBox.warning(
                self,
                "Stream no reproducible",
                f"{result.message}\nHTTP: {result.status_code or '—'}\n"
                f"Formato: {result.media_format or 'no identificado'}",
            )
            return

        command = build_ffplay_command(
            playlist.url,
            playlist.request_headers,
            include_sensitive_headers=result.used_sensitive_headers,
            executable=executable,
        )
        try:
            launch_command(command)
        except OSError as exc:
            QMessageBox.critical(self, "No se pudo abrir ffplay", str(exc))

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001 - Qt API
        if self._discovery_thread is not None:
            self._discovery_thread.requestInterruption()
            self._discovery_thread.wait(1500)
        super().closeEvent(event)
