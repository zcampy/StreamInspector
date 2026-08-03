from __future__ import annotations

import socket

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QInputDialog, QMessageBox

from streaminspector.core.events import (
    EventBus,
    HttpFlowCaptured,
    ProxyError,
    ProxyStartRequested,
    ProxyStateChanged,
    ProxyStopRequested,
    StatusMessage,
)
from streaminspector.gui.advanced_window import AdvancedMainWindow
from streaminspector.gui.https_setup_dialog import HttpsSetupDialog
from streaminspector.storage import StorageService
from streaminspector.system_proxy import (
    SystemProxySnapshot,
    enable_system_proxy,
    restore_system_proxy,
    system_proxy_supported,
)

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
        self._https_dialogs: list[HttpsSetupDialog] = []
        self._system_proxy_snapshot: SystemProxySnapshot | None = None
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

        self.system_proxy_action = QAction(
            "Configurar automáticamente el proxy de Windows",
            self,
        )
        self.system_proxy_action.setCheckable(True)
        automatic = self._proxy_settings.value(
            "proxy/configure_system",
            system_proxy_supported(),
            type=bool,
        )
        self.system_proxy_action.setChecked(automatic and system_proxy_supported())
        self.system_proxy_action.setEnabled(system_proxy_supported())
        self.system_proxy_action.toggled.connect(
            lambda checked: self._proxy_settings.setValue(
                "proxy/configure_system",
                checked,
            )
        )
        menu.addAction(self.system_proxy_action)

        menu.addSeparator()
        https_action = QAction("Configurar navegador y HTTPS…", self)
        https_action.triggered.connect(self._show_https_setup)
        menu.addAction(https_action)

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

    def _on_proxy_state_changed(self, event: ProxyStateChanged) -> None:
        super()._on_proxy_state_changed(event)
        if event.running:
            self._enable_windows_proxy(event.host, event.port)
        else:
            self._restore_windows_proxy()

    def _on_proxy_error(self, event: ProxyError) -> None:
        self._restore_windows_proxy()
        super()._on_proxy_error(event)

    def _enable_windows_proxy(self, host: str, port: int) -> None:
        if not self.system_proxy_action.isChecked() or self._system_proxy_snapshot is not None:
            return
        try:
            self._system_proxy_snapshot = enable_system_proxy(host, port)
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(
                self,
                "Proxy de Windows",
                f"El proxy está activo, pero Windows no pudo configurarse automáticamente:\n{exc}",
            )
            return
        self.statusBar().showMessage(
            f"Proxy activo en {host}:{port}; configuración de Windows aplicada",
            8000,
        )

    def _restore_windows_proxy(self) -> None:
        snapshot = self._system_proxy_snapshot
        if snapshot is None:
            return
        self._system_proxy_snapshot = None
        try:
            restore_system_proxy(snapshot)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Restaurar proxy de Windows",
                f"No se pudo restaurar la configuración anterior:\n{exc}",
            )

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
        system_detail = (
            "Windows se configurará y restaurará automáticamente."
            if self.system_proxy_action.isChecked()
            else "La configuración automática del proxy de Windows está desactivada."
        )
        QMessageBox.information(
            self,
            "Diagnóstico del proxy",
            f"Configuración actual: {host}:{port}\n\n{detail}\n{system_detail}\n\n"
            "No es necesario definir STREAMINSPECTOR_PROXY__HOST ni "
            "STREAMINSPECTOR_PROXY__PORT manualmente.",
        )

    def _show_https_setup(self) -> None:
        host, port = self._proxy_endpoint()
        dialog = HttpsSetupDialog(
            host,
            port,
            proxy_running=self.proxy_button.isChecked(),
            parent=self,
        )
        self._https_dialogs.append(dialog)
        dialog.finished.connect(lambda: self._https_dialogs.remove(dialog))
        dialog.show()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self._restore_windows_proxy()
        super().closeEvent(event)


def _check_bind_error(host: str, port: int) -> str | None:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
    except OSError as exc:
        return str(exc)
    return None
