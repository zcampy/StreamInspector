from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMessageBox

from streaminspector.core.events import EventBus, HttpFlowCaptured, StatusMessage
from streaminspector.gui.onboarding_window import OnboardingWindow
from streaminspector.har_import import flows_from_har
from streaminspector.storage import StorageService


class HarImportWindow(OnboardingWindow):
    """Main window with read-only HAR import for offline analysis."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self._install_har_import_action()

    def _install_har_import_action(self) -> None:
        menu = self.menuBar().addMenu("Importar")
        action = QAction("Archivo HAR…", self)
        action.triggered.connect(self._import_har)
        menu.addAction(action)

    def _import_har(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Importar archivo HAR",
            "",
            "HTTP Archive (*.har);;JSON (*.json);;Todos los archivos (*)",
        )
        if not filename:
            return
        path = Path(filename)
        try:
            flows = flows_from_har(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "No se pudo importar el HAR", str(exc))
            return
        if not flows:
            QMessageBox.information(self, "Importar HAR", "El archivo no contiene capturas.")
            return

        self._clear_view()
        self._visible_session_id = -1
        self._domain_root.setText(0, f"HAR: {path.name}")
        for flow in flows:
            self._append_flow(flow)
        self.filter_bar.refresh_options()
        self._event_bus.publish(
            StatusMessage(message=f"Importadas {len(flows)} capturas desde {path.name}")
        )
