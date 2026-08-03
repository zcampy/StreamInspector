from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from streaminspector import __version__
from streaminspector.core.config import AppSettings
from streaminspector.core.events import ApplicationStarted, EventBus
from streaminspector.core.logging import configure_logging
from streaminspector.gui.main_window import MainWindow
from streaminspector.gui.theme import DARK_STYLESHEET
from streaminspector.proxy import ProxyService


def build_application() -> tuple[QApplication, MainWindow, EventBus, ProxyService]:
    settings = AppSettings()
    settings.ensure_directories()
    configure_logging(settings.log_dir)

    app = QApplication(sys.argv)
    app.setApplicationName("StreamInspector")
    app.setApplicationVersion(__version__)
    if settings.ui.theme == "dark":
        app.setStyleSheet(DARK_STYLESHEET)

    event_bus = EventBus()
    proxy_service = ProxyService(event_bus, settings.proxy)
    app.aboutToQuit.connect(proxy_service.close)

    window = MainWindow(event_bus)
    event_bus.publish(ApplicationStarted(version=__version__))
    return app, window, event_bus, proxy_service


def main() -> int:
    app, window, _event_bus, _proxy_service = build_application()
    logging.getLogger(__name__).info("Starting StreamInspector %s", __version__)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
