"""Diálogo que muestra una playlist HLS parseada con sus segmentos y
comandos ffmpeg listos para copiar."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
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
    """Muestra los segmentos de un .m3u8 y los botones para extraer."""

    def __init__(
        self,
        playlist: M3u8Playlist,
        source_url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._playlist = playlist
        self._source_url = source_url
        self.setWindowTitle("Playlist HLS (m3u8)")
        self.resize(820, 600)

        layout = QVBoxLayout(self)

        # Cabecera con metadatos
        info = QFormLayout()
        info.addRow("URL origen:", QLabel(source_url))
        version_text = (
            str(playlist.version) if playlist.version else "(no declarada)"
        )
        info.addRow("Versión:", QLabel(version_text))
        info.addRow(
            "Target duration:",
            QLabel(
                f"{playlist.target_duration}s"
                if playlist.target_duration
                else "(no declarado)"
            ),
        )
        type_text = (
            "Master playlist (lista de variantes)"
            if playlist.is_master
            else "Media playlist (segmentos)"
        )
        info.addRow("Tipo:", QLabel(type_text))
        info.addRow(
            "Estado:",
            QLabel("VOD (con ENDLIST)" if not playlist.is_live else "Live (sin ENDLIST)"),
        )
        segments_count = playlist.segment_count
        total_duration = playlist.total_duration
        if segments_count:
            duration_text = (
                f"{segments_count} segmentos, {total_duration:.1f}s total"
            )
        else:
            duration_text = "0 segmentos"
        info.addRow("Contenido:", QLabel(duration_text))
        layout.addLayout(info)

        # Lista de segmentos
        if playlist.segments:
            layout.addWidget(QLabel("Segmentos:"))
            self.segments_list = QListWidget()
            for segment in playlist.segments:
                duration_text = (
                    f"{segment.duration:.2f}s"
                    if segment.duration is not None
                    else "?s"
                )
                item = QListWidgetItem(f"[{duration_text}]  {segment.url}")
                item.setData(Qt.ItemDataRole.UserRole, segment.url)
                self.segments_list.addItem(item)
            self.segments_list.itemDoubleClicked.connect(
                lambda item: self._copy_to_clipboard(item.data(Qt.ItemDataRole.UserRole))
            )
            layout.addWidget(self.segments_list, 1)
        else:
            self.segments_list = None
            placeholder = QLabel(
                "(Esta playlist no contiene segmentos — es una master playlist "
                "con variantes. Pulsa el botón de abajo para abrir cada variante.)"
            )
            placeholder.setWordWrap(True)
            layout.addWidget(placeholder, 1)

        # Comando ffmpeg
        layout.addWidget(QLabel("Comando ffmpeg (clic para copiar al portapapeles):"))
        self.ffmpeg_edit = QPlainTextEdit()
        self.ffmpeg_edit.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.ffmpeg_edit.setFont(mono)
        self.ffmpeg_edit.setPlainText(build_ffmpeg_command(source_url))
        self.ffmpeg_edit.setFixedHeight(70)
        layout.addWidget(self.ffmpeg_edit)

        # Botones
        buttons = QHBoxLayout()
        copy_ffmpeg = QPushButton("Copiar ffmpeg")
        copy_ffmpeg.clicked.connect(
            lambda: self._copy_to_clipboard(self.ffmpeg_edit.toPlainText())
        )
        buttons.addWidget(copy_ffmpeg)

        if self.segments_list is not None:
            copy_all = QPushButton("Copiar todas las URLs de segmentos")
            copy_all.clicked.connect(self._copy_all_segments)
            buttons.addWidget(copy_all)

        buttons.addStretch(1)
        ok = QPushButton("Cerrar")
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _copy_to_clipboard(self, text: str) -> None:
        if text:
            QApplication.clipboard().setText(text)

    def _copy_all_segments(self) -> None:
        if self.segments_list is None:
            return
        urls = "\n".join(
            self.segments_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.segments_list.count())
        )
        self._copy_to_clipboard(urls)
