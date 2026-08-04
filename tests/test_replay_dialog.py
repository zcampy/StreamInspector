import pytest

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.gui.replay_dialog import ReplayDialog, _parse_headers


def test_parse_headers_accepts_text_mapping_and_removes_transport_headers() -> None:
    headers = _parse_headers(
        '{"Content-Type": "application/json", "Host": "example.com", "X-Test": "1"}'
    )

    assert headers == {"Content-Type": "application/json", "X-Test": "1"}


def test_parse_headers_rejects_non_text_values() -> None:
    with pytest.raises(ValueError, match="texto a texto"):
        _parse_headers('{"X-Retry": 2}')


def test_parse_headers_reports_invalid_json() -> None:
    with pytest.raises(ValueError, match="JSON no válido"):
        _parse_headers("not-json")


def _flow() -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id="replay-1",
        method="POST",
        scheme="https",
        host="api.example",
        port=443,
        path="/v1",
        url="https://api.example/v1",
        http_version="HTTP/2",
        status_code=200,
        reason="OK",
        content_type="application/json",
        request_headers=(
            ("Content-Type", "application/json"),
            ("X-Trace", "abc"),
        ),
        response_headers=(),
        request_body=b'{"user":"demo"}',
        response_body=b"",
        request_size=15,
        response_size=0,
    )


def test_replay_dialog_uses_captured_request_as_initial_state(qtbot) -> None:
    flow = _flow()
    dialog = ReplayDialog(flow)
    qtbot.addWidget(dialog)

    assert dialog.method.currentText() == "POST"
    assert dialog.url.text() == "https://api.example/v1"
    assert dialog.body.toPlainText() == '{"user":"demo"}'
    # Cabeceras: el JSON inicial debe parsear correctamente y conservar X-Trace.
    parsed = _parse_headers(dialog.headers.toPlainText())
    assert parsed == {
        "Content-Type": "application/json",
        "X-Trace": "abc",
    }


def test_replay_dialog_rejects_invalid_headers_json(qtbot, monkeypatch) -> None:
    """Si el usuario edita las cabeceras a algo inválido, debe mostrarse un aviso y
    NO debe lanzarse el worker (sin red involucrada)."""
    flow = _flow()
    dialog = ReplayDialog(flow)
    qtbot.addWidget(dialog)

    dialog.headers.setPlainText("not-json")
    # Capturamos QMessageBox.warning para no bloquear el test offscreen.
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "streaminspector.gui.replay_dialog.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args[1], args[2])) or 0,
    )
    started: list[bool] = []
    monkeypatch.setattr(
        "streaminspector.gui.replay_dialog._ReplayWorker.start",
        lambda self: started.append(True),
    )

    dialog._send()

    assert warnings and "no válidas" in warnings[0][0]
    assert started == [], "No debe lanzarse el worker con cabeceras inválidas"


def test_replay_dialog_requires_method_and_url(qtbot, monkeypatch) -> None:
    flow = _flow()
    dialog = ReplayDialog(flow)
    qtbot.addWidget(dialog)

    dialog.url.setText("")
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "streaminspector.gui.replay_dialog.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args[1], args[2])) or 0,
    )
    started: list[bool] = []
    monkeypatch.setattr(
        "streaminspector.gui.replay_dialog._ReplayWorker.start",
        lambda self: started.append(True),
    )

    dialog._send()

    assert warnings and "Petición incompleta" in warnings[0][0]
    assert started == []
