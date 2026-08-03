from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.storage import FlowAnnotationData, StorageService


def test_poc_capture_annotation_survives_restart(tmp_path):
    database = tmp_path / "poc.sqlite3"
    flow = HttpFlowCaptured(
        flow_id="poc-login-001",
        method="POST",
        scheme="https",
        host="api.example.test",
        port=443,
        path="/login",
        url="https://api.example.test/login",
        http_version="HTTP/2",
        status_code=401,
        reason="Unauthorized",
        content_type="application/json",
        request_headers=(("content-type", "application/json"),),
        response_headers=(("content-type", "application/json"),),
        request_body=b'{"user":"demo"}',
        response_body=b'{"error":"invalid credentials"}',
        response_size=31,
        duration_ms=125.5,
    )

    first_bus = EventBus()
    first_storage = StorageService(first_bus, database)
    first_session_id = first_storage.active_session_id
    first_bus.publish(flow)
    first_storage.save_annotation(
        flow.flow_id,
        favorite=True,
        tags="login, error, poc",
        note="Validar respuesta 401 y tratamiento del token.",
    )
    first_storage.close()

    second_storage = StorageService(EventBus(), database)
    try:
        restored = second_storage.session_events(first_session_id)
        assert len(restored) == 1
        assert restored[0].flow_id == flow.flow_id
        assert restored[0].status_code == 401
        assert restored[0].response_body == flow.response_body
        assert second_storage.get_annotation(flow.flow_id) == FlowAnnotationData(
            favorite=True,
            tags="login, error, poc",
            note="Validar respuesta 401 y tratamiento del token.",
        )
        assert second_storage.favorite_flow_ids() == {flow.flow_id}
    finally:
        second_storage.close()
