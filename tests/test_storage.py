from pathlib import Path

from streaminspector.core.events import (
    EventBus,
    HttpFlowCaptured,
    StoredHistoryDeleted,
    StoredHistoryDeleteRequested,
)
from streaminspector.storage import StorageService


def test_storage_persists_restores_and_deletes_flow(tmp_path: Path) -> None:
    event_bus = EventBus()
    storage = StorageService(event_bus, tmp_path / "sessions.sqlite3")
    deleted_events: list[StoredHistoryDeleted] = []
    event_bus.subscribe(StoredHistoryDeleted, deleted_events.append)

    original = HttpFlowCaptured(
        flow_id="flow-1",
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
