from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget

from streaminspector.core.events import EventBus, HttpFlowCaptured, StatusMessage
from streaminspector.gui.main_window import MainWindow
from streaminspector.gui.session_panel import SessionPanel
from streaminspector.storage import SessionSummary, StorageService


class SessionMainWindow(MainWindow):
    """Main window extended with persisted capture-session navigation."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        self._storage = storage
        self._visible_session_id: int | None = None
        super().__init__(event_bus, initial_flows=initial_flows)
        self._build_sessions_dock()

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
        self._event_bus.publish(
            StatusMessage(
                message=f"Sesión abierta: {summary.name} ({len(flows)} capturas)"
            )
        )

    def _on_flow_captured(self, event: HttpFlowCaptured) -> None:
        if self._visible_session_id not in (None, self._storage.active_session_id):
            return
        self._visible_session_id = self._storage.active_session_id
        self._domain_root.setText(0, "Sesión actual")
        super()._on_flow_captured(event)
        self.session_panel.refresh()
