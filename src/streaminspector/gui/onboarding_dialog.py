from __future__ import annotations

import platform
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from streaminspector.gui.https_setup_dialog import certificate_status
from streaminspector.system_proxy import system_proxy_supported


def diagnostic_report(host: str, port: int, data_dir: Path) -> str:
    certificate_present, certificate_files = certificate_status()
    certificates = ", ".join(path.name for path in certificate_files) or "no encontrados"
    proxy_support = "disponible" if system_proxy_supported() else "no disponible"
    data_status = "sí" if data_dir.exists() else "se creará al usarlo"
    return "\n".join(
        (
            f"Python: {platform.python_version()} ({sys.executable})",
            f"Sistema: {platform.system()} {platform.release()}",
            f"Proxy configurado: {host}:{port}",
            f"Proxy automático de Windows: {proxy_support}",
            f"Certificados mitmproxy: {certificates}",
            f"Directorio de datos: {data_dir}",
            f"Directorio de datos accesible: {data_status}",
        )
    )


class OnboardingDialog(QDialog):
    """First-run guide and local diagnostic summary."""

    def __init__(
        self,
        host: str,
        port: int,
        data_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Primeros pasos con StreamInspector")
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Sigue estos pasos para realizar una primera captura HTTP/HTTPS autorizada."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tabs = QTabWidget(self)
        tabs.addTab(self._text_page(self._steps(host, port)), "Guía paso a paso")
        tabs.addTab(
            self._text_page(diagnostic_report(host, port, data_dir)),
            "Diagnóstico local",
        )
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _text_page(text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        viewer = QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(text)
        layout.addWidget(viewer)
        return page

    @staticmethod
    def _steps(host: str, port: int) -> str:
        return (
            "1. En Windows, inicia con 'Iniciar StreamInspector.bat'.\n\n"
            "2. Pulsa 'Proxy OFF'. Cuando el motor esté listo cambiará a 'Proxy ON'.\n\n"
            f"3. El proxy local utilizará {host}:{port}. En Windows puede configurarse "
            "automáticamente desde el menú Proxy.\n\n"
            "4. Para HTTPS abre Proxy > Configurar navegador y HTTPS, visita mitm.it e "
            "instala el certificado únicamente en un entorno autorizado.\n\n"
            "5. Abre una web o API propia. Las solicitudes aparecerán en la tabla.\n\n"
            "6. Selecciona una fila para revisar petición, respuesta, cabeceras, cuerpo y JSON.\n\n"
            "7. Usa Captura para pausar, omitir recursos estáticos o excluir dominios.\n\n"
            "8. Usa Exportar para generar CSV, JSON o HAR, y Peticiones para repetir o "
            "comparar capturas.\n\n"
            "9. Pulsa Proxy ON para detenerlo. StreamInspector restaurará el proxy anterior "
            "de Windows cuando la configuración automática esté activada."
        )
