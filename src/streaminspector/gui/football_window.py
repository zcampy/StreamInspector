"""Ventana principal con la pestaña de partidos en el nivel superior."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.gui.deep_search_window import DeepSearchWindow
from streaminspector.storage import StorageService


class FootballWindow(DeepSearchWindow):
    """Muestra Tráfico y Partidos como pestañas principales independientes."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self._promote_football_tab()

    def _promote_football_tab(self) -> None:
        traffic_widget = self.takeCentralWidget()
        football_panel = self.football_events_panel

        detail_index = self.details.indexOf(football_panel)
        if detail_index >= 0:
            self.details.removeTab(detail_index)

        self.main_tabs = QTabWidget(self)
        self.main_tabs.setObjectName("main_tabs")
        self.main_tabs.addTab(traffic_widget, "Tráfico")
        self.main_tabs.addTab(football_panel, "Partidos")
        self.setCentralWidget(self.main_tabs)
