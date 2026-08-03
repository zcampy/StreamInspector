from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QInputDialog, QMessageBox

from streaminspector.core.events import EventBus, HttpFlowCaptured, StatusMessage
from streaminspector.gui.advanced_window import FLOW_ID_ROLE
from streaminspector.gui.har_import_window import HarImportWindow
from streaminspector.storage import FlowAnnotationData, StorageService


class AnnotationWindow(HarImportWindow):
    """Main window with persistent organization metadata for captures."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self._install_annotation_actions()
        self._refresh_annotation_marks()

    def _install_annotation_actions(self) -> None:
        menu = self.menuBar().addMenu("Organizar")

        favorite_action = QAction("Marcar o desmarcar como favorita", self)
        favorite_action.triggered.connect(self._toggle_favorite)
        menu.addAction(favorite_action)

        tags_action = QAction("Editar etiquetas…", self)
        tags_action.triggered.connect(self._edit_tags)
        menu.addAction(tags_action)

        note_action = QAction("Editar nota…", self)
        note_action.triggered.connect(self._edit_note)
        menu.addAction(note_action)

        show_action = QAction("Ver anotación…", self)
        show_action.triggered.connect(self._show_annotation)
        menu.addAction(show_action)

        menu.addSeparator()
        self.only_favorites_action = QAction("Mostrar solo favoritas", self)
        self.only_favorites_action.setCheckable(True)
        self.only_favorites_action.toggled.connect(self._apply_favorite_filter)
        menu.addAction(self.only_favorites_action)

    def _selected_annotation(self) -> tuple[HttpFlowCaptured, FlowAnnotationData] | None:
        flow = self._selected_flow()
        if flow is None:
            QMessageBox.information(self, "Organizar captura", "Selecciona una captura primero.")
            return None
        return flow, self._storage.get_annotation(flow.flow_id)

    def _toggle_favorite(self) -> None:
        selected = self._selected_annotation()
        if selected is None:
            return
        flow, annotation = selected
        self._save_annotation(
            flow,
            favorite=not annotation.favorite,
            tags=annotation.tags,
            note=annotation.note,
        )
        state = "marcada como favorita" if not annotation.favorite else "eliminada de favoritas"
        self._event_bus.publish(StatusMessage(message=f"Captura {state}"))

    def _edit_tags(self) -> None:
        selected = self._selected_annotation()
        if selected is None:
            return
        flow, annotation = selected
        value, accepted = QInputDialog.getText(
            self,
            "Etiquetas de la captura",
            "Etiquetas separadas por comas:",
            text=annotation.tags,
        )
        if accepted:
            self._save_annotation(
                flow,
                favorite=annotation.favorite,
                tags=value,
                note=annotation.note,
            )

    def _edit_note(self) -> None:
        selected = self._selected_annotation()
        if selected is None:
            return
        flow, annotation = selected
        value, accepted = QInputDialog.getMultiLineText(
            self,
            "Nota de la captura",
            "Observaciones:",
            annotation.note,
        )
        if accepted:
            self._save_annotation(
                flow,
                favorite=annotation.favorite,
                tags=annotation.tags,
                note=value,
            )

    def _show_annotation(self) -> None:
        selected = self._selected_annotation()
        if selected is None:
            return
        flow, annotation = selected
        QMessageBox.information(
            self,
            "Anotación de la captura",
            f"URL: {flow.url}\n\n"
            f"Favorita: {'sí' if annotation.favorite else 'no'}\n"
            f"Etiquetas: {annotation.tags or 'Ninguna'}\n\n"
            f"Nota:\n{annotation.note or 'Sin nota'}",
        )

    def _save_annotation(
        self,
        flow: HttpFlowCaptured,
        *,
        favorite: bool,
        tags: str,
        note: str,
    ) -> None:
        self._storage.save_annotation(
            flow.flow_id,
            favorite=favorite,
            tags=tags,
            note=note,
        )
        self._refresh_annotation_marks()
        self._apply_favorite_filter(self.only_favorites_action.isChecked())

    def _append_flow(self, event: HttpFlowCaptured) -> None:
        super()._append_flow(event)
        if hasattr(self, "only_favorites_action"):
            self._refresh_annotation_marks()
            self._apply_favorite_filter(self.only_favorites_action.isChecked())

    def _refresh_annotation_marks(self) -> None:
        favorites = self._storage.favorite_flow_ids()
        for row in range(self.history.rowCount()):
            item = self.history.item(row, 0)
            if item is None:
                continue
            flow_id = str(item.data(FLOW_ID_ROLE) or "")
            base_text = item.text().removeprefix("★ ")
            item.setText(f"★ {base_text}" if flow_id in favorites else base_text)

    def _apply_favorite_filter(self, enabled: bool) -> None:
        favorites = self._storage.favorite_flow_ids()
        for row in range(self.history.rowCount()):
            item = self.history.item(row, 0)
            flow_id = str(item.data(FLOW_ID_ROLE) or "") if item is not None else ""
            self.history.setRowHidden(row, enabled and flow_id not in favorites)
        self.statusBar().showMessage(
            "Mostrando solo capturas favoritas" if enabled else "Filtro de favoritas desactivado",
            5000,
        )
