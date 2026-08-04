from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QWidget,
)

from streaminspector.core.events import HttpFlowCaptured

# Rol donde `AdvancedMainWindow` guarda el `flow_id` de cada fila. La barra de
# filtros lo necesita para mapear filas visuales (post-sort) a flows y así
# ocultar las correctas cuando la tabla está ordenada por alguna columna.
FLOW_ID_DATA_ROLE = Qt.ItemDataRole.UserRole + 1


class TrafficFilterBar(QWidget):
    """Combined client-side filters for the current traffic table."""

    def __init__(
        self,
        table: QTableWidget,
        flows: Callable[[], list[HttpFlowCaptured]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._table = table
        self._flows = flows

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)

        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("Buscar URL, host, ruta, cabeceras…")
        self.text_filter.setClearButtonEnabled(True)

        self.domain_filter = QComboBox()
        self.method_filter = QComboBox()
        self.status_filter = QComboBox()
        self.type_filter = QComboBox()
        self.result_label = QLabel("0 de 0")

        self.method_filter.addItems(
            [
                "Todos",
                "GET",
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "HEAD",
                "OPTIONS",
            ]
        )
        self.status_filter.addItems(["Todos", "2xx", "3xx", "4xx", "5xx", "Sin respuesta"])
        self.type_filter.addItems(
            ["Todos", "JSON", "HTML", "JavaScript", "CSS", "Imagen", "Audio/Vídeo", "Otro"]
        )

        reset_button = QPushButton("Restablecer")
        reset_button.clicked.connect(self.reset)

        layout.addWidget(QLabel("Filtro"))
        layout.addWidget(self.text_filter, 1)
        layout.addWidget(QLabel("Dominio"))
        layout.addWidget(self.domain_filter)
        layout.addWidget(QLabel("Método"))
        layout.addWidget(self.method_filter)
        layout.addWidget(QLabel("Estado"))
        layout.addWidget(self.status_filter)
        layout.addWidget(QLabel("Tipo"))
        layout.addWidget(self.type_filter)
        layout.addWidget(reset_button)
        layout.addWidget(self.result_label)

        self.text_filter.textChanged.connect(self.apply)
        self.domain_filter.currentIndexChanged.connect(self.apply)
        self.method_filter.currentIndexChanged.connect(self.apply)
        self.status_filter.currentIndexChanged.connect(self.apply)
        self.type_filter.currentIndexChanged.connect(self.apply)
        self.refresh_options()

    def refresh_options(self) -> None:
        selected = self.domain_filter.currentText()
        domains = sorted({flow.host for flow in self._flows() if flow.host})
        self.domain_filter.blockSignals(True)
        self.domain_filter.clear()
        self.domain_filter.addItem("Todos")
        self.domain_filter.addItems(domains)
        index = self.domain_filter.findText(selected)
        self.domain_filter.setCurrentIndex(index if index >= 0 else 0)
        self.domain_filter.blockSignals(False)
        self.apply()

    def reset(self) -> None:
        self.text_filter.clear()
        for combo in (
            self.domain_filter,
            self.method_filter,
            self.status_filter,
            self.type_filter,
        ):
            combo.setCurrentIndex(0)
        self.apply()

    def apply(self) -> None:
        flows_by_id = {flow.flow_id: flow for flow in self._flows()}
        visible = 0
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            flow_id = str(item.data(FLOW_ID_DATA_ROLE) or "") if item is not None else ""
            flow = flows_by_id.get(flow_id)
            if flow is None:
                # Fila sin flow_id (p.ej. importada de HAR sin reasignación).
                # La dejamos visible para no perder datos sin querer.
                visible += 1
                continue
            matches = self._matches(flow)
            self._table.setRowHidden(row, not matches)
            if matches:
                visible += 1
        self.result_label.setText(f"{visible} de {self._table.rowCount()}")

    def _matches(self, flow: HttpFlowCaptured) -> bool:
        text = self.text_filter.text().strip().casefold()
        domain = self.domain_filter.currentText()
        method = self.method_filter.currentText()
        status = self.status_filter.currentText()
        content_type = self.type_filter.currentText()

        if text and text not in _searchable_text(flow):
            return False
        if domain != "Todos" and flow.host != domain:
            return False
        if method != "Todos" and flow.method.upper() != method:
            return False
        if not _status_matches(flow.status_code, status):
            return False
        return _type_matches(flow.content_type, content_type)


def _searchable_text(flow: HttpFlowCaptured) -> str:
    headers = " ".join(
        f"{name} {value}"
        for name, value in (*flow.request_headers, *flow.response_headers)
    )
    return " ".join(
        (
            flow.method,
            flow.url,
            flow.host,
            flow.path,
            flow.reason,
            flow.content_type,
            headers,
        )
    ).casefold()


def _status_matches(status_code: int | None, selected: str) -> bool:
    if selected == "Todos":
        return True
    if selected == "Sin respuesta":
        return status_code is None
    if status_code is None:
        return False
    return status_code // 100 == int(selected[0])


def _type_matches(content_type: str, selected: str) -> bool:
    if selected == "Todos":
        return True
    mime = content_type.split(";", 1)[0].strip().lower()
    if selected == "JSON":
        return mime == "application/json" or mime.endswith("+json")
    if selected == "HTML":
        return mime in {"text/html", "application/xhtml+xml"}
    if selected == "JavaScript":
        return "javascript" in mime or mime in {"application/ecmascript", "text/ecmascript"}
    if selected == "CSS":
        return mime == "text/css"
    if selected == "Imagen":
        return mime.startswith("image/")
    if selected == "Audio/Vídeo":
        return mime.startswith(("audio/", "video/"))
    return bool(mime) and not any(
        (
            mime == "application/json" or mime.endswith("+json"),
            mime in {"text/html", "application/xhtml+xml", "text/css"},
            "javascript" in mime,
            mime.startswith(("image/", "audio/", "video/")),
        )
    )
