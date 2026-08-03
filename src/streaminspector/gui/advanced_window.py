from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox

from streaminspector.core.events import EventBus, HttpFlowCaptured, StatusMessage
from streaminspector.exporting import (
    flows_to_csv,
    flows_to_har,
    flows_to_json,
    format_request,
)
from streaminspector.gui.main_window import (
    _decode_body,
    _format_headers,
    _pretty_json,
)
from streaminspector.gui.session_window import SessionMainWindow
from streaminspector.storage import StorageService

FLOW_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class AdvancedMainWindow(SessionMainWindow):
    """Traffic window with sorting, exports and contextual copy actions."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self._install_advanced_actions()

    def _install_advanced_actions(self) -> None:
        self.history.setSortingEnabled(True)
        self.history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self._show_context_menu)

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

    def _append_flow(self, event: HttpFlowCaptured) -> None:
        sorting = self.history.isSortingEnabled()
        self.history.setSortingEnabled(False)
        super()._append_flow(event)
        self._attach_flow_id(self.history.rowCount() - 1, event.flow_id)
        self.history.setSortingEnabled(sorting)

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
        request_body = _decode_body(flow.request_body)
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
            path.write_text(exporter(flows), encoding="utf-8", newline="")
        except OSError as exc:
            QMessageBox.critical(self, "Error de exportación", str(exc))
            return
        self._event_bus.publish(
            StatusMessage(message=f"Exportadas {len(flows)} capturas a {path.name}")
        )
