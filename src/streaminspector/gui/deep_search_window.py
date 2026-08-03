from __future__ import annotations

import json

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QInputDialog, QMessageBox, QPlainTextEdit

from streaminspector.core.events import EventBus, HttpFlowCaptured, StatusMessage
from streaminspector.deep_search import SEARCH_SCOPES, matches_flow
from streaminspector.gui.advanced_window import FLOW_ID_ROLE
from streaminspector.gui.annotation_window import AnnotationWindow
from streaminspector.storage import StorageService


class DeepSearchWindow(AnnotationWindow):
    """Main window with full-content search and reusable search presets."""

    def __init__(
        self,
        event_bus: EventBus,
        storage: StorageService,
        initial_flows: list[HttpFlowCaptured] | None = None,
    ) -> None:
        super().__init__(event_bus, storage, initial_flows=initial_flows)
        self._search_settings = QSettings("StreamInspector", "StreamInspector")
        self._deep_query = ""
        self._deep_scope = "all"
        self._case_sensitive = False
        self._install_deep_search_actions()

    def _install_deep_search_actions(self) -> None:
        menu = self.menuBar().addMenu("Buscar")

        search_action = QAction("Búsqueda profunda…", self)
        search_action.triggered.connect(self._configure_deep_search)
        menu.addAction(search_action)

        clear_action = QAction("Limpiar búsqueda profunda", self)
        clear_action.triggered.connect(self._clear_deep_search)
        menu.addAction(clear_action)

        save_action = QAction("Guardar búsqueda actual…", self)
        save_action.triggered.connect(self._save_search_preset)
        menu.addAction(save_action)

        load_action = QAction("Aplicar búsqueda guardada…", self)
        load_action.triggered.connect(self._load_search_preset)
        menu.addAction(load_action)

        delete_action = QAction("Eliminar búsqueda guardada…", self)
        delete_action.triggered.connect(self._delete_search_preset)
        menu.addAction(delete_action)

    def _configure_deep_search(self) -> None:
        query, accepted = QInputDialog.getText(
            self,
            "Búsqueda profunda",
            "Texto a buscar en las capturas:",
            text=self._deep_query,
        )
        if not accepted:
            return
        labels = list(SEARCH_SCOPES)
        current_label = next(
            (label for label, value in SEARCH_SCOPES.items() if value == self._deep_scope),
            labels[0],
        )
        scope_label, accepted = QInputDialog.getItem(
            self,
            "Ámbito de búsqueda",
            "Buscar en:",
            labels,
            labels.index(current_label),
            False,
        )
        if not accepted:
            return
        case_label, accepted = QInputDialog.getItem(
            self,
            "Coincidencia",
            "Distinguir mayúsculas y minúsculas:",
            ["No", "Sí"],
            1 if self._case_sensitive else 0,
            False,
        )
        if not accepted:
            return
        self._deep_query = query.strip()
        self._deep_scope = SEARCH_SCOPES[scope_label]
        self._case_sensitive = case_label == "Sí"
        self._apply_deep_search()

    def _apply_deep_search(self) -> None:
        by_id = {flow.flow_id: flow for flow in self._flows}
        favorites = self._storage.favorite_flow_ids()
        visible = 0
        for row in range(self.history.rowCount()):
            item = self.history.item(row, 0)
            flow_id = str(item.data(FLOW_ID_ROLE) or "") if item is not None else ""
            flow = by_id.get(flow_id)
            matched = flow is not None and matches_flow(
                flow,
                self._deep_query,
                scope=self._deep_scope,
                case_sensitive=self._case_sensitive,
            )
            favorite_hidden = self.only_favorites_action.isChecked() and flow_id not in favorites
            self.history.setRowHidden(row, not matched or favorite_hidden)
            if matched and not favorite_hidden:
                visible += 1
        self._highlight_query()
        self._event_bus.publish(
            StatusMessage(
                message=f"Búsqueda profunda: {visible} coincidencias"
                if self._deep_query
                else "Búsqueda profunda desactivada"
            )
        )

    def _clear_deep_search(self) -> None:
        self._deep_query = ""
        self._deep_scope = "all"
        self._case_sensitive = False
        self._apply_deep_search()

    def _highlight_query(self) -> None:
        for editor in self._detail_editors():
            self._highlight_editor(editor, self._deep_query, self._case_sensitive)

    @staticmethod
    def _highlight_editor(
        editor: QPlainTextEdit,
        query: str,
        case_sensitive: bool,
    ) -> None:
        editor.setExtraSelections([])
        if not query:
            return
        document = editor.document()
        cursor = QTextCursor(document)
        selections: list[QPlainTextEdit.ExtraSelection] = []
        options = (
            QTextDocument.FindFlag.FindCaseSensitively
            if case_sensitive
            else QTextDocument.FindFlag(0)
        )
        while True:
            cursor = document.find(query, cursor, options)
            if cursor.isNull():
                break
            selection = QPlainTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = QTextCharFormat()
            selection.format.setBackground(editor.palette().highlight())
            selection.format.setForeground(editor.palette().highlightedText())
            selections.append(selection)
        editor.setExtraSelections(selections)

    def _show_selected_flow(self) -> None:
        super()._show_selected_flow()
        self._highlight_query()

    def _apply_favorite_filter(self, enabled: bool) -> None:
        super()._apply_favorite_filter(enabled)
        if hasattr(self, "_deep_query"):
            self._apply_deep_search()

    def _presets(self) -> dict[str, dict[str, object]]:
        raw = str(self._search_settings.value("search/presets", "{}"))
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _write_presets(self, presets: dict[str, dict[str, object]]) -> None:
        self._search_settings.setValue(
            "search/presets",
            json.dumps(presets, ensure_ascii=False, sort_keys=True),
        )

    def _save_search_preset(self) -> None:
        if not self._deep_query:
            QMessageBox.information(
                self,
                "Guardar búsqueda",
                "Configura primero una búsqueda profunda.",
            )
            return
        name, accepted = QInputDialog.getText(
            self,
            "Guardar búsqueda",
            "Nombre de la búsqueda:",
        )
        clean_name = name.strip()
        if not accepted or not clean_name:
            return
        presets = self._presets()
        presets[clean_name] = {
            "query": self._deep_query,
            "scope": self._deep_scope,
            "case_sensitive": self._case_sensitive,
        }
        self._write_presets(presets)
        self.statusBar().showMessage(f"Búsqueda guardada: {clean_name}", 5000)

    def _load_search_preset(self) -> None:
        presets = self._presets()
        if not presets:
            QMessageBox.information(self, "Búsquedas guardadas", "No hay búsquedas guardadas.")
            return
        name, accepted = QInputDialog.getItem(
            self,
            "Aplicar búsqueda guardada",
            "Búsqueda:",
            sorted(presets),
            0,
            False,
        )
        if not accepted:
            return
        preset = presets[name]
        self._deep_query = str(preset.get("query", ""))
        self._deep_scope = str(preset.get("scope", "all"))
        self._case_sensitive = bool(preset.get("case_sensitive", False))
        self._apply_deep_search()

    def _delete_search_preset(self) -> None:
        presets = self._presets()
        if not presets:
            QMessageBox.information(self, "Búsquedas guardadas", "No hay búsquedas guardadas.")
            return
        name, accepted = QInputDialog.getItem(
            self,
            "Eliminar búsqueda guardada",
            "Búsqueda:",
            sorted(presets),
            0,
            False,
        )
        if not accepted:
            return
        presets.pop(name, None)
        self._write_presets(presets)
        self.statusBar().showMessage(f"Búsqueda eliminada: {name}", 5000)
