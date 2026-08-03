DARK_STYLESHEET = """
QWidget {
    background-color: #17191d;
    color: #e6e8eb;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QMainWindow, QMenuBar, QMenu, QStatusBar, QToolBar {
    background-color: #1f2228;
}
QMenuBar::item:selected, QMenu::item:selected {
    background-color: #343943;
}
QLineEdit, QPlainTextEdit, QTextEdit, QTableView, QTreeView, QTabWidget::pane {
    background-color: #111318;
    border: 1px solid #353a44;
    selection-background-color: #365f91;
}
QHeaderView::section {
    background-color: #272b33;
    border: 0;
    border-right: 1px solid #3a3f49;
    padding: 6px;
}
QPushButton {
    background-color: #2f69a1;
    border: 1px solid #3b7ebd;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover { background-color: #397ab7; }
QPushButton:disabled { background-color: #30343b; color: #777c85; }
QSplitter::handle { background-color: #30343b; }
"""
