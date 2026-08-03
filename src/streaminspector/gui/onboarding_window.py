from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from streaminspector import __version__
from streaminspector.core.config import AppSettings
from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.gui.onboarding_dialog import OnboardingDialog
from streaminspector.gui.selective_capture_window import SelectiveCaptureWindow
from streaminspector.storage import StorageService


class OnboardingWindow(SelectiveCaptureWindow):
    """Main window with an accessible first-run guide and diagnostics."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self._onboarding_dialogs: list[OnboardingDialog] = []
        self._install_onboarding_action()
        QTimer.singleShot(0, self._show_onboarding_once)

    def _install_onboarding_action(self) -> None:
        help_menu = next(
            (
                menu
                for menu in self.menuBar().findChildren(QMenu)
                if menu.title().replace("&", "") == "Ayuda"
            ),
            None,
        )
        if help_menu is None:
            help_menu = self.menuBar().addMenu("Ayuda")
        action = QAction("Primeros pasos y diagnóstico…", self)
        action.triggered.connect(self._show_onboarding)
        help_menu.addAction(action)

    def _show_onboarding_once(self) -> None:
        settings = QSettings("StreamInspector", "StreamInspector")
        key = f"onboarding/{__version__}"
        if settings.value(key, False, type=bool):
            return
        self._show_onboarding()
        settings.setValue(key, True)

    def _show_onboarding(self) -> None:
        host, port = self._proxy_endpoint()
        dialog = OnboardingDialog(host, port, AppSettings().data_dir, self)
        self._onboarding_dialogs.append(dialog)
        dialog.finished.connect(lambda: self._onboarding_dialogs.remove(dialog))
        dialog.show()
