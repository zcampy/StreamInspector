from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


def mitmproxy_certificates_dir() -> Path:
    return Path.home() / ".mitmproxy"


def certificate_status(cert_dir: Path | None = None) -> tuple[bool, list[Path]]:
    directory = cert_dir or mitmproxy_certificates_dir()
    expected = [
        directory / "mitmproxy-ca-cert.cer",
        directory / "mitmproxy-ca-cert.p12",
        directory / "mitmproxy-ca.pem",
    ]
    existing = [path for path in expected if path.exists()]
    return bool(existing), existing


class HttpsSetupDialog(QDialog):
    """Guide the user through browser proxy and HTTPS certificate setup."""

    def __init__(
        self,
        proxy_host: str,
        proxy_port: int,
        proxy_running: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._host = proxy_host
        self._port = proxy_port
        self._running = proxy_running
        self.setWindowTitle("Configurar navegador y HTTPS")
        self.resize(700, 520)

        layout = QVBoxLayout(self)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        instructions = QPlainTextEdit()
        instructions.setReadOnly(True)
        instructions.setPlainText(self._instructions())
        layout.addWidget(instructions, 1)

        buttons = QHBoxLayout()
        open_mitm = QPushButton("Abrir mitm.it")
        open_mitm.clicked.connect(self._open_mitm_it)
        buttons.addWidget(open_mitm)

        open_folder = QPushButton("Abrir carpeta de certificados")
        open_folder.clicked.connect(self._open_certificates_folder)
        buttons.addWidget(open_folder)

        refresh = QPushButton("Comprobar de nuevo")
        refresh.clicked.connect(self._refresh_status)
        buttons.addWidget(refresh)
        layout.addLayout(buttons)

        self._refresh_status()

    def _instructions(self) -> str:
        return (
            "1. Activa Proxy ON en StreamInspector.\n"
            f"2. Configura el navegador o dispositivo para usar {self._host}:{self._port}.\n"
            "3. Con el proxy activo, pulsa 'Abrir mitm.it'.\n"
            "4. Descarga el certificado correspondiente al sistema operativo.\n"
            "5. Instálalo como entidad de certificación raíz de confianza.\n"
            "6. Abre una web HTTPS y comprueba que aparece en el historial.\n\n"
            "Usa esta función únicamente en equipos, navegadores y redes donde tengas autorización."
        )

    def _refresh_status(self) -> None:
        present, files = certificate_status()
        proxy_text = "activo" if self._running else "detenido"
        cert_text = (
            "certificados generados: " + ", ".join(path.name for path in files)
            if present
            else "todavía no se encontraron certificados generados"
        )
        self.status_label.setText(
            f"Proxy {proxy_text} en {self._host}:{self._port}; {cert_text}."
        )

    def _open_mitm_it(self) -> None:
        if not self._running:
            QMessageBox.information(
                self,
                "Proxy detenido",
                "Activa primero Proxy ON. mitm.it solo funciona cuando el tráfico pasa por el proxy.",
            )
            return
        webbrowser.open("http://mitm.it")

    def _open_certificates_folder(self) -> None:
        directory = mitmproxy_certificates_dir()
        directory.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(directory)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(directory)])
            else:
                subprocess.Popen(["xdg-open", str(directory)])
        except OSError as exc:
            QMessageBox.warning(self, "No se pudo abrir la carpeta", str(exc))
