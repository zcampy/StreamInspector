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
