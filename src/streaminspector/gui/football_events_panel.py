"""Pestaña con los eventos de fútbol emitidos por la página observada."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
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
from streaminspector.media_playback import (
    build_ffplay_command,
    find_ffplay,
    launch_command,
)
from streaminspector.stream_validation import validate_reproducible_link

_MATCH_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class FootballEventsPanel(QWidget):
    def __init__(
        self,
        flows_provider: Callable[[], list[HttpFlowCaptured]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._flows_provider = flows_provider
        self._events: list[FootballEvent] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.summary = QLabel("Partidos disponibles: 0")
        header.addWidget(self.summary)
        header.addStretch(1)
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
            "La lista se actualiza automáticamente cuando la página de fútbol carga "
            "su API de eventos. Un partido aparece como reproducible cuando ya se ha "
            "capturado su playlist HLS."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #888c95;")
        layout.addWidget(self.note)

    def refresh(self) -> None:
        latest: HttpFlowCaptured | None = None
        for flow in self._flows_provider():
            if is_football_events_url(flow.url) and flow.status_code == 200:
                latest = flow
        if latest is None:
            self._events = []
            self._render()
            self.note.setText(
                "Abre la página de fútbol con el proxy activo. Cuando llegue la respuesta "
                "de eventos, los partidos aparecerán aquí automáticamente."
            )
            return
        try:
            self._events = parse_football_events(
                latest.response_body,
                latest.response_headers,
            )
            self.note.setText(
                "Eventos cargados. Abre un partido en la web para capturar su stream; "
                "cuando llegue el M3U8, la fila cambiará a Disponible."
            )
        except (OSError, ValueError) as exc:
            self._events = []
            self.note.setText(f"No se pudo interpretar la respuesta de eventos: {exc}")
        self._render()

    def _render(self) -> None:
        flows = self._flows_provider()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._events))
        available = 0
        for row, event in enumerate(self._events):
            playlist = captured_playlist_for_match(flows, event.match_id)
            if playlist is not None:
                available += 1
            time_item = QTableWidgetItem(event.local_time.strftime("%d/%m %H:%M"))
            time_item.setData(Qt.ItemDataRole.UserRole, event.starts_at_ms)
            time_item.setData(_MATCH_ID_ROLE, event.match_id)
            self.table.setItem(row, 0, time_item)
            self.table.setItem(row, 1, QTableWidgetItem(event.competition or "—"))
            self.table.setItem(row, 2, QTableWidgetItem(event.home))
            self.table.setItem(row, 3, QTableWidgetItem(event.away or "—"))
            self.table.setItem(
                row,
                4,
                QTableWidgetItem("Disponible" if playlist is not None else "Sin capturar"),
            )
            self.table.setItem(row, 5, QTableWidgetItem(str(event.match_id)))
        self.table.setSortingEnabled(True)
        self.summary.setText(
            f"Partidos: {len(self._events)} · Reproducibles: {available}"
        )
        self._update_play_state()

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
        if match_id is None:
            return None
        return captured_playlist_for_match(self._flows_provider(), match_id)

    def _update_play_state(self) -> None:
        self.play_button.setEnabled(self._selected_playlist() is not None)

    def _play_selected(self) -> None:
        playlist = self._selected_playlist()
        if playlist is None:
            QMessageBox.information(
                self,
                "Stream todavía no capturado",
                "Abre este partido en la página con el proxy activo y espera a que "
                "empiece a cargar el reproductor. La fila se actualizará automáticamente.",
            )
            return
        executable = find_ffplay()
        if executable is None:
            QMessageBox.warning(
                self,
                "ffplay no está instalado",
                "No se encontró ffplay en PATH. Instala FFmpeg para reproducir el stream.",
            )
            return

        original_text = self.play_button.text()
        self.play_button.setText("Validando…")
        self.play_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = validate_reproducible_link(
                playlist.url,
                playlist.request_headers,
            )
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
