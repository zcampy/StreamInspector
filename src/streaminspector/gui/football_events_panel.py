"""Pestaña de partidos cargada íntegramente mediante HTTP en segundo plano."""

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
from streaminspector.football_events import FootballEvent
from streaminspector.football_stream_discovery import (
    BackendContext,
    DirectPlaylistResult,
    ScheduleResult,
    discover_direct_playlist,
    load_backend_schedule,
)
from streaminspector.media_playback import build_ffplay_command, find_ffplay, launch_command
from streaminspector.stream_validation import validate_reproducible_link

_MATCH_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_MAX_BACKGROUND_MATCHES = 20


class _ScheduleThread(QThread):
    loaded = Signal(object)

    def run(self) -> None:
        self.loaded.emit(load_backend_schedule())


class _DiscoveryThread(QThread):
    found = Signal(object)
    progress = Signal(int, int)

    def __init__(self, context: BackendContext, events: list[FootballEvent]) -> None:
        super().__init__()
        self._context = context
        self._events = events[:_MAX_BACKGROUND_MATCHES]

    def run(self) -> None:
        total = len(self._events)
        for index, event in enumerate(self._events, start=1):
            if self.isInterruptionRequested():
                break
            self.progress.emit(index, total)
            self.found.emit(discover_direct_playlist(self._context, event.match_id))


class FootballEventsPanel(QWidget):
    def __init__(
        self,
        flows_provider: Callable[[], list[HttpFlowCaptured]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Se conserva el argumento por compatibilidad con la ventana principal,
        # pero esta pestaña no depende del proxy ni de capturas HTTP.
        self._flows_provider = flows_provider
        self._events: list[FootballEvent] = []
        self._context: BackendContext | None = None
        self._direct_playlists: dict[int, HttpFlowCaptured] = {}
        self._lookup_messages: dict[int, str] = {}
        self._schedule_thread: _ScheduleThread | None = None
        self._discovery_thread: _DiscoveryThread | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.summary = QLabel("Partidos: 0 · Reproducibles: 0")
        header.addWidget(self.summary)
        header.addStretch(1)
        self.search_button = QPushButton("Buscar enlaces")
        self.search_button.setEnabled(False)
        self.search_button.clicked.connect(self._start_background_discovery)
        header.addWidget(self.search_button)
        self.refresh_button = QPushButton("Actualizar")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
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
            "La lista y los enlaces se consultan directamente desde la aplicación, "
            "sin activar el proxy ni abrir un navegador."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #888c95;")
        layout.addWidget(self.note)

    def refresh(self) -> None:
        if self._schedule_thread is not None:
            return
        self.refresh_button.setEnabled(False)
        self.search_button.setEnabled(False)
        self.note.setText("Cargando calendario directamente desde el backend…")
        self._schedule_thread = _ScheduleThread(self)
        self._schedule_thread.loaded.connect(self._on_schedule_loaded)
        self._schedule_thread.finished.connect(self._on_schedule_finished)
        self._schedule_thread.start()

    def _on_schedule_loaded(self, result: ScheduleResult) -> None:
        self._events = result.events
        self._context = result.context
        self._lookup_messages.clear()
        self.note.setText(result.message)
        self._render()
        if self._events and self._context is not None:
            self._start_background_discovery()

    def _on_schedule_finished(self) -> None:
        thread = self._schedule_thread
        self._schedule_thread = None
        if thread is not None:
            thread.deleteLater()
        self.refresh_button.setEnabled(True)
        self.search_button.setEnabled(bool(self._events and self._context))

    def _playlist_for_match(self, match_id: int) -> HttpFlowCaptured | None:
        return self._direct_playlists.get(match_id)

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
        if self._discovery_thread is not None or self._context is None:
            return
        pending = [event for event in self._events if self._playlist_for_match(event.match_id) is None]
        if not pending:
            return
        for event in pending[:_MAX_BACKGROUND_MATCHES]:
            self._lookup_messages[event.match_id] = "Buscando…"
        self._render()
        self.search_button.setEnabled(False)
        self._discovery_thread = _DiscoveryThread(self._context, pending)
        self._discovery_thread.found.connect(self._on_direct_result)
        self._discovery_thread.progress.connect(self._on_discovery_progress)
        self._discovery_thread.finished.connect(self._on_discovery_finished)
        self._discovery_thread.start()

    def _on_direct_result(self, result: DirectPlaylistResult) -> None:
        if result.url:
            self._direct_playlists[result.match_id] = HttpFlowCaptured(
                flow_id=f"backend-{result.match_id}",
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
        self.note.setText(f"Buscando enlaces en segundo plano: {current}/{total}")

    def _on_discovery_finished(self) -> None:
        thread = self._discovery_thread
        self._discovery_thread = None
        if thread is not None:
            thread.deleteLater()
        self.search_button.setEnabled(bool(self._events and self._context))
        self.note.setText(
            "Búsqueda terminada. No directo significa que la respuesta pública no contiene "
            "una URL HLS utilizable directamente."
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
                "El backend no ha devuelto un M3U8 directo para este partido.",
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
            include_sensitive_headers=False,
            executable=executable,
        )
        try:
            launch_command(command)
        except OSError as exc:
            QMessageBox.critical(self, "No se pudo abrir ffplay", str(exc))

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001 - Qt API
        for thread in (self._schedule_thread, self._discovery_thread):
            if thread is not None:
                thread.requestInterruption()
                thread.wait(1500)
        super().closeEvent(event)
