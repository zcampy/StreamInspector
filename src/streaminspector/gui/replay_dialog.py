from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from streaminspector.core.events import HttpFlowCaptured


@dataclass(frozen=True, slots=True)
class ReplayResult:
    status: int
    reason: str
    elapsed_ms: float
    headers: tuple[tuple[str, str], ...]
    body: bytes


class _ReplayWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._method = method
        self._url = url
        self._headers = headers
        self._body = body

    def run(self) -> None:
        request = urllib.request.Request(
            self._url,
            data=self._body or None,
            headers=self._headers,
            method=self._method,
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                result = ReplayResult(
                    status=response.status,
                    reason=response.reason,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    headers=tuple(response.headers.items()),
                    body=body,
                )
        except urllib.error.HTTPError as exc:
            result = ReplayResult(
                status=exc.code,
                reason=exc.reason,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                headers=tuple(exc.headers.items()),
                body=exc.read(),
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)


class ReplayDialog(QDialog):
    """Edit and replay a captured HTTP request for authorized testing."""

    def __init__(self, flow: HttpFlowCaptured, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _ReplayWorker | None = None
        self.setWindowTitle("Repetir petición")
        self.resize(920, 720)

        self.method = QComboBox()
        self.method.setEditable(True)
        self.method.addItems(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
        self.method.setCurrentText(flow.method)
        self.url = QLineEdit(flow.url)
        self.headers = QPlainTextEdit(_headers_to_json(flow.request_headers))
        self.body = QPlainTextEdit(flow.request_body.decode("utf-8", errors="replace"))
        self.result_summary = QLabel("Sin enviar")
        self.result_headers = QPlainTextEdit()
        self.result_body = QPlainTextEdit()
        self.result_headers.setReadOnly(True)
        self.result_body.setReadOnly(True)

        request_panel = QWidget()
        form = QFormLayout(request_panel)
        form.addRow("Método", self.method)
        form.addRow("URL", self.url)
        form.addRow("Cabeceras JSON", self.headers)
        form.addRow("Cuerpo", self.body)

        response_panel = QWidget()
        response_layout = QVBoxLayout(response_panel)
        response_layout.addWidget(self.result_summary)
        response_layout.addWidget(QLabel("Cabeceras de respuesta"))
        response_layout.addWidget(self.result_headers)
        response_layout.addWidget(QLabel("Cuerpo de respuesta"))
        response_layout.addWidget(self.result_body)

        splitter = QSplitter()
        splitter.addWidget(request_panel)
        splitter.addWidget(response_panel)
        splitter.setSizes([450, 450])

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close | QDialogButtonBox.StandardButton.Apply
        )
        self.send_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.send_button.setText("Enviar")
        self.buttons.rejected.connect(self.reject)
        self.send_button.clicked.connect(self._send)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        layout.addWidget(self.buttons)

    def _send(self) -> None:
        try:
            headers = _parse_headers(self.headers.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, "Cabeceras no válidas", str(exc))
            return
        method = self.method.currentText().strip().upper()
        url = self.url.text().strip()
        if not method or not url:
            QMessageBox.warning(self, "Petición incompleta", "Método y URL son obligatorios.")
            return

        self.send_button.setEnabled(False)
        self.result_summary.setText("Enviando…")
        self._worker = _ReplayWorker(
            method,
            url,
            headers,
            self.body.toPlainText().encode("utf-8"),
            self,
        )
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(lambda: self.send_button.setEnabled(True))
        self._worker.start()

    def _on_completed(self, result: ReplayResult) -> None:
        self.result_summary.setText(
            f"HTTP {result.status} {result.reason} — {result.elapsed_ms:.0f} ms — "
            f"{len(result.body)} bytes"
        )
        self.result_headers.setPlainText(
            "\n".join(f"{name}: {value}" for name, value in result.headers)
        )
        self.result_body.setPlainText(result.body.decode("utf-8", errors="replace"))

    def _on_failed(self, message: str) -> None:
        self.result_summary.setText("Error al enviar")
        QMessageBox.critical(self, "Error de repetición", message)


def _headers_to_json(headers: tuple[tuple[str, str], ...]) -> str:
    return json.dumps(dict(headers), indent=2, ensure_ascii=False)


def _parse_headers(text: str) -> dict[str, str]:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON no válido: {exc.msg}") from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError("Las cabeceras deben ser un objeto JSON de texto a texto.")
    blocked = {"content-length", "host", "connection"}
    return {key: item for key, item in value.items() if key.casefold() not in blocked}
