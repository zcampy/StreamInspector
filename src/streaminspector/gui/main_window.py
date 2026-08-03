from __future__ import annotations

import json
import webbrowser

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
)

from streaminspector.core.events import (
    EventBus,
    HttpFlowCaptured,
    ProxyError,
    ProxyStartRequested,
    ProxyStateChanged,
    ProxyStopRequested,
    StatusMessage,
)


class _QtEventBridge(QObject):
    status = Signal(object)
    proxy_state = Signal(object)
    proxy_error = Signal(object)
    flow = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, event_bus: EventBus) -> None:
        super().__init__()
        self._event_bus = event_bus
        self._domains: dict[str, QTreeWidgetItem] = {}
        self._flows: list[HttpFlowCaptured] = []
        self._bridge = _QtEventBridge(self)
        self._bridge.status.connect(self._on_status_message)
        self._bridge.proxy_state.connect(self._on_proxy_state_changed)
        self._bridge.proxy_error.connect(self._on_proxy_error)
        self._bridge.flow.connect(self._on_flow_captured)

        self.setWindowTitle("StreamInspector Pro — 0.1 Alpha")
        self.resize(1380, 820)
        self._build_actions()
        self._build_toolbar()
        self._build_central_area()
        self._build_domain_dock()
        self._build_status_bar()
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        self._event_bus.subscribe(StatusMessage, self._bridge.status.emit)
        self._event_bus.subscribe(ProxyStateChanged, self._bridge.proxy_state.emit)
        self._event_bus.subscribe(ProxyError, self._bridge.proxy_error.emit)
        self._event_bus.subscribe(HttpFlowCaptured, self._bridge.flow.emit)

    def _build_actions(self) -> None:
        self.action_exit = QAction("Salir", self)
        self.action_exit.triggered.connect(self.close)
        self.action_clear = QAction("Limpiar historial", self)
        self.action_clear.triggered.connect(self._clear_history)

        file_menu = self.menuBar().addMenu("Archivo")
        file_menu.addAction(self.action_exit)
        tools_menu = self.menuBar().addMenu("Herramientas")
        tools_menu.addAction(self.action_clear)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Navegación", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com")
        self.url_edit.setClearButtonEnabled(True)
        toolbar.addWidget(QLabel(" URL "))
        toolbar.addWidget(self.url_edit)

        open_button = QPushButton("Abrir")
        open_button.clicked.connect(self._open_requested_url)
        toolbar.addWidget(open_button)

        self.proxy_button = QPushButton("Proxy OFF")
        self.proxy_button.setCheckable(True)
        self.proxy_button.toggled.connect(self._toggle_proxy)
        toolbar.addWidget(self.proxy_button)

    def _build_central_area(self) -> None:
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.history = QTableWidget(0, 8)
        self.history.setHorizontalHeaderLabels(
            ["#", "Método", "Estado", "Host", "Ruta", "Tipo", "Tamaño", "Tiempo"]
        )
        self.history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history.setAlternatingRowColors(True)
        self.history.verticalHeader().setVisible(False)
        self.history.itemSelectionChanged.connect(self._show_selected_flow)
        header = self.history.horizontalHeader()
        for column in (0, 1, 2, 3, 5, 6, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.details = QTabWidget()
        self.request_view = self._add_text_tab("Petición")
        self.response_view = self._add_text_tab("Respuesta")
        self.headers_view = self._add_text_tab("Headers")
        self.body_view = self._add_text_tab("Body")
        self.json_view = self._add_text_tab("JSON")

        splitter.addWidget(self.history)
        splitter.addWidget(self.details)
        splitter.setSizes([500, 260])
        self.setCentralWidget(splitter)

    def _add_text_tab(self, title: str) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlaceholderText("Selecciona una captura")
        self.details.addTab(editor, title)
        return editor

    def _build_domain_dock(self) -> None:
        dock = QDockWidget("Dominios", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.domain_tree = QTreeWidget()
        self.domain_tree.setHeaderHidden(True)
        self._reset_domain_tree()
        dock.setWidget(self.domain_tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_status_bar(self) -> None:
        status = QStatusBar(self)
        status.showMessage("Preparado — activa el proxy para comenzar")
        self.setStatusBar(status)

    def _open_requested_url(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self._event_bus.publish(StatusMessage(message="Introduce una URL"))
            return
        if "://" not in url:
            url = f"https://{url}"
        webbrowser.open(url)
        self._event_bus.publish(StatusMessage(message=f"Abriendo {url}"))

    def _toggle_proxy(self, enabled: bool) -> None:
        self.proxy_button.setEnabled(False)
        event = ProxyStartRequested() if enabled else ProxyStopRequested()
        self._event_bus.publish(event)

    def _clear_history(self) -> None:
        self.history.setRowCount(0)
        self._flows.clear()
        self._reset_domain_tree()
        for editor in self._detail_editors():
            editor.clear()
        self._event_bus.publish(StatusMessage(message="Historial limpiado"))

    def _reset_domain_tree(self) -> None:
        self.domain_tree.clear()
        self._domains.clear()
        self._domain_root = QTreeWidgetItem(["Sesión actual"])
        self.domain_tree.addTopLevelItem(self._domain_root)
        self._domain_root.setExpanded(True)

    def _detail_editors(self) -> tuple[QPlainTextEdit, ...]:
        return (
            self.request_view,
            self.response_view,
            self.headers_view,
            self.body_view,
            self.json_view,
        )

    @Slot(object)
    def _on_status_message(self, event: StatusMessage) -> None:
        self.statusBar().showMessage(event.message, 6000)

    @Slot(object)
    def _on_proxy_state_changed(self, event: ProxyStateChanged) -> None:
        self.proxy_button.blockSignals(True)
        self.proxy_button.setChecked(event.running)
        self.proxy_button.setText("Proxy ON" if event.running else "Proxy OFF")
        self.proxy_button.setEnabled(True)
        self.proxy_button.blockSignals(False)
        if event.running:
            self.statusBar().showMessage(f"Proxy activo en {event.host}:{event.port}")
        else:
            self.statusBar().showMessage("Proxy detenido")

    @Slot(object)
    def _on_proxy_error(self, event: ProxyError) -> None:
        self.proxy_button.blockSignals(True)
        self.proxy_button.setChecked(False)
        self.proxy_button.setText("Proxy OFF")
        self.proxy_button.setEnabled(True)
        self.proxy_button.blockSignals(False)
        self.statusBar().showMessage(f"Error del proxy: {event.message}", 10000)

    @Slot(object)
    def _on_flow_captured(self, event: HttpFlowCaptured) -> None:
        row = self.history.rowCount()
        self._flows.append(event)
        self.history.insertRow(row)
        duration = "" if event.duration_ms is None else f"{event.duration_ms:.0f} ms"
        values = [
            str(row + 1),
            event.method,
            "" if event.status_code is None else str(event.status_code),
            event.host,
            event.path,
            event.content_type.split(";", 1)[0],
            _format_bytes(event.response_size),
            duration,
        ]
        for column, value in enumerate(values):
            self.history.setItem(row, column, QTableWidgetItem(value))

        if event.host not in self._domains:
            item = QTreeWidgetItem([event.host])
            self._domains[event.host] = item
            self._domain_root.addChild(item)

    def _show_selected_flow(self) -> None:
        row = self.history.currentRow()
        if row < 0 or row >= len(self._flows):
            return
        flow = self._flows[row]
        request_headers = _format_headers(flow.request_headers)
        response_headers = _format_headers(flow.response_headers)
        request_body = _decode_body(flow.request_body)
        response_body = _decode_body(flow.response_body)

        self.request_view.setPlainText(
            f"{flow.method} {flow.url} {flow.http_version}\n\n{request_headers}\n\n{request_body}"
        )
        self.response_view.setPlainText(
            f"{flow.http_version} {flow.status_code or ''} {flow.reason}\n\n"
            f"{response_headers}\n\n{response_body}"
        )
        self.headers_view.setPlainText(
            f"REQUEST\n{request_headers}\n\nRESPONSE\n{response_headers}"
        )
        self.body_view.setPlainText(response_body)
        self.json_view.setPlainText(_pretty_json(response_body))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self._event_bus.publish(ProxyStopRequested())
        super().closeEvent(event)


def _format_headers(headers: tuple[tuple[str, str], ...]) -> str:
    return "\n".join(f"{name}: {value}" for name, value in headers)


def _decode_body(body: bytes) -> str:
    if not body:
        return ""
    return body.decode("utf-8", errors="replace")


def _pretty_json(text: str) -> str:
    if not text.strip():
        return ""
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return "El cuerpo seleccionado no contiene JSON válido."


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
