from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from streaminspector.storage import SessionSummary, StorageService


class SessionPanel(QWidget):
    """Browse and manage persisted capture sessions."""

    def __init__(
        self,
        storage: StorageService,
        on_open: Callable[[SessionSummary], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._storage = storage
        self._on_open = on_open
        self._sessions: dict[int, SessionSummary] = {}

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._open_selected)

        refresh_button = QPushButton("Actualizar")
        refresh_button.clicked.connect(self.refresh)
        rename_button = QPushButton("Renombrar")
        rename_button.clicked.connect(self._rename_selected)
        delete_button = QPushButton("Eliminar")
        delete_button.clicked.connect(self._delete_selected)

        buttons = QHBoxLayout()
        buttons.addWidget(refresh_button)
        buttons.addWidget(rename_button)
        buttons.addWidget(delete_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.list_widget)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        selected_id = self.selected_session_id()
        self.list_widget.clear()
        self._sessions = {item.id: item for item in self._storage.list_sessions()}
        for summary in self._sessions.values():
            suffix = "activa" if summary.ended_at is None else "cerrada"
            text = (
                f"{summary.name}\n"
                f"{summary.started_at.astimezone().strftime('%d/%m/%Y %H:%M')} · "
                f"{summary.flow_count} capturas · {suffix}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, summary.id)
            self.list_widget.addItem(item)
            if summary.id == selected_id:
                self.list_widget.setCurrentItem(item)

    def selected_session_id(self) -> int | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.ItemDataRole.UserRole))

    def _open_selected(self, _item: QListWidgetItem | None = None) -> None:
        session_id = self.selected_session_id()
        if session_id is not None:
            self._on_open(self._sessions[session_id])

    def _rename_selected(self) -> None:
        session_id = self.selected_session_id()
        if session_id is None:
            return
        summary = self._sessions[session_id]
        name, accepted = QInputDialog.getText(
            self,
            "Renombrar sesión",
            "Nombre:",
            text=summary.name,
        )
        if accepted:
            try:
                self._storage.rename_session(session_id, name)
            except ValueError as exc:
                QMessageBox.warning(self, "Nombre no válido", str(exc))
                return
            self.refresh()

    def _delete_selected(self) -> None:
        session_id = self.selected_session_id()
        if session_id is None:
            return
        if session_id == self._storage.active_session_id:
            QMessageBox.information(
                self,
                "Sesión activa",
                "La sesión activa no se puede eliminar.",
            )
            return
        summary = self._sessions[session_id]
        answer = QMessageBox.question(
            self,
            "Eliminar sesión",
            f"¿Eliminar '{summary.name}' y sus capturas?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._storage.delete_session(session_id)
            self.refresh()
