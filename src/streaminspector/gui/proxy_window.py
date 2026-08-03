from __future__ import annotations

import socket

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QInputDialog, QMessageBox

from streaminspector.core.events import (
    EventBus,
    HttpFlowCaptured,
    ProxyStartRequested,
    ProxyStopRequested,
    StatusMessage,
)
from streaminspector.gui.advanced_window import AdvancedMainWindow
from streaminspector.storage import StorageService

DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 8080


class ProxyConfiguredWindow(AdvancedMainWindow):
    """Advanced window with persistent proxy endpoint controls."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self._proxy_settings = QSettings("StreamInspector", "StreamInspector")
        self._install_proxy_actions()
        self._show_proxy_endpoint()

    def _install_proxy_actions(self) -> None:
        menu = self.menuBar().addMenu("Proxy")

        configure_action = QAction("Configurar host y puerto…", self)
        configure_action.triggered.connect(self._configure_proxy)
        menu.addAction(configure_action)

        diagnose_action = QAction("Diagnosticar configuración…", self)
        diagnose_action.triggered.connect(self._diagnose_proxy)
        menu.addAction(diagnose_action)

    def _proxy_endpoint(self) -> tuple[str, int]:
        host = str(self._proxy_settings.value("proxy/host", DEFAULT_PROXY_HOST)).strip()
        port = int(self._proxy_settings.value("proxy/port", DEFAULT_PROXY_PORT))
        return host or DEFAULT_PROXY_HOST, port

    def _show_proxy_endpoint(self) -> None:
        host, port = self._proxy_endpoint()
        self.proxy_button.setToolTip(f"Proxy configurado: {host}:{port}")

    def _toggle_proxy(self, enabled: bool) -> None:
        self.proxy_button.setEnabled(False)
        if enabled:
            host, port = self._proxy_endpoint()
            self._event_bus.publish(ProxyStartRequested(host=host, port=port))
        else:
            self._event_bus.publish(ProxyStopRequested())

    def _configure_proxy(self) -> None:
        if self.proxy_button.isChecked():
            QMessageBox.information(
                self,
                "Configurar proxy",
                "Detén el proxy antes de cambiar el host o el puerto.",
            )
            return

        current_host, current_port = self._proxy_endpoint()
        host, accepted = QInputDialog.getText(
            self,
            "Host del proxy",
            "Dirección de escucha:",
            text=current_host,
        )
        if not accepted:
            return
        host = host.strip()
        if not host:
            QMessageBox.warning(self, "Host no válido", "El host no puede estar vacío.")
            return

        port, accepted = QInputDialog.getInt(
            self,
            "Puerto del proxy",
            "Puerto de escucha:",
            current_port,
            1,
            65535,
        )
        if not accepted:
            return

        self._proxy_settings.setValue("proxy/host", host)
        self._proxy_settings.setValue("proxy/port", port)
        self._show_proxy_endpoint()
        self._event_bus.publish(StatusMessage(message=f"Proxy configurado en {host}:{port}"))

    def _diagnose_proxy(self) -> None:
        host, port = self._proxy_endpoint()
        bind_error = _check_bind_error(host, port)
        if bind_error:
            detail = f"El puerto no está disponible: {bind_error}"
        else:
            detail = "El host y el puerto están disponibles para iniciar el proxy."
        QMessageBox.information(
            self,
            "Diagnóstico del proxy",
            f"Configuración actual: {host}:{port}\n\n{detail}\n\n"
            "No es necesario definir STREAMINSPECTOR_PROXY__HOST ni "
            "STREAMINSPECTOR_PROXY__PORT manualmente.",
        )


def _check_bind_error(host: str, port: int) -> str | None:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
    except OSError as exc:
        return str(exc)
    return None
