from __future__ import annotations

import socket
from urllib.parse import urlparse

from PySide6.QtCore import QSettings, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import QInputDialog, QMessageBox

from streaminspector.browser_launcher import (
    LaunchedBrowser,
    default_browser,
    find_browsers,
    launch_browser,
)
from streaminspector.capture_policy import CaptureMode, save_capture_policy
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
    ca_certificate_generated,
    ca_certificate_installed,
    enable_system_proxy,
    install_ca_certificate,
    restore_system_proxy,
    system_proxy_supported,
)

DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 8080

# Tiempo que tarda mitmproxy en generar el .cer la primera vez. Lo esperamos
# con un QTimer.singleShot antes de comprobar/instalar para no spamear status.
CA_INSTALL_DELAY_MS = 2000


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
        # Handle al navegador dedicado lanzado (None si no hay ninguno abierto).
        self._launched_browser: LaunchedBrowser | None = None
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

        # --- Navegador dedicado para captura aislada ----------------------
        # Lanza una instancia nueva del navegador con el proxy configurado
        # por proceso (--proxy-server) y un perfil limpio. El resto del
        # sistema NO se ve afectado — solo este navegador pasa por mitmproxy.
        menu.addSeparator()
        self._scan_web_action = QAction(
            "Escanear una web específica…", self
        )
        self._scan_web_action.triggered.connect(self._scan_specific_web)
        menu.addAction(self._scan_web_action)
        self._open_browser_action = QAction(
            "Abrir navegador dedicado para captura…", self
        )
        self._open_browser_action.triggered.connect(self._open_dedicated_browser)
        menu.addAction(self._open_browser_action)
        self._close_browser_action = QAction(
            "Cerrar navegador de captura", self
        )
        self._close_browser_action.triggered.connect(self._close_dedicated_browser)
        self._close_browser_action.setEnabled(False)
        menu.addAction(self._close_browser_action)

    def _proxy_endpoint(self) -> tuple[str, int]:
        return _sanitize_endpoint(
            self._proxy_settings.value("proxy/host", DEFAULT_PROXY_HOST),
            self._proxy_settings.value("proxy/port", DEFAULT_PROXY_PORT),
        )

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
            # Intentar instalar el CA de mitmproxy en el cert store del usuario
            # actual (no requiere admin). Lo diferimos un poco para dar tiempo
            # a que mitmproxy genere el .cer en la primera ejecución.
            if system_proxy_supported() and not ca_certificate_generated():
                QTimer.singleShot(
                    CA_INSTALL_DELAY_MS, self._try_auto_install_ca_certificate
                )
            else:
                self._try_auto_install_ca_certificate()
        else:
            self._restore_windows_proxy()
            # Si el proxy se detiene, cerramos también el navegador dedicado
            # (si lo hay) para no dejar al usuario con una ventana zombie
            # cuyo tráfico ya no se está capturando.
            self._close_dedicated_browser(silent=True)

    def _try_auto_install_ca_certificate(self) -> None:
        """Si el cert de mitmproxy aún no está en el store del usuario, lo instala.

        Es seguro llamarlo varias veces: si el cert ya está, no hace nada.
        Si algo falla, lo reporta en la status bar sin romper el flujo principal.
        """
        if not system_proxy_supported():
            return
        result = install_ca_certificate()
        if result.already_present:
            return
        if result.installed:
            self._event_bus.publish(
                StatusMessage(
                    message=(
                        "Certificado de mitmproxy instalado automáticamente en el "
                        "store del usuario actual. HTTPS ya debería confiar en él."
                    ),
                    level="info",
                )
            )
        elif result.detail:
            self._event_bus.publish(
                StatusMessage(
                    message=(
                        f"No se pudo instalar el certificado automáticamente: "
                        f"{result.detail}. Usa Proxy > Configurar navegador y HTTPS…"
                    ),
                    level="error",
                )
            )

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

    # --------------------------------- navegador dedicado

    def _scan_specific_web(self) -> None:
        """Orquesta la captura enfocada a UNA sola web.

        Pasos automáticos:
        1. Pide al usuario la URL a escanear.
        2. Extrae el dominio y lo añade a la whitelist.
        3. Cambia el modo a WHITELIST (si no lo estaba).
        4. Persiste la policy.
        5. Arranca el proxy si está apagado.
        6. Abre el navegador dedicado apuntando a esa URL.

        Si el usuario quiere escanear otra web, repite el flujo y se
        acumula en la whitelist. Si quiere limpiar la whitelist, lo
        hace desde Captura > Modo de captura > Configurar dominios
        permitidos…
        """
        policy = self._storage.capture_policy
        if policy is None:
            # Fallback defensivo: en tests o scripts puede no haber policy.
            QMessageBox.warning(
                self,
                "Sin política de captura",
                "No se encontró la política de captura. Reinicia StreamInspector.",
            )
            return

        url, accepted = QInputDialog.getText(
            self,
            "Escanear una web específica",
            "URL de la web a escanear (solo se capturará este dominio):",
            text="https://",
        )
        if not accepted:
            return
        domain = extract_domain_for_whitelist(url.strip())
        if domain is None:
            QMessageBox.warning(
                self,
                "URL no válida",
                f"La URL debe empezar por http:// o https:// y tener un "
                f"dominio válido.\n\nRecibido: {url}",
            )
            return

        # Acumular en la whitelist (no destructivo: lo que ya estaba se
        # conserva). Si ya estaba este dominio, lo detectamos para que
        # el status no diga "+1" cuando en realidad era un duplicado.
        already = domain in policy.whitelisted_domains
        if not already:
            policy.whitelisted_domains = (domain,) + tuple(
                d for d in policy.whitelisted_domains if d != domain
            )
        policy.mode = CaptureMode.WHITELIST
        save_capture_policy(self._capture_settings, policy)

        # Refresca el status de la UI (muestra el nuevo modo + el
        # conteo de dominios en la status bar).
        if hasattr(self, "_refresh_capture_status"):
            self._refresh_capture_status()
        if hasattr(self, "_mode_whitelist_action"):
            self._mode_whitelist_action.setChecked(True)

        self._event_bus.publish(
            StatusMessage(
                message=(
                    f"Whitelist: {'+' if not already else ''}"
                    f"{domain}. Modo whitelist activo."
                )
            )
        )

        # Arranca el proxy si está apagado.
        if not self.proxy_button.isChecked():
            self._toggle_proxy(True)

        # Lanza el navegador dedicado apuntando a la URL.
        # Reconstruimos la URL normalizada (scheme + host + path, sin
        # query ni fragment) para evitar tokens en la barra del navegador.
        parsed = urlparse(url.strip())
        normalized = f"{parsed.scheme}://{parsed.hostname}{parsed.path or '/'}"
        self._open_dedicated_browser_at(normalized)

    def _open_dedicated_browser_at(self, url: str) -> None:
        """Como `_open_dedicated_browser`, pero abre `url` en la nueva pestaña.

        Si no hay navegador ya lanzado, crea uno. Si ya hay uno, simplemente
        le pasa la URL al sistema para que la abra (que en Windows con un
        navegador por defecto, abre en la instancia activa si puede).
        """
        if self._launched_browser is not None and self._launched_browser.is_alive:
            # Ya hay un navegador dedicado. Le pedimos al sistema que
            # abra la URL — el SO la dirigirá a la instancia por defecto
            # (que es la nuestra, recién lanzada).
            QDesktopServices.openUrl(QUrl(url))
            self._event_bus.publish(
                StatusMessage(
                    message=f"URL abierta en el navegador de captura: {url}"
                )
            )
            return
        # No hay navegador: lanza uno nuevo y, en cuanto esté listo,
        # abre la URL. Como `launch_browser` es síncrono (Popen) y el
        # navegador tarda unos ms en cargar la home, abrimos la URL
        # justo después de lanzar.
        self._open_dedicated_browser()
        launched = self._launched_browser
        if launched is not None and launched.is_alive:
            # Programar la apertura de la URL un poco después para dar
            # tiempo a que el navegador esté listo.
            QTimer.singleShot(1500, lambda: QDesktopServices.openUrl(QUrl(url)))

    def _open_dedicated_browser(self) -> None:
        """Lanza una instancia nueva del navegador con el proxy configurado.

        El navegador se lanza con --proxy-server=http://host:port (por
        proceso, NO por configuración global de Windows) y un perfil
        temporal, así que:
        - El usuario puede seguir con su navegador normal sin
          interferencias.
        - Solo el tráfico de esta instancia va a StreamInspector.
        - El perfil se borra al cerrar, sin contaminar el perfil normal.
        """
        if not self.proxy_button.isChecked():
            QMessageBox.information(
                self,
                "Proxy detenido",
                "Activa el proxy primero (botón Proxy OFF → ON). El "
                "navegador dedicado necesita el proxy en marcha para "
                "que StreamInspector capture su tráfico.",
            )
            return
        if self._launched_browser is not None and self._launched_browser.is_alive:
            QMessageBox.information(
                self,
                "Navegador ya abierto",
                f"Ya hay un {self._launched_browser.browser.name} "
                f"abierto para captura (PID {self._launched_browser.pid}). "
                "Ciérralo antes de abrir otro.",
            )
            return

        # Limpia un handle muerto (el proceso murió pero no lo cerramos)
        if self._launched_browser is not None and not self._launched_browser.is_alive:
            self._launched_browser.close()
            self._launched_browser = None

        host, port = self._proxy_endpoint()
        browser = default_browser()
        if browser is None:
            browsers = find_browsers()
            if not browsers:
                QMessageBox.warning(
                    self,
                    "Sin navegador compatible",
                    "No se encontró Microsoft Edge ni Google Chrome "
                    "instalados. El launcher solo soporta navegadores "
                    "basados en Chromium por ahora.",
                )
                return
            browser = browsers[0]

        # Si el CA de mitmproxy está en el cert store del usuario, NO
        # necesitamos --ignore-certificate-errors: la validación TLS
        # funcionará normal.
        ignore_cert_errors = not ca_certificate_installed()

        try:
            launched = launch_browser(
                browser, host, port, ignore_cert_errors=ignore_cert_errors
            )
        except (OSError, FileNotFoundError, NotImplementedError) as exc:
            QMessageBox.warning(
                self,
                "No se pudo abrir el navegador",
                f"Falló el lanzamiento de {browser.name}: {exc}",
            )
            return
        self._launched_browser = launched
        self._close_browser_action.setEnabled(True)
        # Status bar: indica que el navegador dedicado está activo.
        cert_note = (
            " (HTTPS sin validar)"
            if ignore_cert_errors
            else " (HTTPS validado por CA de mitmproxy)"
        )
        self.statusBar().showMessage(
            f"{browser.name} abierto para captura (PID {launched.pid}){cert_note}",
            8000,
        )
        self._event_bus.publish(
            StatusMessage(
                message=(
                    f"{browser.name} dedicado abierto. Su tráfico va "
                    f"a StreamInspector; el resto del sistema NO."
                )
            )
        )
        # Monitorea si el usuario cierra el navegador desde fuera.
        self._browser_watchdog = QTimer(self)
        self._browser_watchdog.setInterval(2000)
        self._browser_watchdog.timeout.connect(self._check_launched_browser)
        self._browser_watchdog.start()

    def _close_dedicated_browser(self, silent: bool = False) -> None:
        """Cierra el navegador dedicado y limpia el perfil temporal."""
        launched = self._launched_browser
        if launched is None:
            return
        was_alive = launched.close()
        self._launched_browser = None
        self._close_browser_action.setEnabled(False)
        if hasattr(self, "_browser_watchdog") and self._browser_watchdog is not None:
            self._browser_watchdog.stop()
            self._browser_watchdog = None
        if not silent and was_alive:
            self._event_bus.publish(
                StatusMessage(message="Navegador de captura cerrado.")
            )

    def _check_launched_browser(self) -> None:
        """Si el usuario cerró el navegador desde fuera, actualiza la UI."""
        launched = self._launched_browser
        if launched is None:
            return
        if not launched.is_alive:
            # El proceso murió por sí solo (usuario cerró la ventana).
            self._close_dedicated_browser(silent=True)
            self._event_bus.publish(
                StatusMessage(
                    message=(
                        f"{launched.browser.name} se cerró. Su tráfico "
                        f"ya no se está capturando."
                    )
                )
            )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        # Cerrar el navegador dedicado si está abierto, antes de restaurar
        # el proxy. No queremos dejar procesos zombie al salir de la app.
        self._close_dedicated_browser(silent=True)
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


def _sanitize_endpoint(host: object, port: object) -> tuple[str, int]:
    """Devuelve (host, port) saneado, cayendo a los defaults ante entrada corrupta.

    Acepta los valores "crudos" que devuelve `QSettings.value` (que pueden ser
    cualquier cosa si el usuario editó el registro a mano o hubo un cierre
    abrupto). Sin sanitización, `int("abc")` o un puerto fuera de rango
    reventarían la UI al primer `Proxy ON`.
    """
    clean_host = str(host or "").strip() or DEFAULT_PROXY_HOST
    try:
        clean_port = int(port)
    except (TypeError, ValueError):
        clean_port = DEFAULT_PROXY_PORT
    if not 1 <= clean_port <= 65535:
        clean_port = DEFAULT_PROXY_PORT
    return clean_host, clean_port


def extract_domain_for_whitelist(url: str) -> str | None:
    """Extrae el dominio normalizado de una URL para añadirlo a la whitelist.

    Devuelve el dominio en minúsculas y sin 'www.' inicial, o None si la
    URL no es parseable como http/https con host.

    Función pura (sin UI) para que se pueda testear y reutilizar.

    Ejemplos:
        >>> extract_domain_for_whitelist("https://fctv33hd.fit/evento-x")
        'fctv33hd.fit'
        >>> extract_domain_for_whitelist("HTTPS://WWW.FCTV33HD.FIT/EVENTO?token=abc")
        'fctv33hd.fit'
        >>> extract_domain_for_whitelist("ftp://example.com")
        None
        >>> extract_domain_for_whitelist("not a url")
        None
        >>> extract_domain_for_whitelist("")
        None
    """
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.hostname
    if not host:
        return None
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None
