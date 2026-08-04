from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QInputDialog, QMessageBox

from streaminspector.ad_presets import (
    COMMON_AD_DOMAINS,
    COMMON_STREAM_CDN_DOMAINS,
    merge_ad_preset,
    merge_stream_preset,
)
from streaminspector.capture_policy import (
    CaptureMode,
    CapturePolicy,
    normalize_domains,
    save_capture_policy,
)
from streaminspector.core.events import EventBus, HttpFlowCaptured, StatusMessage
from streaminspector.gui.proxy_window import ProxyConfiguredWindow
from streaminspector.storage import StorageService


class SelectiveCaptureWindow(ProxyConfiguredWindow):
    """Main window with persistent capture acceptance controls."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        self._capture_settings = QSettings("StreamInspector", "StreamInspector")
        # Si el storage ya tiene una policy registrada (porque `main.py`
        # la creó y la pasó con `set_capture_filter(policy=...)`), la
        # reusamos. Esto garantiza que storage, proxy y UI compartan
        # la MISMA instancia y vean los cambios de los demás al instante.
        existing_policy = storage.capture_policy
        if existing_policy is not None:
            self._capture_policy = existing_policy
        else:
            # Fallback: la UI crea su propia policy. Lo mantenemos para
            # backwards compat con tests/scripts que instancian el
            # window directamente sin pasar por `main.py`.
            self._capture_policy = CapturePolicy(
                paused=False,
                excluded_domains=normalize_domains(
                    str(
                        self._capture_settings.value(
                            "capture/excluded_domains", ""
                        )
                    )
                ),
                omit_static=self._capture_settings.value(
                    "capture/omit_static", False, type=bool
                ),
            )
            storage.set_capture_filter(self._capture_policy.accepts)
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self._install_capture_actions()
        self._refresh_capture_status()

    def _install_capture_actions(self) -> None:
        menu = self.menuBar().addMenu("Captura")

        # Submenú "Modo de captura" — toggle entre ALL y WHITELIST.
        # Esto decide si el proxy intercepta todo el sistema o solo
        # los dominios de la whitelist (clave para privacidad).
        self.mode_menu = menu.addMenu("Modo de captura")
        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)
        self._mode_all_action = QAction("Capturar todo el sistema", self)
        self._mode_all_action.setCheckable(True)
        self._mode_all_action.setChecked(
            self._capture_policy.mode is CaptureMode.ALL
        )
        self._mode_all_action.triggered.connect(
            lambda: self._set_capture_mode(CaptureMode.ALL)
        )
        self.mode_group.addAction(self._mode_all_action)
        self.mode_menu.addAction(self._mode_all_action)
        self._mode_whitelist_action = QAction(
            "Solo dominios en la whitelist", self
        )
        self._mode_whitelist_action.setCheckable(True)
        self._mode_whitelist_action.setChecked(
            self._capture_policy.mode is CaptureMode.WHITELIST
        )
        self._mode_whitelist_action.triggered.connect(
            lambda: self._set_capture_mode(CaptureMode.WHITELIST)
        )
        self.mode_group.addAction(self._mode_whitelist_action)
        self.mode_menu.addAction(self._mode_whitelist_action)
        self.mode_menu.addSeparator()
        whitelist_edit_action = QAction(
            "Configurar dominios permitidos…", self
        )
        whitelist_edit_action.triggered.connect(self._configure_whitelisted_domains)
        self.mode_menu.addAction(whitelist_edit_action)
        whitelist_preset_action = QAction(
            f"Cargar preset de CDNs de stream "
            f"({len(COMMON_STREAM_CDN_DOMAINS)} dominios)…",
            self,
        )
        whitelist_preset_action.triggered.connect(self._load_stream_preset)
        self.mode_menu.addAction(whitelist_preset_action)

        menu.addSeparator()

        self.pause_capture_action = QAction("Pausar captura", self)
        self.pause_capture_action.setCheckable(True)
        self.pause_capture_action.toggled.connect(self._set_capture_paused)
        menu.addAction(self.pause_capture_action)

        self.omit_static_action = QAction("Omitir recursos estáticos", self)
        self.omit_static_action.setCheckable(True)
        self.omit_static_action.setChecked(self._capture_policy.omit_static)
        self.omit_static_action.toggled.connect(self._set_omit_static)
        menu.addAction(self.omit_static_action)

        domains_action = QAction("Configurar dominios excluidos…", self)
        domains_action.triggered.connect(self._configure_excluded_domains)
        menu.addAction(domains_action)

        load_preset_action = QAction(
            "Cargar lista de exclusión de ads (preset)…", self
        )
        load_preset_action.triggered.connect(self._load_ad_preset)
        menu.addAction(load_preset_action)

        menu.addSeparator()
        status_action = QAction("Ver política actual…", self)
        status_action.triggered.connect(self._show_capture_policy)
        menu.addAction(status_action)

    def _set_capture_paused(self, paused: bool) -> None:
        self._capture_policy.paused = paused
        self.pause_capture_action.setText(
            "Reanudar captura" if paused else "Pausar captura"
        )
        self._refresh_capture_status()
        self._event_bus.publish(
            StatusMessage(message="Captura pausada" if paused else "Captura reanudada")
        )

    def _set_capture_mode(self, mode: CaptureMode) -> None:
        """Cambia entre ALL y WHITELIST en caliente (sin reiniciar el proxy).

        Importante: el filtro del `CaptureAddon` ve el cambio al instante
        porque la policy es un objeto mutable compartido.
        """
        if self._capture_policy.mode is mode:
            return
        self._capture_policy.mode = mode
        save_capture_policy(self._capture_settings, self._capture_policy)
        self._refresh_capture_status()
        if mode is CaptureMode.WHITELIST:
            if not self._capture_policy.whitelisted_domains:
                msg = (
                    "Modo whitelist activo. Aún no hay dominios en la "
                    "lista: no se capturará NADA hasta que añadas al "
                    "menos uno (Captura > Modo de captura > Cargar "
                    "preset de CDNs de stream…)."
                )
            else:
                msg = (
                    f"Modo whitelist activo. Solo se capturan "
                    f"{len(self._capture_policy.whitelisted_domains)} "
                    f"dominios. El resto del sistema pasa transparente."
                )
        else:
            msg = (
                "Modo 'capturar todo' activo. StreamInspector "
                "interceptará tráfico de TODAS las apps del sistema "
                "(navegadores, GitHub Desktop, ChatGPT, telemetría…)."
            )
        self._event_bus.publish(StatusMessage(message=msg))

    def _configure_whitelisted_domains(self) -> None:
        current = "\n".join(self._capture_policy.whitelisted_domains)
        value, accepted = QInputDialog.getMultiLineText(
            self,
            "Dominios permitidos (whitelist)",
            "Un dominio por línea. Se incluye el dominio y sus subdominios.\n"
            "Vacío = nada se capturará (modo whitelist sin entradas).",
            current,
        )
        if not accepted:
            return
        domains = normalize_domains(value)
        self._capture_policy.whitelisted_domains = domains
        save_capture_policy(self._capture_settings, self._capture_policy)
        self._refresh_capture_status()
        in_whitelist = (
            self._capture_policy.mode is CaptureMode.WHITELIST
        )
        hint = "Activa" if in_whitelist else (
            "Cambia a Modo whitelist para usarla"
        )
        self._event_bus.publish(
            StatusMessage(
                message=f"Whitelist: {len(domains)} dominios. {hint}."
            )
        )

    def _load_stream_preset(self) -> None:
        """Carga la lista curada de CDNs de stream en la whitelist.

        Aditiva: si el usuario ya tenía dominios propios, se conservan;
        los del preset se añaden al final sin duplicados. Esto es lo que
        el usuario necesita para empezar a cazar streams sin tener que
        escribir nada.
        """
        existing = self._capture_policy.whitelisted_domains
        merged = merge_stream_preset(existing)
        added = len(merged) - len(existing)
        if added == 0:
            self._event_bus.publish(
                StatusMessage(
                    message=(
                        f"El preset de CDNs ya estaba en la whitelist "
                        f"({len(COMMON_STREAM_CDN_DOMAINS)} dominios)."
                    )
                )
            )
            return
        self._capture_policy.whitelisted_domains = merged
        save_capture_policy(self._capture_settings, self._capture_policy)
        self._refresh_capture_status()
        self._event_bus.publish(
            StatusMessage(
                message=(
                    f"Preset de CDNs aplicado: +{added} dominios "
                    f"(total {len(merged)})."
                )
            )
        )

    def _set_omit_static(self, enabled: bool) -> None:
        self._capture_policy.omit_static = enabled
        save_capture_policy(self._capture_settings, self._capture_policy)
        self._refresh_capture_status()

    def _configure_excluded_domains(self) -> None:
        current = "\n".join(self._capture_policy.excluded_domains)
        value, accepted = QInputDialog.getMultiLineText(
            self,
            "Dominios excluidos",
            "Un dominio por línea. También excluye sus subdominios:",
            current,
        )
        if not accepted:
            return
        domains = normalize_domains(value)
        self._capture_policy.excluded_domains = domains
        save_capture_policy(self._capture_settings, self._capture_policy)
        self._refresh_capture_status()
        self._event_bus.publish(
            StatusMessage(message=f"Dominios excluidos: {len(domains)}")
        )

    def _load_ad_preset(self) -> None:
        """Añade la lista curada de ads/trackers a los dominios excluidos.

        La acción es aditiva: si el usuario ya tiene dominios propios, se
        conservan. Los nuevos se añaden al final sin duplicados.
        """
        existing = self._capture_policy.excluded_domains
        merged = merge_ad_preset(existing)
        added = len(merged) - len(existing)
        if added == 0:
            self._event_bus.publish(
                StatusMessage(
                    message=(
                        f"La lista curada ya estaba incluida "
                        f"({len(COMMON_AD_DOMAINS)} dominios)."
                    )
                )
            )
            return
        self._capture_policy.excluded_domains = merged
        save_capture_policy(self._capture_settings, self._capture_policy)
        self._refresh_capture_status()
        self._event_bus.publish(
            StatusMessage(
                message=(
                    f"Preset de ads aplicado: +{added} dominios "
                    f"(total {len(merged)})."
                )
            )
        )

    def _show_capture_policy(self) -> None:
        excluded = "\n".join(self._capture_policy.excluded_domains) or "Ninguno"
        whitelisted = (
            "\n".join(self._capture_policy.whitelisted_domains) or "Ninguno"
        )
        mode_text = (
            "Whitelist (solo estos dominios)"
            if self._capture_policy.mode is CaptureMode.WHITELIST
            else "Capturar todo el sistema"
        )
        QMessageBox.information(
            self,
            "Política de captura",
            f"Modo: {mode_text}\n"
            f"Estado: {'pausada' if self._capture_policy.paused else 'activa'}\n"
            f"Omitir recursos estáticos: "
            f"{'sí' if self._capture_policy.omit_static else 'no'}\n\n"
            f"Dominios en whitelist:\n{whitelisted}\n\n"
            f"Dominios excluidos:\n{excluded}",
        )

    def _refresh_capture_status(self) -> None:
        if not hasattr(self, "pause_capture_action"):
            return
        if self._capture_policy.paused:
            parts = ["Captura pausada"]
        elif self._capture_policy.mode is CaptureMode.WHITELIST:
            n = len(self._capture_policy.whitelisted_domains)
            parts = [f"Modo whitelist ({n} dominios)"]
        else:
            parts = ["Captura todo el sistema"]
        if self._capture_policy.omit_static:
            parts.append("sin estáticos")
        if self._capture_policy.excluded_domains:
            parts.append(
                f"{len(self._capture_policy.excluded_domains)} excluidos"
            )
        self.statusBar().showMessage(" · ".join(parts), 6000)

    def _on_flow_captured(self, event: HttpFlowCaptured) -> None:
        if not self._capture_policy.accepts(event):
            return
        super()._on_flow_captured(event)
