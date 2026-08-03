from __future__ import annotations

import difflib

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.exporting import format_request
from streaminspector.gui.main_window import _decode_body, _format_headers


class CompareDialog(QDialog):
    """Compare two captured HTTP flows side by side and as a unified diff."""

    def __init__(self, flows: list[HttpFlowCaptured], parent=None) -> None:
        super().__init__(parent)
        self._flows = flows
        self.setWindowTitle("Comparar capturas")
        self.resize(1100, 720)

        layout = QVBoxLayout(self)
        selectors = QHBoxLayout()
        self.left_combo = QComboBox()
        self.right_combo = QComboBox()
        for flow in flows:
            label = f"{flow.method} {flow.status_code or '-'} {flow.url}"
            self.left_combo.addItem(label, flow.flow_id)
            self.right_combo.addItem(label, flow.flow_id)
        if len(flows) > 1:
            self.right_combo.setCurrentIndex(1)

        selectors.addWidget(QLabel("Captura A"))
        selectors.addWidget(self.left_combo, 1)
        selectors.addWidget(QLabel("Captura B"))
        selectors.addWidget(self.right_combo, 1)
        layout.addLayout(selectors)

        panes = QHBoxLayout()
        self.left_view = QPlainTextEdit()
        self.right_view = QPlainTextEdit()
        self.left_view.setReadOnly(True)
        self.right_view.setReadOnly(True)
        panes.addWidget(self.left_view)
        panes.addWidget(self.right_view)
        layout.addLayout(panes, 2)

        layout.addWidget(QLabel("Diferencias"))
        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        layout.addWidget(self.diff_view, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.left_combo.currentIndexChanged.connect(self.refresh)
        self.right_combo.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        left = self._selected(self.left_combo)
        right = self._selected(self.right_combo)
        if left is None or right is None:
            return
        left_text = _flow_text(left)
        right_text = _flow_text(right)
        self.left_view.setPlainText(left_text)
        self.right_view.setPlainText(right_text)
        diff = difflib.unified_diff(
            left_text.splitlines(),
            right_text.splitlines(),
            fromfile="captura A",
            tofile="captura B",
            lineterm="",
        )
        self.diff_view.setPlainText("\n".join(diff) or "Sin diferencias")

    def _selected(self, combo: QComboBox) -> HttpFlowCaptured | None:
        flow_id = combo.currentData()
        return next((flow for flow in self._flows if flow.flow_id == flow_id), None)


def _flow_text(flow: HttpFlowCaptured) -> str:
    response_headers = _format_headers(flow.response_headers)
    response_body = _decode_body(flow.response_body)
    return (
        f"REQUEST\n{format_request(flow)}\n\n"
        f"RESPONSE\n{flow.http_version} {flow.status_code or ''} {flow.reason}\n"
        f"{response_headers}\n\n{response_body}"
    )
