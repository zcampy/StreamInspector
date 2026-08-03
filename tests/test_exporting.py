import json

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.exporting import flows_to_csv, flows_to_har, flows_to_json, format_request


def _flow() -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id="export-1",
        method="POST",
        scheme="https",
        host="example.com",
        port=443,
        path="/api",
        url="https://example.com/api",
        http_version="HTTP/2",
        status_code=201,
        reason="Created",
        content_type="application/json",
        request_headers=(("content-type", "application/json"),),
        response_headers=(("content-type", "application/json"),),
        request_body=b'{"name": "test"}',
        response_body=b'{"ok": true}',
        response_size=12,
        duration_ms=25.0,
    )


def test_export_serializers_include_flow_data() -> None:
    flow = _flow()

    csv_text = flows_to_csv([flow])
    json_payload = json.loads(flows_to_json([flow]))
    har_payload = json.loads(flows_to_har([flow]))

    assert "https://example.com/api" in csv_text
    assert json_payload[0]["request"]["method"] == "POST"
    assert har_payload["log"]["entries"][0]["response"]["status"] == 201
    assert format_request(flow).startswith("POST https://example.com/api HTTP/2")
