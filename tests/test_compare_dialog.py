"""GUI tests for CompareDialog using pytest-qt in offscreen mode."""

from __future__ import annotations

import pytest

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.gui.compare_dialog import CompareDialog

pytestmark = pytest.mark.usefixtures("qtbot")


def _flow(flow_id: str, body: bytes, status: int = 200) -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id=flow_id,
        method="POST",
        scheme="https",
        host="api.example",
        port=443,
        path="/v1",
        url="https://api.example/v1",
        http_version="HTTP/2",
        status_code=status,
        reason="OK" if status == 200 else "Server Error",
        content_type="application/json",
        request_headers=(("Content-Type", "application/json"),),
        response_headers=(("Content-Type", "application/json"),),
        request_body=b'{"k":"v"}',
        response_body=body,
        request_size=9,
        response_size=len(body),
        duration_ms=10.0,
    )


def test_compare_dialog_populates_selectors_and_panes(qtbot) -> None:
    flows = [
        _flow("a", b'{"result":1}'),
        _flow("b", b'{"result":2}'),
        _flow("c", b'{"result":3}'),
    ]

    dialog = CompareDialog(flows)
    qtbot.addWidget(dialog)

    assert dialog.left_combo.count() == 3
    assert dialog.right_combo.count() == 3
    # Por defecto: A = primero, B = segundo.
    assert dialog.left_combo.currentData() == "a"
    assert dialog.right_combo.currentData() == "b"

    # Poblado de paneles.
    assert "REQUEST" in dialog.left_view.toPlainText()
    assert "RESPONSE" in dialog.left_view.toPlainText()
    assert dialog.right_view.toPlainText() != dialog.left_view.toPlainText()
    assert dialog.diff_view.toPlainText() != ""


def test_compare_dialog_shows_no_diff_when_same_capture(qtbot) -> None:
    flow = _flow("only", b'{"x":1}')
    dialog = CompareDialog([flow, flow])
    qtbot.addWidget(dialog)

    # Mismo flow en A y B: diff debe estar vacío o mostrar "Sin diferencias".
    diff_text = dialog.diff_view.toPlainText()
    assert diff_text == "" or "Sin diferencias" in diff_text


def test_compare_dialog_swap_changes_view(qtbot) -> None:
    flows = [
        _flow("a", b'{"x":1}'),
        _flow("b", b'{"x":2}'),
    ]
    dialog = CompareDialog(flows)
    qtbot.addWidget(dialog)

    # Capturar texto inicial.
    initial_right = dialog.right_view.toPlainText()

    # Cambiar A al segundo flow.
    dialog.left_combo.setCurrentIndex(1)
    assert dialog.left_view.toPlainText() == initial_right
