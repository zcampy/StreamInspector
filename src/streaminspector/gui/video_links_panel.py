"""Panel de enlaces multimedia detectados en las capturas."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.media_utils import (
    ReproducibleLinkInfo,
    build_ffmpeg_command,
    build_reproducible_link_info,
    decode_response_body,
    is_m3u8_response,
    is_video_url,
    parse_m3u8,
)
from streaminspector.stream_validation import (
    StreamValidationResult,
    validate_reproducible_link,
)


class VideoLinksPanel(QWidget):
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

        header_layout = QHBoxLayout()
        self.header_label = QLabel("Streams de vídeo (0)")
        self.header_label.setStyleSheet("color: #6dd58c; font-weight: bold;")
        header_layout.addWidget(self.header_label)
        header_layout.addStretch(1)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #888c95;")
        header_layout.addWidget(self.summary_label)
        layout.addLayout(header_layout)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Método", "Estado", "Tipo", "URL"])
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

        button_layout = QHBoxLayout()
        self.play_button = QPushButton("▶ Probar en navegador")
        self.play_button.clicked.connect(self._open_selected_in_browser)
        self.play_button.setEnabled(False)
        button_layout.addWidget(self.play_button)

        self.reproducible_button = QPushButton("Obtener enlace reproducible")
        self.reproducible_button.clicked.connect(self._obtain_reproducible_link)
        self.reproducible_button.setEnabled(False)
        button_layout.addWidget(self.reproducible_button)

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

    def refresh(self) -> None:
        video_flows: list[HttpFlowCaptured] = []
        seen_urls: set[str] = set()
        for flow in self._flows_provider():
            if not (
                is_video_url(flow.url, flow.content_type)
                or is_m3u8_response(
                    flow.content_type,
                    flow.response_body,
                    flow.response_headers,
                )
            ):
                continue
            if flow.url in seen_urls:
                continue
            seen_urls.add(flow.url)
            video_flows.append(flow)

        self.header_label.setText(f"Streams de vídeo ({len(video_flows)})")
        if video_flows:
            counts: dict[str, int] = {}
            for flow in video_flows:
                key = self._classify(flow)
                counts[key] = counts.get(key, 0) + 1
            self.summary_label.setText(
                ", ".join(f"{count} {kind}" for kind, count in sorted(counts.items()))
            )
        else:
            self.summary_label.setText("")

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
            self.table.setItem(row, 3, QTableWidgetItem(self._classify(flow)))
            url_item = QTableWidgetItem(flow.url)
            url_item.setToolTip(flow.url)
            self.table.setItem(row, 4, url_item)
        self.table.setSortingEnabled(True)
        self._update_button_state()

    @staticmethod
    def _classify(flow: HttpFlowCaptured) -> str:
        if is_m3u8_response(
            flow.content_type,
            flow.response_body,
            flow.response_headers,
        ):
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
        return flow.content_type.split(";", 1)[0].strip() or "?"

    def _selected_flow(self) -> HttpFlowCaptured | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 4)
        return self._flow_by_url.get(item.text()) if item is not None else None

    def _copy_selected_url(self) -> None:
        flow = self._selected_flow()
        if flow is None:
            QMessageBox.information(self, "Copiar URL", "Selecciona un stream primero.")
            return
        QApplication.clipboard().setText(flow.url)

    def _copy_selected_ffmpeg(self) -> None:
        flow = self._selected_flow()
        if flow is None:
            QMessageBox.information(self, "Copiar ffmpeg", "Selecciona un stream primero.")
            return
        QApplication.clipboard().setText(
            build_ffmpeg_command(flow.url, flow.content_type, flow.request_headers)
        )

    def _playlist_for_flow(self, flow: HttpFlowCaptured):
        if not is_m3u8_response(
            flow.content_type,
            flow.response_body,
            flow.response_headers,
        ):
            return None
        body = decode_response_body(flow.response_body, flow.response_headers)
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return parse_m3u8(text, base_url=flow.url)

    def _view_selected_m3u8(self) -> None:
        flow = self._selected_flow()
        if flow is None:
            return
        playlist = self._playlist_for_flow(flow)
        if playlist is None:
            return
        from streaminspector.gui.m3u8_dialog import M3u8Dialog

        dialog = M3u8Dialog(
            playlist,
            flow.url,
            self,
            request_headers=flow.request_headers,
        )
        dialog.show()

    def _obtain_reproducible_link(self) -> None:
        flow = self._selected_flow()
        if flow is None:
            QMessageBox.information(
                self,
                "Obtener enlace reproducible",
                "Selecciona un stream primero.",
            )
            return
        playlist = self._playlist_for_flow(flow)
        info = build_reproducible_link_info(
            flow.url,
            playlist,
            flow.request_headers,
        )
        QApplication.clipboard().setText(info.url)
        ReproducibleLinkDialog(
            info,
            self,
            request_headers=flow.request_headers,
        ).exec()

    def _open_selected_in_browser(self) -> None:
        flow = self._selected_flow()
        if flow is None:
            QMessageBox.information(
                self,
                "Probar en navegador",
                "Selecciona un stream primero.",
            )
            return
        if not QDesktopServices.openUrl(QUrl(flow.url)):
            QMessageBox.warning(
                self,
                "No se pudo abrir el navegador",
                f"El sistema no pudo abrir esta URL:\n{flow.url}",
            )

    def _on_double_click(self, _index) -> None:
        flow = self._selected_flow()
        if flow is None:
            return
        if self._playlist_for_flow(flow) is not None:
            self._view_selected_m3u8()
        else:
            self._copy_selected_ffmpeg()

    def _update_button_state(self) -> None:
        flow = self._selected_flow()
        selected = flow is not None
        is_m3u8 = selected and self._playlist_for_flow(flow) is not None
        self.play_button.setEnabled(selected)
        self.reproducible_button.setEnabled(selected)
        self.copy_url_button.setEnabled(selected)
        self.copy_ffmpeg_button.setEnabled(selected)
        self.view_m3u8_button.setEnabled(bool(is_m3u8))

    def _clear_panel(self) -> None:
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
        menu.addAction("▶ Probar en navegador").triggered.connect(
            self._open_selected_in_browser
        )
        menu.addAction("Obtener enlace reproducible").triggered.connect(
            self._obtain_reproducible_link
        )
        menu.addAction("Copiar URL").triggered.connect(self._copy_selected_url)
        menu.addAction("Copiar como ffmpeg").triggered.connect(
            self._copy_selected_ffmpeg
        )
        if self._playlist_for_flow(flow) is not None:
            menu.addAction("Ver segmentos m3u8").triggered.connect(
                self._view_selected_m3u8
            )
        menu.exec(self.table.viewport().mapToGlobal(position))


class ReproducibleLinkDialog(QDialog):
    def __init__(
        self,
        info: ReproducibleLinkInfo,
        parent: QWidget | None = None,
        request_headers: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self._info = info
        self._request_headers = request_headers or ()
        self.setWindowTitle("Enlace reproducible")
        self.resize(820, 560)
        layout = QVBoxLayout(self)

        if info.selected_variant is not None:
            variant = info.selected_variant
            selected_text = "Mejor variante seleccionada"
            if variant.resolution:
                selected_text += f": {variant.resolution}"
            if variant.bandwidth:
                selected_text += f" · {variant.bandwidth} bps"
            layout.addWidget(QLabel(selected_text))

        if info.appears_temporary:
            warning = QLabel("⚠ La URL parece firmada o temporal y puede caducar.")
            warning.setWordWrap(True)
            layout.addWidget(warning)

        headers = ", ".join(info.required_headers) or "Ninguna cabecera especial detectada"
        layout.addWidget(QLabel(f"Cabeceras recomendadas: {headers}"))
        if info.sensitive_headers:
            layout.addWidget(
                QLabel(
                    "Cabeceras sensibles disponibles: "
                    + ", ".join(info.sensitive_headers)
                    + ". No se incluyen automáticamente."
                )
            )

        layout.addWidget(QLabel("URL reproducible (copiada al portapapeles):"))
        url_edit = QPlainTextEdit(info.url)
        url_edit.setReadOnly(True)
        url_edit.setFixedHeight(90)
        layout.addWidget(url_edit)

        layout.addWidget(QLabel("Comando ffmpeg:"))
        command_edit = QPlainTextEdit(info.command)
        command_edit.setReadOnly(True)
        command_edit.setFixedHeight(130)
        layout.addWidget(command_edit)

        if info.warnings:
            notes = QLabel("\n".join(f"• {warning}" for warning in info.warnings))
            notes.setWordWrap(True)
            layout.addWidget(notes)

        buttons = QHBoxLayout()
        validate_button = QPushButton("Validar ahora")
        validate_button.clicked.connect(self._validate_now)
        buttons.addWidget(validate_button)
        copy_url = QPushButton("Copiar URL")
        copy_url.clicked.connect(lambda: QApplication.clipboard().setText(info.url))
        buttons.addWidget(copy_url)
        copy_command = QPushButton("Copiar ffmpeg")
        copy_command.clicked.connect(
            lambda: QApplication.clipboard().setText(info.command)
        )
        buttons.addWidget(copy_command)
        buttons.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _validate_now(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = validate_reproducible_link(
                self._info.url,
                self._request_headers,
            )
        finally:
            QApplication.restoreOverrideCursor()

        if (
            not result.ok
            and result.status_code in {401, 403}
            and self._info.sensitive_headers
        ):
            answer = QMessageBox.question(
                self,
                "El servidor exige autenticación",
                "La validación respondió HTTP "
                f"{result.status_code}. La captura contiene "
                f"{', '.join(self._info.sensitive_headers)}.\n\n"
                "¿Reintentar incluyendo esas credenciales? "
                "No compartas el resultado ni el comando generado.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                QApplication.processEvents()
                try:
                    result = validate_reproducible_link(
                        self._info.url,
                        self._request_headers,
                        include_sensitive_headers=True,
                    )
                finally:
                    QApplication.restoreOverrideCursor()

        self._show_validation_result(result)

    def _show_validation_result(self, result: StreamValidationResult) -> None:
        details = [
            result.message,
            f"Etapa: {result.stage}",
            f"Playlist: {result.playlist_url}",
        ]
        if result.media_playlist_url:
            details.append(f"Variante: {result.media_playlist_url}")
        if result.segment_url:
            details.append(f"Segmento: {result.segment_url}")
        if result.status_code is not None:
            details.append(f"HTTP: {result.status_code}")
        if result.used_sensitive_headers:
            details.append("Se utilizaron Cookie/Authorization en esta comprobación.")
        text = "\n".join(details)
        if result.ok:
            QMessageBox.information(self, "Enlace reproducible válido", text)
        else:
            QMessageBox.warning(self, "El enlace no ha superado la validación", text)
