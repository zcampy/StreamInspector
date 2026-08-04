from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QInputDialog, QMessageBox

from streaminspector.ad_presets import COMMON_AD_DOMAINS, merge_ad_preset
from streaminspector.capture_policy import CapturePolicy, normalize_domains
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
        domains = normalize_domains(
            str(self._capture_settings.value("capture/excluded_domains", ""))
        )
        self._capture_policy = CapturePolicy(
            paused=False,
            excluded_domains=domains,
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

    def _set_omit_static(self, enabled: bool) -> None:
        self._capture_policy.omit_static = enabled
        self._capture_settings.setValue("capture/omit_static", enabled)
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
        self._capture_settings.setValue(
            "capture/excluded_domains", "\n".join(domains)
        )
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
        self._capture_settings.setValue(
            "capture/excluded_domains", "\n".join(merged)
        )
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
        domains = "\n".join(self._capture_policy.excluded_domains) or "Ninguno"
        QMessageBox.information(
            self,
            "Política de captura",
            f"Estado: {'pausada' if self._capture_policy.paused else 'activa'}\n"
            f"Omitir recursos estáticos: "
            f"{'sí' if self._capture_policy.omit_static else 'no'}\n\n"
            f"Dominios excluidos:\n{domains}",
        )

    def _refresh_capture_status(self) -> None:
        if not hasattr(self, "pause_capture_action"):
            return
        parts = ["Captura pausada" if self._capture_policy.paused else "Captura activa"]
        if self._capture_policy.omit_static:
            parts.append("sin estáticos")
        if self._capture_policy.excluded_domains:
            parts.append(f"{len(self._capture_policy.excluded_domains)} dominios excluidos")
        self.statusBar().showMessage(" · ".join(parts), 6000)

    def _on_flow_captured(self, event: HttpFlowCaptured) -> None:
        if not self._capture_policy.accepts(event):
            return
        super()._on_flow_captured(event)
