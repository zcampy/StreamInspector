from pathlib import Path

import pytest

from streaminspector.core.events import (
    EventBus,
    HttpFlowCaptured,
    StoredHistoryDeleted,
    StoredHistoryDeleteRequested,
)
from streaminspector.storage import StorageService


def _flow(flow_id: str = "flow-1") -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id=flow_id,
        method="GET",
        scheme="https",
        host="example.com",
        port=443,
        path="/api",
        url="https://example.com/api",
        http_version="HTTP/2",
        status_code=200,
        reason="OK",
        content_type="application/json",
        request_headers=(("accept", "application/json"),),
        response_headers=(("content-type", "application/json"),),
        request_body=b"request-body",
        response_body=b'{"ok": true}',
        response_size=12,
    )


def test_storage_persists_restores_and_deletes_flow(tmp_path: Path) -> None:
    event_bus = EventBus()
    storage = StorageService(event_bus, tmp_path / "sessions.sqlite3")
    deleted_events: list[StoredHistoryDeleted] = []
    event_bus.subscribe(StoredHistoryDeleted, deleted_events.append)

    original = _flow()
    event_bus.publish(original)

    restored = storage.recent_events()
    assert len(restored) == 1
    assert restored[0].host == "example.com"
    assert restored[0].request_headers == original.request_headers
    assert restored[0].response_body == b'{"ok": true}'
    assert restored[0].created_at == original.created_at

    event_bus.publish(StoredHistoryDeleteRequested())
    assert storage.recent_events() == []
    assert deleted_events[0].deleted_count == 1
    storage.close()


def test_storage_groups_flows_by_capture_session(tmp_path: Path) -> None:
    event_bus = EventBus()
    storage = StorageService(event_bus, tmp_path / "sessions.sqlite3")
    active_session_id = storage.active_session_id

    event_bus.publish(_flow("flow-session-1"))

    sessions = storage.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].id == active_session_id
    assert sessions[0].flow_count == 1

    session_flows = storage.session_events(active_session_id)
    assert [flow.flow_id for flow in session_flows] == ["flow-session-1"]

    storage.rename_session(active_session_id, "Prueba API")
    assert storage.list_sessions()[0].name == "Prueba API"
    storage.close()


def test_storage_deletes_only_inactive_session(tmp_path: Path) -> None:
    event_bus = EventBus()
    storage = StorageService(event_bus, tmp_path / "sessions.sqlite3")
    disposable_id = storage.create_session("Descartable")

    assert storage.delete_session(disposable_id) == 0
    assert all(item.id != disposable_id for item in storage.list_sessions())

    with pytest.raises(ValueError, match="activa"):
        storage.delete_session(storage.active_session_id)
    storage.close()


def test_storage_migrates_existing_db_adding_request_size(tmp_path: Path) -> None:
    """BDs creadas antes de añadir `request_size` deben actualizarse sin perder datos."""
    from sqlalchemy import create_engine, text

    database = tmp_path / "legacy.sqlite3"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as conn:
        # Esquema "antiguo" sin request_size.
        conn.execute(
            text(
                "CREATE TABLE captured_flows ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "flow_id VARCHAR(64) UNIQUE, "
                "captured_at DATETIME, "
                "method VARCHAR(16), "
                "scheme VARCHAR(16), "
                "host VARCHAR(255), "
                "port INTEGER, "
                "path TEXT, "
                "url TEXT, "
                "http_version VARCHAR(32), "
                "status_code INTEGER, "
                "reason VARCHAR(255), "
                "content_type VARCHAR(255), "
                "request_headers_json TEXT, "
                "response_headers_json TEXT, "
                "request_body BLOB, "
                "response_body BLOB, "
                "response_size INTEGER, "
                "duration_ms FLOAT"
                ")"
            )
        )

    event_bus = EventBus()
    storage = StorageService(event_bus, database)
    try:
        # El esquema nuevo debe tener la columna tras la migración.
        with storage._engine.connect() as conn:
            columns = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(captured_flows)")).all()
            }
        assert "request_size" in columns

        # Persistir un flow usa el campo sin error.
        storage._store_flow(
            HttpFlowCaptured(
                flow_id="legacy-1",
                method="GET",
                host="legacy.example",
                url="https://legacy.example/",
                path="/",
                request_body=b"hi",
                response_body=b"{}",
                request_size=2,
                response_size=2,
            )
        )
        restored = storage.recent_events(limit=5)
        assert len(restored) == 1
        assert restored[0].request_size == 2
    finally:
        storage.close()


def test_storage_persists_request_size_round_trip(tmp_path: Path) -> None:
    event_bus = EventBus()
    storage = StorageService(event_bus, tmp_path / "sessions.sqlite3")
    try:
        event_bus.publish(
            HttpFlowCaptured(
                flow_id="size-1",
                method="POST",
                host="api.example",
                url="https://api.example/v1",
                path="/v1",
                request_body=b"payload",
                response_body=b"{}",
                request_size=7,
                response_size=2,
            )
        )
        restored = storage.recent_events(limit=5)
        assert restored[0].request_size == 7
        assert restored[0].response_size == 2
    finally:
        storage.close()
