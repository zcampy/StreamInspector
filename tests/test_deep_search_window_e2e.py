"""End-to-end tests for the main window using the event bus."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings

from streaminspector import __version__
from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.gui.deep_search_window import DeepSearchWindow
from streaminspector.gui.traffic_filters import FLOW_ID_DATA_ROLE
from streaminspector.storage import StorageService


@pytest.fixture(autouse=True)
def _suppress_onboarding() -> None:
    settings = QSettings("StreamInspector", "StreamInspector")
    settings.setValue(f"onboarding/{__version__}", True)
    settings.setValue("startup_notice/0.1.0a19", True)
    yield
    settings.remove(f"onboarding/{__version__}")
    settings.remove("startup_notice/0.1.0a19")


def _flow(
    flow_id: str,
    *,
    method: str = "GET",
    host: str = "api.example",
    path: str = "/",
    status_code: int | None = 200,
    content_type: str = "application/json",
    response_body: bytes = b"{}",
    request_body: bytes = b"",
) -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id=flow_id,
        method=method,
        scheme="https",
        host=host,
        port=443,
        path=path,
        url=f"https://{host}{path}",
        http_version="HTTP/2",
        status_code=status_code,
        reason="OK" if status_code == 200 else "Error",
        content_type=content_type,
        request_headers=(),
        response_headers=(),
        request_body=request_body,
        response_body=response_body,
        request_size=len(request_body),
        response_size=len(response_body),
        duration_ms=10.0,
    )


@pytest.fixture
def app_window(qtbot, tmp_path: Path):
    bus = EventBus()
    storage = StorageService(bus, tmp_path / "test.sqlite3")
    win = DeepSearchWindow(bus, storage, initial_flows=[])
    qtbot.addWidget(win)
    yield win, bus, storage
    storage.close()


def test_published_flow_appears_in_table(app_window) -> None:
    win, bus, _storage = app_window

    bus.publish(_flow("e2e-1", host="api.example", path="/health"))

    assert win.history.rowCount() == 1
    assert win.history.item(0, 0).text() == "1"
    assert win.history.item(0, 1).text() == "GET"
    assert win.history.item(0, 2).text() == "200"
    assert win.history.item(0, 3).text() == "api.example"


def test_multiple_flows_accumulate(app_window) -> None:
    win, bus, _storage = app_window

    for i in range(5):
        bus.publish(_flow(f"e2e-{i}", path=f"/v{i}"))

    assert win.history.rowCount() == 5
    paths = {win.history.item(i, 4).text() for i in range(5)}
    assert paths == {"/v0", "/v1", "/v2", "/v3", "/v4"}


def test_filter_by_method_hides_rows(app_window) -> None:
    win, bus, _storage = app_window
    bus.publish(_flow("g1", method="GET"))
    bus.publish(_flow("p1", method="POST"))
    bus.publish(_flow("d1", method="DELETE"))

    win.filter_bar.method_filter.setCurrentText("GET")

    visible = [i for i in range(win.history.rowCount()) if not win.history.isRowHidden(i)]
    assert len(visible) == 1
    # El flow GET debe ser el único visible, esté en la fila que esté tras el sort.
    assert win.history.item(visible[0], 1).text() == "GET"


def test_filter_by_status_hides_5xx(app_window) -> None:
    win, bus, _storage = app_window
    bus.publish(_flow("ok", status_code=200))
    bus.publish(_flow("err", status_code=500))

    win.filter_bar.status_filter.setCurrentText("5xx")

    visible = [i for i in range(win.history.rowCount()) if not win.history.isRowHidden(i)]
    assert len(visible) == 1
    assert win.history.item(visible[0], 2).text() == "500"


def test_filter_by_domain(app_window) -> None:
    win, bus, _storage = app_window
    bus.publish(_flow("a", host="a.example"))
    bus.publish(_flow("b", host="b.example"))

    win.filter_bar.domain_filter.setCurrentText("a.example")

    visible = [i for i in range(win.history.rowCount()) if not win.history.isRowHidden(i)]
    assert len(visible) == 1
    assert win.history.item(visible[0], 3).text() == "a.example"


def test_favorite_mark_persists(app_window) -> None:
    win, bus, storage = app_window
    bus.publish(_flow("fav-1"))
    win.history.setCurrentCell(0, 0)

    win._toggle_favorite()
    assert "fav-1" in storage.favorite_flow_ids()

    win.history.setCurrentCell(0, 0)
    win._toggle_favorite()
    assert "fav-1" not in storage.favorite_flow_ids()


def test_only_favorites_filter(app_window) -> None:
    win, bus, _storage = app_window
    bus.publish(_flow("a"))
    bus.publish(_flow("b"))
    bus.publish(_flow("c"))

    # Marcar la del medio (b) como favorita: el orden de fila no es estable
    # porque la tabla ordena por la columna "#" en sentido descendente, así
    # que localizamos el flow por su flow_id antes de seleccionarlo.
    for row in range(win.history.rowCount()):
        if win.history.item(row, 0).data(FLOW_ID_DATA_ROLE) == "b":
            win.history.setCurrentCell(row, 0)
            break
    win._toggle_favorite()

    win.only_favorites_action.setChecked(True)

    visible = [i for i in range(win.history.rowCount()) if not win.history.isRowHidden(i)]
    assert len(visible) == 1


def test_deep_search_hides_non_matching(app_window) -> None:
    win, bus, _storage = app_window
    bus.publish(_flow("a", path="/login"))
    bus.publish(_flow("b", path="/logout"))
    bus.publish(_flow("c", path="/api/users"))

    win._deep_query = "login"
    win._deep_scope = "all"
    win._apply_deep_search()

    visible = [i for i in range(win.history.rowCount()) if not win.history.isRowHidden(i)]
    assert len(visible) == 1
    path = win.history.item(visible[0], 4).text()
    assert path == "/login"


def test_persisted_flows_appear_on_reload(qtbot, tmp_path: Path) -> None:
    bus1 = EventBus()
    storage1 = StorageService(bus1, tmp_path / "test.sqlite3")
    bus1.publish(_flow("pre-1"))
    bus1.publish(_flow("pre-2"))
    storage1.close()

    bus2 = EventBus()
    storage2 = StorageService(bus2, tmp_path / "test.sqlite3")
    try:
        # El bootstrap real carga los initial_flows desde `recent_events`; el
        # test simula ese patrón en lugar de pasar lista vacía.
        restored = storage2.recent_events(limit=500)
        win = DeepSearchWindow(bus2, storage2, initial_flows=restored)
        qtbot.addWidget(win)
        assert win.history.rowCount() == 2
        ids = {
            win.history.item(i, 0).data(FLOW_ID_DATA_ROLE)
            for i in range(win.history.rowCount())
        }
        assert ids == {"pre-1", "pre-2"}
    finally:
        storage2.close()
