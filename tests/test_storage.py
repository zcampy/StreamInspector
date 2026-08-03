from pathlib import Path

from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.storage import StorageService


def test_storage_persists_and_loads_flow(tmp_path: Path) -> None:
    event_bus = EventBus()
    storage = StorageService(event_bus, tmp_path / "sessions.sqlite3")

    event_bus.publish(
        HttpFlowCaptured(
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
            response_body=b'{"ok": true}',
            response_size=12,
        )
    )

    flows = storage.recent()
    assert len(flows) == 1
    assert flows[0].host == "example.com"
    assert flows[0].response_body == b'{"ok": true}'
    storage.close()
