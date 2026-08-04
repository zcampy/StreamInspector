"""Panel inferior que muestra SOLO los enlaces a streams de vídeo/audio.

Es un *derivado* de la lista principal de flows: no duplica estado, solo
lee `self._flows` del `MainWindow` y filtra por `is_video_url` /
`is_m3u8_response`. Acciones disponibles:
- Copiar URL al portapapeles
- Copiar como comando ffmpeg (contenedor correcto según content-type)
- Ver los segmentos de una playlist m3u8 parseada (abre `M3u8Dialog`)
- Doble-click: m3u8 → ver segmentos; otro → copiar ffmpeg
- Botón "Limpiar panel" para vaciarlo sin afectar la captura principal
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.media_utils import (
    build_ffmpeg_command,
    is_m3u8_response,
    is_video_url,
)


class VideoLinksPanel(QWidget):
    """Lista de streams de vídeo/audio extraídos de los flows del MainWindow."""

    def __init__(
        self,
        flows_provider: Callable[[], list[HttpFlowCaptured]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._flows_provider = flows_provider
        self._flow_by_url: dict[str, HttpFlowCaptured] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Cabecera con contador
        header_layout = QHBoxLayout()
        self.header_label = QLabel("Streams de vídeo (0)")
        self.header_label.setStyleSheet("color: #6dd58c; font-weight: bold;")
        header_layout.addWidget(self.header_label)
        header_layout.addStretch(1)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #888c95;")
        header_layout.addWidget(self.summary_label)
        layout.addLayout(header_layout)

        # Tabla: 5 columnas. URL es la principal (stretch).
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["#", "Método", "Estado", "Tipo", "URL"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        for column in (0, 1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._update_button_state)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table)

        # Botones de acción sobre la fila seleccionada
        button_layout = QHBoxLayout()

        self.copy_url_button = QPushButton("Copiar URL")
        self.copy_url_button.clicked.connect(self._copy_selected_url)
        self.copy_url_button.setEnabled(False)
        button_layout.addWidget(self.copy_url_button)

        self.copy_ffmpeg_button = QPushButton("Copiar como ffmpeg")
        self.copy_ffmpeg_button.clicked.connect(self._copy_selected_ffmpeg)
        self.copy_ffmpeg_button.setEnabled(False)
        button_layout.addWidget(self.copy_ffmpeg_button)

        self.view_m3u8_button = QPushButton("Ver segmentos m3u8")
        self.view_m3u8_button.clicked.connect(self._view_selected_m3u8)
        self.view_m3u8_button.setEnabled(False)
        button_layout.addWidget(self.view_m3u8_button)

        button_layout.addStretch(1)

        self.clear_button = QPushButton("Limpiar panel")
        self.clear_button.clicked.connect(self._clear_panel)
        button_layout.addWidget(self.clear_button)

        layout.addLayout(button_layout)

    # ------------------------------------------------------------------ refresh

    def refresh(self) -> None:
        """Reconstruye la tabla leyendo los flows actuales.

        Se llama desde el MainWindow tras cada `_append_flow` o `_clear_view`.
        Dedupa por URL (las playlists m3u8 se relisten cada pocos segundos
        en vivo, no queremos duplicados visuales).
        """
        flows = self._flows_provider()
        video_flows: list[HttpFlowCaptured] = []
        seen_urls: set[str] = set()
        for flow in flows:
            if not (
                is_video_url(flow.url, flow.content_type)
                or is_m3u8_response(flow.content_type, flow.response_body)
            ):
                continue
            if flow.url in seen_urls:
                continue
            seen_urls.add(flow.url)
            video_flows.append(flow)

        # Cabecera: total + desglose por tipo (m3u8, mp4, ts, etc.)
        self.header_label.setText(f"Streams de vídeo ({len(video_flows)})")
        if video_flows:
            counts: dict[str, int] = {}
            for flow in video_flows:
                key = self._classify(flow)
                counts[key] = counts.get(key, 0) + 1
            breakdown = ", ".join(
                f"{count} {kind}" for kind, count in sorted(counts.items())
            )
            self.summary_label.setText(breakdown)
        else:
            self.summary_label.setText("")

        # Repintar la tabla con sorting deshabilitado para que el orden
        # de inserción sea el orden de pintado.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(video_flows))
        self._flow_by_url.clear()
        for row, flow in enumerate(video_flows):
            self._flow_by_url[flow.url] = flow
            self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(flow.method))
            status_text = str(flow.status_code) if flow.status_code else "—"
            status_item = QTableWidgetItem(status_text)
            if flow.status_code and flow.status_code >= 400:
                font = status_item.font()
                font.setBold(True)
                status_item.setFont(font)
            self.table.setItem(row, 2, status_item)
            tipo = self._classify(flow)
            self.table.setItem(row, 3, QTableWidgetItem(tipo))
            url_item = QTableWidgetItem(flow.url)
            url_item.setToolTip(flow.url)
            self.table.setItem(row, 4, url_item)
        self.table.setSortingEnabled(True)
        self._update_button_state()

    @staticmethod
    def _classify(flow: HttpFlowCaptured) -> str:
        """Etiqueta corta para la columna 'Tipo' (m3u8, mp4, ts, etc.)."""
        if is_m3u8_response(flow.content_type, flow.response_body):
            return "m3u8"
        lower = flow.url.lower().split("?", 1)[0]
        for ext in (
            ".m3u8",
            ".m3u",
            ".mp4",
            ".webm",
            ".mov",
            ".ts",
            ".m4s",
            ".mpd",
            ".flv",
            ".mkv",
        ):
            if lower.endswith(ext):
                return ext.lstrip(".")
        ct = flow.content_type.split(";", 1)[0].strip()
        return ct or "?"

    # ----------------------------------------------------------------- acciones

    def _selected_flow(self) -> HttpFlowCaptured | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        url_item = self.table.item(row, 4)
        if url_item is None:
            return None
        url = url_item.text()
        return self._flow_by_url.get(url)

    def _copy_selected_url(self) -> None:
        flow = self._selected_flow()
        if flow is None:
            QMessageBox.information(
                self, "Copiar URL", "Selecciona un stream primero."
            )
            return
        QApplication.clipboard().setText(flow.url)

    def _copy_selected_ffmpeg(self) -> None:
        flow = self._selected_flow()
        if flow is None:
            QMessageBox.information(
                self, "Copiar ffmpeg", "Selecciona un stream primero."
            )
            return
        QApplication.clipboard().setText(
            build_ffmpeg_command(
                flow.url, flow.content_type, flow.request_headers
            )
        )

    def _view_selected_m3u8(self) -> None:
        flow = self._selected_flow()
        if flow is None or not is_m3u8_response(
            flow.content_type, flow.response_body
        ):
            return
        from streaminspector.gui.m3u8_dialog import M3u8Dialog
        from streaminspector.media_utils import parse_m3u8

        text = flow.response_body.decode("utf-8", errors="replace")
        playlist = parse_m3u8(text, base_url=flow.url)
        dialog = M3u8Dialog(playlist, flow.url, self)
        dialog.show()

    def _on_double_click(self, _index) -> None:
        flow = self._selected_flow()
        if flow is None:
            return
        if is_m3u8_response(flow.content_type, flow.response_body):
            self._view_selected_m3u8()
        else:
            self._copy_selected_ffmpeg()

    def _update_button_state(self) -> None:
        flow = self._selected_flow()
        self.copy_url_button.setEnabled(flow is not None)
        self.copy_ffmpeg_button.setEnabled(flow is not None)
        self.view_m3u8_button.setEnabled(
            flow is not None
            and is_m3u8_response(flow.content_type, flow.response_body)
        )

    def _clear_panel(self) -> None:
        """Vacía la tabla. La captura principal (self._flows) no se toca.

        Útil cuando el usuario quiere centrarse en un subconjunto sin
        perder los flows ya capturados.
        """
        self._flow_by_url.clear()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setSortingEnabled(True)
        self.header_label.setText("Streams de vídeo (0)")
        self.summary_label.setText("(vacío manualmente)")

    def _show_context_menu(self, position) -> None:
        flow = self._selected_flow()
        if flow is None:
            return
        menu = QMenu(self)
        copy_url = menu.addAction("Copiar URL")
        copy_url.triggered.connect(self._copy_selected_url)
        copy_ffmpeg = menu.addAction("Copiar como ffmpeg")
        copy_ffmpeg.triggered.connect(self._copy_selected_ffmpeg)
        if is_m3u8_response(flow.content_type, flow.response_body):
            view_m3u8 = menu.addAction("Ver segmentos m3u8")
            view_m3u8.triggered.connect(self._view_selected_m3u8)
        menu.exec(self.table.viewport().mapToGlobal(position))
