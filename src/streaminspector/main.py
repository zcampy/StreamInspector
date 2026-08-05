from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from streaminspector import __version__
from streaminspector.capture_policy import CapturePolicy, load_capture_policy
from streaminspector.core.config import AppSettings
from streaminspector.core.events import ApplicationStarted, EventBus
from streaminspector.core.logging import configure_logging
from streaminspector.gui.football_schedule_window import FootballScheduleWindow
from streaminspector.gui.theme import DARK_STYLESHEET
from streaminspector.proxy import ProxyService
from streaminspector.storage import StorageService


def build_application() -> tuple[
    QApplication,
    FootballScheduleWindow,
    EventBus,
    ProxyService,
    StorageService,
    CapturePolicy,
]:
    settings = AppSettings()
    settings.ensure_directories()
    configure_logging(settings.log_dir)

    app = QApplication(sys.argv)
    app.setApplicationName("StreamInspector")
    app.setApplicationVersion(__version__)
    if settings.ui.theme == "dark":
        app.setStyleSheet(DARK_STYLESHEET)

    event_bus = EventBus()
    storage_service = StorageService(
        event_bus,
        settings.data_dir / settings.storage.database_name,
    )
    capture_settings = QSettings("StreamInspector", "StreamInspector")
    capture_policy = load_capture_policy(capture_settings)
    storage_service.set_capture_filter(capture_policy.accepts, policy=capture_policy)
    proxy_service = ProxyService(event_bus, capture_policy)
    app.aboutToQuit.connect(proxy_service.close)
    app.aboutToQuit.connect(storage_service.close)

    initial_flows = storage_service.recent_events(limit=500)
    window = FootballScheduleWindow(
        event_bus,
        storage_service,
        initial_flows=initial_flows,
    )
    event_bus.publish(ApplicationStarted(version=__version__))
    return (
        app,
        window,
        event_bus,
        proxy_service,
        storage_service,
        capture_policy,
    )


def main() -> int:
    app, window, _event_bus, _proxy_service, _storage_service, _policy = (
        build_application()
    )
    logging.getLogger(__name__).info("Starting StreamInspector %s", __version__)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
