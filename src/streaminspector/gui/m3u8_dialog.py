"""Diálogo de análisis HLS y generación controlada de comandos ffmpeg."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from streaminspector.media_utils import M3u8Playlist, build_ffmpeg_command


class M3u8Dialog(QDialog):
    def __init__(
        self,
        playlist: M3u8Playlist,
        source_url: str,
        parent: QWidget | None = None,
        request_headers: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self._playlist = playlist
        self._source_url = source_url
        if request_headers is None and parent is not None:
            selected_flow = getattr(parent, "_selected_flow", None)
            flow = selected_flow() if callable(selected_flow) else None
            request_headers = getattr(flow, "request_headers", ()) if flow else ()
        self._request_headers = request_headers or ()
        self.setWindowTitle("Playlist HLS (m3u8)")
        self.resize(860, 640)

        layout = QVBoxLayout(self)
        info = QFormLayout()
        info.addRow("URL origen:", QLabel(source_url))
        info.addRow(
            "Versión:",
            QLabel(str(playlist.version) if playlist.version else "(no declarada)"),
        )
        info.addRow(
            "Target duration:",
            QLabel(
                f"{playlist.target_duration}s"
                if playlist.target_duration
                else "(no declarado)"
            ),
        )
        info.addRow(
            "Tipo:",
            QLabel(
                "Master playlist (variantes)"
                if playlist.is_master
                else "Media playlist (segmentos)"
            ),
        )
        if playlist.is_live is None:
            state_text = "Depende de la variante"
        elif playlist.is_live:
            state_text = "Live (sin ENDLIST)"
        else:
            state_text = "VOD (con ENDLIST)"
        info.addRow("Estado:", QLabel(state_text))
        if playlist.is_master:
            content_text = f"{len(playlist.variants)} variantes"
        elif playlist.segment_count:
            content_text = (
                f"{playlist.segment_count} segmentos, "
                f"{playlist.total_duration:.1f}s total"
            )
        else:
            content_text = "0 segmentos"
        info.addRow("Contenido:", QLabel(content_text))
        layout.addLayout(info)

        self.items_list = QListWidget()
        self.segments_list = self.items_list
        if playlist.is_master:
            layout.addWidget(QLabel("Variantes:"))
            for variant in playlist.variants:
                details = [
                    str(variant.bandwidth) if variant.bandwidth else "? bps",
                    variant.resolution or "?",
                    variant.codecs or "codecs desconocidos",
                ]
                item = QListWidgetItem(f"[{' | '.join(details)}]  {variant.url}")
                item.setData(Qt.ItemDataRole.UserRole, variant.url)
                self.items_list.addItem(item)
        else:
            layout.addWidget(QLabel("Segmentos:"))
            for segment in playlist.segments:
                duration = (
                    f"{segment.duration:.2f}s"
                    if segment.duration is not None
                    else "?s"
                )
                item = QListWidgetItem(f"[{duration}]  {segment.url}")
                item.setData(Qt.ItemDataRole.UserRole, segment.url)
                self.items_list.addItem(item)
        self.items_list.itemDoubleClicked.connect(
            lambda item: self._copy_to_clipboard(
                item.data(Qt.ItemDataRole.UserRole)
            )
        )
        layout.addWidget(self.items_list, 1)

        self.include_sensitive = QCheckBox(
            "Incluir Cookie y Authorization en el comando ffmpeg"
        )
        self.include_sensitive.setToolTip(
            "Puede exponer credenciales. Actívalo solo para uso local y "
            "no compartas el comando generado."
        )
        self.include_sensitive.toggled.connect(self._refresh_ffmpeg_command)
        layout.addWidget(self.include_sensitive)

        layout.addWidget(QLabel("Comando ffmpeg:"))
        self.ffmpeg_edit = QPlainTextEdit()
        self.ffmpeg_edit.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.ffmpeg_edit.setFont(mono)
        self.ffmpeg_edit.setFixedHeight(90)
        layout.addWidget(self.ffmpeg_edit)
        self._refresh_ffmpeg_command()

        buttons = QHBoxLayout()
        copy_ffmpeg = QPushButton("Copiar ffmpeg")
        copy_ffmpeg.clicked.connect(
            lambda: self._copy_to_clipboard(self.ffmpeg_edit.toPlainText())
        )
        buttons.addWidget(copy_ffmpeg)

        copy_all = QPushButton(
            "Copiar URLs de variantes"
            if playlist.is_master
            else "Copiar URLs de segmentos"
        )
        copy_all.clicked.connect(self._copy_all_items)
        copy_all.setEnabled(self.items_list.count() > 0)
        buttons.addWidget(copy_all)

        buttons.addStretch(1)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _refresh_ffmpeg_command(self) -> None:
        command = build_ffmpeg_command(
            self._source_url,
            request_headers=self._request_headers,
            include_sensitive_headers=self.include_sensitive.isChecked(),
        )
        self.ffmpeg_edit.setPlainText(command)

    def _copy_to_clipboard(self, text: str) -> None:
        if text:
            QApplication.clipboard().setText(text)

    def _copy_all_items(self) -> None:
        urls = "\n".join(
            self.items_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.items_list.count())
        )
        self._copy_to_clipboard(urls)
