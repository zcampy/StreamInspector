from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDockWidget,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from streaminspector.core.events import EventBus, StatusMessage


class MainWindow(QMainWindow):
    def __init__(self, event_bus: EventBus) -> None:
        super().__init__()
        self._event_bus = event_bus
        self.setWindowTitle("StreamInspector Pro — 0.1 Alpha")
        self.resize(1380, 820)
        self._build_actions()
        self._build_toolbar()
        self._build_central_area()
        self._build_domain_dock()
        self._build_status_bar()
        self._event_bus.subscribe(StatusMessage, self._on_status_message)

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
        self.proxy_button.toggled.connect(self._toggle_proxy_placeholder)
        toolbar.addWidget(self.proxy_button)

    def _build_central_area(self) -> None:
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.history = QTableWidget(0, 7)
        self.history.setHorizontalHeaderLabels(
            ["#", "Método", "Estado", "Host", "Ruta", "Tipo", "Tamaño"]
        )
        self.history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history.setAlternatingRowColors(True)
        self.history.verticalHeader().setVisible(False)
        header = self.history.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.details = QTabWidget()
        for name in ("Petición", "Respuesta", "Headers", "Cookies", "JSON", "HTML", "Hex"):
            placeholder = QLabel(f"Selecciona una entrada para ver: {name}")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.details.addTab(placeholder, name)

        splitter.addWidget(self.history)
        splitter.addWidget(self.details)
        splitter.setSizes([500, 260])
        self.setCentralWidget(splitter)

    def _build_domain_dock(self) -> None:
        dock = QDockWidget("Dominios", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.domain_tree = QTreeWidget()
        self.domain_tree.setHeaderHidden(True)
        root = QTreeWidgetItem(["Sesión actual"])
        self.domain_tree.addTopLevelItem(root)
        root.setExpanded(True)
        dock.setWidget(self.domain_tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_status_bar(self) -> None:
        status = QStatusBar(self)
        status.showMessage("Preparado — proxy aún no implementado")
        self.setStatusBar(status)

    def _open_requested_url(self) -> None:
        url = self.url_edit.text().strip()
        message = f"URL preparada: {url}" if url else "Introduce una URL"
        self._event_bus.publish(StatusMessage(message=message))

    def _toggle_proxy_placeholder(self, enabled: bool) -> None:
        self.proxy_button.setText("Proxy ON" if enabled else "Proxy OFF")
        state = "activado" if enabled else "desactivado"
        self._event_bus.publish(StatusMessage(message=f"Proxy {state} (simulado en Foundation)"))

    def _clear_history(self) -> None:
        self.history.setRowCount(0)
        self.domain_tree.clear()
        self.domain_tree.addTopLevelItem(QTreeWidgetItem(["Sesión actual"]))
        self._event_bus.publish(StatusMessage(message="Historial limpiado"))

    def add_demo_row(self) -> None:
        row = self.history.rowCount()
        self.history.insertRow(row)
        values = [str(row + 1), "GET", "200", "example.com", "/", "HTML", "1.2 KB"]
        for column, value in enumerate(values):
            self.history.setItem(row, column, QTableWidgetItem(value))

    def _on_status_message(self, event: StatusMessage) -> None:
        self.statusBar().showMessage(event.message, 6000)
