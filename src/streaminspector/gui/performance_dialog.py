from __future__ import annotations

from collections import Counter
from statistics import mean, median

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from streaminspector.core.events import HttpFlowCaptured


def performance_summary(flows: list[HttpFlowCaptured]) -> dict[str, float | int | str]:
    durations = [flow.duration_ms for flow in flows if flow.duration_ms is not None]
    errors = sum(1 for flow in flows if flow.status_code is not None and flow.status_code >= 400)
    total_bytes = sum(flow.request_size + flow.response_size for flow in flows)
    return {
        "requests": len(flows),
        "errors": errors,
        "error_rate": (errors / len(flows) * 100) if flows else 0.0,
        "total_bytes": total_bytes,
        "average_ms": mean(durations) if durations else 0.0,
        "median_ms": median(durations) if durations else 0.0,
        "maximum_ms": max(durations, default=0.0),
    }


class PerformanceDialog(QDialog):
    """Session-level HTTP performance and traffic overview."""

    def __init__(self, flows: list[HttpFlowCaptured], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rendimiento de la sesión")
        self.resize(920, 620)

        layout = QVBoxLayout(self)
        summary = performance_summary(flows)
        metrics = QFormLayout()
        metrics.addRow("Peticiones", QLabel(str(summary["requests"])))
        metrics.addRow("Errores HTTP", QLabel(str(summary["errors"])))
        metrics.addRow("Tasa de error", QLabel(f"{summary['error_rate']:.1f} %"))
        metrics.addRow("Tiempo medio", QLabel(f"{summary['average_ms']:.1f} ms"))
        metrics.addRow("Mediana", QLabel(f"{summary['median_ms']:.1f} ms"))
        metrics.addRow("Máximo", QLabel(f"{summary['maximum_ms']:.1f} ms"))
        metrics.addRow("Tráfico total", QLabel(_format_bytes(int(summary["total_bytes"]))))
        layout.addLayout(metrics)

        tabs = QTabWidget()
        tabs.addTab(_slowest_table(flows), "Más lentas")
        tabs.addTab(_largest_table(flows), "Más pesadas")
        tabs.addTab(_domains_table(flows), "Dominios")
        tabs.addTab(_status_table(flows), "Estados")
        layout.addWidget(tabs, 1)


def _base_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSortingEnabled(True)
    return table


def _slowest_table(flows: list[HttpFlowCaptured]) -> QTableWidget:
    table = _base_table(["Método", "Estado", "Tiempo", "URL"])
    ranked = sorted(flows, key=lambda flow: flow.duration_ms or 0, reverse=True)[:100]
    table.setRowCount(len(ranked))
    for row, flow in enumerate(ranked):
        values = [flow.method, str(flow.status_code or ""), f"{flow.duration_ms or 0:.1f} ms", flow.url]
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(value))
    table.resizeColumnsToContents()
    return table


def _largest_table(flows: list[HttpFlowCaptured]) -> QTableWidget:
    table = _base_table(["Método", "Estado", "Tamaño", "URL"])
    ranked = sorted(flows, key=lambda flow: flow.request_size + flow.response_size, reverse=True)[:100]
    table.setRowCount(len(ranked))
    for row, flow in enumerate(ranked):
        values = [
            flow.method,
            str(flow.status_code or ""),
            _format_bytes(flow.request_size + flow.response_size),
            flow.url,
        ]
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(value))
    table.resizeColumnsToContents()
    return table


def _domains_table(flows: list[HttpFlowCaptured]) -> QTableWidget:
    table = _base_table(["Dominio", "Peticiones", "Errores", "Bytes"])
    counts = Counter(flow.host or "(sin dominio)" for flow in flows)
    errors = Counter(
        flow.host or "(sin dominio)"
        for flow in flows
        if flow.status_code is not None and flow.status_code >= 400
    )
    sizes: Counter[str] = Counter()
    for flow in flows:
        sizes[flow.host or "(sin dominio)"] += flow.request_size + flow.response_size
    rows = counts.most_common()
    table.setRowCount(len(rows))
    for row, (host, count) in enumerate(rows):
        values = [host, str(count), str(errors[host]), _format_bytes(sizes[host])]
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(value))
    table.resizeColumnsToContents()
    return table


def _status_table(flows: list[HttpFlowCaptured]) -> QTableWidget:
    table = _base_table(["Familia", "Peticiones"])
    counts = Counter(
        "Sin respuesta" if flow.status_code is None else f"{flow.status_code // 100}xx"
        for flow in flows
    )
    rows = sorted(counts.items())
    table.setRowCount(len(rows))
    for row, (status, count) in enumerate(rows):
        table.setItem(row, 0, QTableWidgetItem(status))
        table.setItem(row, 1, QTableWidgetItem(str(count)))
    table.resizeColumnsToContents()
    return table


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
