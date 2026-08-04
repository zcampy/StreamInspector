from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox

from streaminspector import __version__
from streaminspector.core.events import EventBus, HttpFlowCaptured, StatusMessage
from streaminspector.exporting import (
    count_sensitive_headers,
    flows_to_csv,
    flows_to_har,
    flows_to_json,
    format_request,
)
from streaminspector.gui.compare_dialog import CompareDialog
from streaminspector.gui.main_window import (
    _decode_body,
    _format_headers,
    _pretty_json,
)
from streaminspector.gui.performance_dialog import PerformanceDialog
from streaminspector.gui.replay_dialog import ReplayDialog
from streaminspector.gui.session_window import SessionMainWindow
from streaminspector.media_utils import (
    build_ffmpeg_command,
    is_m3u8_response,
    is_video_url,
)
from streaminspector.storage import StorageService

FLOW_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class AdvancedMainWindow(SessionMainWindow):
    """Traffic window with sorting, exports and contextual request actions."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self._replay_dialogs: list[ReplayDialog] = []
        self._compare_dialogs: list[CompareDialog] = []
        self._performance_dialogs: list[PerformanceDialog] = []
        self._m3u8_dialogs: list = []
        self._install_advanced_actions()
        self.statusBar().showMessage(
            "Inicio recomendado en Windows: Iniciar StreamInspector.bat", 12000
        )
        QTimer.singleShot(0, self._show_startup_notice)

    def _install_advanced_actions(self) -> None:
        self.history.setSortingEnabled(True)
        self.history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self._show_context_menu)

        tools_menu = self.menuBar().addMenu("Peticiones")
        replay_action = QAction("Repetir petición seleccionada…", self)
        replay_action.triggered.connect(self._replay_selected)
        tools_menu.addAction(replay_action)
        compare_action = QAction("Comparar capturas…", self)
        compare_action.triggered.connect(self._compare_flows)
        tools_menu.addAction(compare_action)

        analysis_menu = self.menuBar().addMenu("Análisis")
        performance_action = QAction("Rendimiento de la sesión…", self)
        performance_action.triggered.connect(self._show_performance)
        analysis_menu.addAction(performance_action)

        help_menu = self.menuBar().addMenu("Ayuda")
        startup_action = QAction("Cómo iniciar StreamInspector", self)
        startup_action.triggered.connect(lambda: self._show_startup_notice(force=True))
        help_menu.addAction(startup_action)

        export_menu = self.menuBar().addMenu("Exportar")
        for label, extension, exporter in (
            ("CSV…", "csv", flows_to_csv),
            ("JSON…", "json", flows_to_json),
            ("HAR…", "har", flows_to_har),
        ):
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, ext=extension, fn=exporter: self._export_visible(ext, fn)
            )
            export_menu.addAction(action)

        for row, flow in enumerate(self._flows):
            self._attach_flow_id(row, flow.flow_id)

    def _show_startup_notice(self, force: bool = False) -> None:
        settings = QSettings("StreamInspector", "StreamInspector")
        key = f"startup_notice/{__version__}"
        if not force and settings.value(key, False, type=bool):
            return
        QMessageBox.information(
            self,
            "Inicio de StreamInspector",
            "En Windows inicia siempre la aplicación mediante "
            "'Iniciar StreamInspector.bat'.\n\n"
            "El lanzador detecta Python, repara un entorno .venv incompleto, "
            "instala PySide6 y actualiza las dependencias automáticamente.",
        )
        settings.setValue(key, True)

    def _append_flow(self, event: HttpFlowCaptured) -> None:
        sorting = self.history.isSortingEnabled()
        self.history.setSortingEnabled(False)
        super()._append_flow(event)
        row = self.history.rowCount() - 1
        self._attach_flow_id(row, event.flow_id)
        if is_video_url(event.url, event.content_type):
            self._highlight_video_row(row)
        self.history.setSortingEnabled(sorting)

    def _highlight_video_row(self, row: int) -> None:
        """Marca una fila como captura de vídeo: negrita + tooltip explicativo.

        Las columnas que ya muestran contenido (Método, Estado, Path) reciben
        el bold; el resto solo el tooltip para no romper la legibilidad.
        """
        columns_to_bold = (1, 2, 4)  # método, estado, ruta
        for column in range(self.history.columnCount()):
            item = self.history.item(row, column)
            if item is None:
                continue
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            if column in columns_to_bold:
                # Color de acento (cian) para que las filas de vídeo resalten
                # al escanear la tabla con la vista.
                item.setForeground(Qt.GlobalColor.cyan)
            item.setToolTip(
                "URL de vídeo/audio (m3u8, mp4, hls…). "
                "Click derecho → Copiar como comando ffmpeg para descargarla."
            )

    def _attach_flow_id(self, row: int, flow_id: str) -> None:
        item = self.history.item(row, 0)
        if item is not None:
            item.setData(FLOW_ID_ROLE, flow_id)

    def _selected_flow(self) -> HttpFlowCaptured | None:
        row = self.history.currentRow()
        if row < 0:
            return None
        item = self.history.item(row, 0)
        flow_id = item.data(FLOW_ID_ROLE) if item is not None else None
        return next((flow for flow in self._flows if flow.flow_id == flow_id), None)

    def _show_selected_flow(self) -> None:
        flow = self._selected_flow()
        if flow is None:
            return
        request_headers = _format_headers(flow.request_headers)
        response_headers = _format_headers(flow.response_headers)
        response_body = _decode_body(flow.response_body)
        self.request_view.setPlainText(format_request(flow))
        self.response_view.setPlainText(
            f"{flow.http_version} {flow.status_code or ''} {flow.reason}\n\n"
            f"{response_headers}\n\n{response_body}"
        )
        self.headers_view.setPlainText(
            f"REQUEST\n{request_headers}\n\nRESPONSE\n{response_headers}"
        )
        self.body_view.setPlainText(response_body)
        self.json_view.setPlainText(_pretty_json(response_body))

    def _show_context_menu(self, position: QPoint) -> None:
        flow = self._selected_flow()
        if flow is None:
            return
        menu = QMenu(self)

        # Acciones específicas para URLs de vídeo/audio. Es lo que el
        # usuario suele necesitar cuando navega streamers que ocultan
        # sus fuentes: la URL está en la captura, solo hay que cazarla.
        if is_video_url(flow.url, flow.content_type):
            menu.addAction("▶ Copiar como comando ffmpeg").triggered.connect(
                lambda: QApplication.clipboard().setText(
                    build_ffmpeg_command(flow.url, flow.content_type)
                )
            )
            # Si el cuerpo parece m3u8, ofrece ver los segmentos parseados.
            if is_m3u8_response(flow.content_type, flow.response_body):
                menu.addAction("▷ Ver segmentos m3u8").triggered.connect(
                    lambda: self._open_m3u8_dialog(flow)
                )
            menu.addSeparator()

        replay_action = menu.addAction("Repetir petición…")
        replay_action.triggered.connect(lambda: self._open_replay_dialog(flow))
        compare_action = menu.addAction("Comparar capturas…")
        compare_action.triggered.connect(self._compare_flows)
        menu.addSeparator()
        actions = (
            ("Copiar URL", flow.url),
            ("Copiar cabeceras de petición", _format_headers(flow.request_headers)),
            ("Copiar cabeceras de respuesta", _format_headers(flow.response_headers)),
            ("Copiar cuerpo de petición", _decode_body(flow.request_body)),
            ("Copiar cuerpo de respuesta", _decode_body(flow.response_body)),
            ("Copiar petición completa", format_request(flow)),
        )
        for label, text in actions:
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, value=text: QApplication.clipboard().setText(value)
            )
        menu.exec(self.history.viewport().mapToGlobal(position))

    def _open_m3u8_dialog(self, flow: HttpFlowCaptured) -> None:
        """Parsea la respuesta m3u8 y abre el diálogo con sus segmentos."""
        from streaminspector.gui.m3u8_dialog import M3u8Dialog
        from streaminspector.media_utils import parse_m3u8

        text = flow.response_body.decode("utf-8", errors="replace")
        playlist = parse_m3u8(text, base_url=flow.url)
        dialog = M3u8Dialog(playlist, flow.url, self)
        self._m3u8_dialogs.append(dialog)
        dialog.finished.connect(lambda: self._m3u8_dialogs.remove(dialog))
        dialog.show()

    def _replay_selected(self) -> None:
        flow = self._selected_flow()
        if flow is None:
            QMessageBox.information(self, "Repetir petición", "Selecciona una captura primero.")
            return
        self._open_replay_dialog(flow)

    def _open_replay_dialog(self, flow: HttpFlowCaptured) -> None:
        dialog = ReplayDialog(flow, self)
        self._replay_dialogs.append(dialog)
        dialog.finished.connect(lambda: self._replay_dialogs.remove(dialog))
        dialog.show()

    def _compare_flows(self) -> None:
        flows = self._visible_flows()
        if len(flows) < 2:
            QMessageBox.information(
                self, "Comparar capturas", "Se necesitan al menos dos capturas visibles."
            )
            return
        dialog = CompareDialog(flows, self)
        self._compare_dialogs.append(dialog)
        dialog.finished.connect(lambda: self._compare_dialogs.remove(dialog))
        dialog.show()

    def _show_performance(self) -> None:
        flows = self._visible_flows()
        if not flows:
            QMessageBox.information(
                self, "Rendimiento", "No hay capturas visibles para analizar."
            )
            return
        dialog = PerformanceDialog(flows, self)
        self._performance_dialogs.append(dialog)
        dialog.finished.connect(lambda: self._performance_dialogs.remove(dialog))
        dialog.show()

    def _visible_flows(self) -> list[HttpFlowCaptured]:
        visible_ids: list[str] = []
        for row in range(self.history.rowCount()):
            if self.history.isRowHidden(row):
                continue
            item = self.history.item(row, 0)
            if item is not None and item.data(FLOW_ID_ROLE):
                visible_ids.append(str(item.data(FLOW_ID_ROLE)))
        by_id = {flow.flow_id: flow for flow in self._flows}
        return [by_id[flow_id] for flow_id in visible_ids if flow_id in by_id]

    def _export_visible(self, extension: str, exporter) -> None:
        flows = self._visible_flows()
        if not flows:
            QMessageBox.information(self, "Exportar", "No hay capturas visibles para exportar.")
            return
        # Antes de pedir nombre de archivo: si los flows contienen
        # headers sensibles (Authorization, Cookie, etc.), preguntamos
        # al usuario si quiere incluirlos o sanitizarlos. Esto evita
        # que un export filtrado a un repo público (HAR/JSON) acabe
        # exponiendo tokens OAuth, cookies de sesión, etc.
        include_secrets = self._confirm_export_secrets(flows, extension)
        if include_secrets is None:
            return  # usuario canceló
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar capturas",
            f"streaminspector.{extension}",
            f"Archivo {extension.upper()} (*.{extension})",
        )
        if not filename:
            return
        path = Path(filename)
        try:
            # CSV no tiene headers, así que `include_secrets` es no-op
            # en `flows_to_csv` pero lo pasamos por simetría.
            if extension == "csv":
                payload = exporter(flows)
            else:
                payload = exporter(flows, include_secrets=include_secrets)
            path.write_text(payload, encoding="utf-8", newline="")
        except OSError as exc:
            QMessageBox.critical(self, "Error de exportación", str(exc))
            return
        suffix = "" if include_secrets else " (headers sensibles sanitizados)"
        self._event_bus.publish(
            StatusMessage(
                message=(
                    f"Exportadas {len(flows)} capturas a {path.name}{suffix}"
                )
            )
        )

    def _confirm_export_secrets(
        self, flows: list[HttpFlowCaptured], extension: str
    ) -> bool | None:
        """Diálogo que pregunta qué hacer con los headers sensibles del export.

        Devuelve True si el usuario quiere incluirlos, False si prefiere
        sanitizarlos, None si canceló.

        Para CSV, que no incluye headers, devuelve True sin preguntar
        (la opción de sanitizar no aplicaría).
        """
        if extension == "csv":
            return True
        count = count_sensitive_headers(flows)
        if count == 0:
            return True
        message = (
            f"Vas a exportar {len(flows)} capturas a un archivo .{extension}.\n\n"
            f"Contienen {count} headers sensibles (Authorization, Cookie, etc.) "
            f"que podrían incluir tokens OAuth, cookies de sesión u otros secretos.\n\n"
            f"¿Cómo quieres proceder?\n\n"
            f"  • Sí, incluir: el archivo se genera TAL CUAL. NO lo subas a "
            f"ningún sitio público sin revisarlo antes.\n"
            f"  • No, sanitizar: los valores sensibles se reemplazan por "
            f"'***REDACTED***'. El archivo es seguro para compartir.\n"
            f"  • Cancelar: no exportes nada."
        )
        reply = QMessageBox.question(
            self,
            "Exportar capturas con secretos",
            message,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,  # default seguro
        )
        if reply == QMessageBox.StandardButton.Yes:
            return True
        if reply == QMessageBox.StandardButton.No:
            return False
        return None
