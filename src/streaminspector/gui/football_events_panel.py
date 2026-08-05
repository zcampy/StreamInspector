"""Pestaña con los eventos de fútbol emitidos por la página observada."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.football_events import (
    FootballEvent,
    is_football_events_url,
    parse_football_events,
)


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

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Hora", "Competición", "Equipo local", "Equipo visitante", "ID"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        self.note = QLabel(
            "La lista se actualiza automáticamente cuando la página de fútbol carga "
            "su API de eventos. Solo se incluyen eventos marcados por la fuente con stream=true."
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
                "Eventos cargados desde la última respuesta válida de la API de fútbol."
            )
        except (OSError, ValueError) as exc:
            self._events = []
            self.note.setText(f"No se pudo interpretar la respuesta de eventos: {exc}")
        self._render()

    def _render(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            time_item = QTableWidgetItem(event.local_time.strftime("%d/%m %H:%M"))
            time_item.setData(Qt.ItemDataRole.UserRole, event.starts_at_ms)
            self.table.setItem(row, 0, time_item)
            self.table.setItem(row, 1, QTableWidgetItem(event.competition or "—"))
            self.table.setItem(row, 2, QTableWidgetItem(event.home))
            self.table.setItem(row, 3, QTableWidgetItem(event.away or "—"))
            self.table.setItem(row, 4, QTableWidgetItem(str(event.match_id)))
        self.table.setSortingEnabled(True)
        self.summary.setText(f"Partidos disponibles: {len(self._events)}")
