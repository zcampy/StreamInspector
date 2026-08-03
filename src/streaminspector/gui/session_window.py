from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QVBoxLayout, QWidget

from streaminspector.core.events import EventBus, HttpFlowCaptured, StatusMessage
from streaminspector.gui.main_window import MainWindow
from streaminspector.gui.session_panel import SessionPanel
from streaminspector.gui.traffic_filters import TrafficFilterBar
from streaminspector.storage import SessionSummary, StorageService


class SessionMainWindow(MainWindow):
    """Main window extended with session navigation and traffic filters."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        self._storage = storage
        self._visible_session_id: int | None = None
        super().__init__(event_bus, initial_flows=initial_flows)
        self._install_filter_bar()
        self._build_sessions_dock()

    def _install_filter_bar(self) -> None:
        content = self.takeCentralWidget()
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        self.filter_bar = TrafficFilterBar(self.history, lambda: self._flows, container)
        layout.addWidget(self.filter_bar)
        layout.addWidget(content, 1)
        self.setCentralWidget(container)

    def _build_sessions_dock(self) -> None:
        dock = QDockWidget("Sesiones", self)
        dock.setObjectName("sessions_dock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.session_panel = SessionPanel(self._storage, self._open_session, dock)
        dock.setWidget(self.session_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _open_session(self, summary: SessionSummary) -> None:
        flows = self._storage.session_events(summary.id, limit=500)
        self._clear_view()
        self._visible_session_id = summary.id
        self._domain_root.setText(0, summary.name)
        for flow in flows:
            self._append_flow(flow)
        self.filter_bar.refresh_options()
        self._event_bus.publish(
            StatusMessage(
                message=f"Sesión abierta: {summary.name} ({len(flows)} capturas)"
            )
        )

    def _append_flow(self, event: HttpFlowCaptured) -> None:
        super()._append_flow(event)
        if hasattr(self, "filter_bar"):
            self.filter_bar.refresh_options()

    def _clear_view(self) -> None:
        super()._clear_view()
        if hasattr(self, "filter_bar"):
            self.filter_bar.refresh_options()

    def _on_flow_captured(self, event: HttpFlowCaptured) -> None:
        if self._visible_session_id not in (None, self._storage.active_session_id):
            return
        self._visible_session_id = self._storage.active_session_id
        self._domain_root.setText(0, "Sesión actual")
        super()._on_flow_captured(event)
        self.session_panel.refresh()
