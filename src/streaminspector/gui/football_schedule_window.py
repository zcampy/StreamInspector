"""Ventana principal con pestaña automática de partidos de fútbol."""

from __future__ import annotations

from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.gui.deep_search_window import DeepSearchWindow
from streaminspector.gui.football_events_panel import FootballEventsPanel
from streaminspector.storage import StorageService


class FootballScheduleWindow(DeepSearchWindow):
    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self.football_events_panel = FootballEventsPanel(lambda: self._flows, self)
        self.details.addTab(self.football_events_panel, "Partidos")
        self.football_events_panel.refresh()

    def _append_flow(self, event: HttpFlowCaptured) -> None:
        super()._append_flow(event)
        panel = getattr(self, "football_events_panel", None)
        if panel is not None:
            panel.refresh()
