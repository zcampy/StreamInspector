import base64
import json

from streaminspector.har_import import flows_from_har


def test_imports_basic_har_entry() -> None:
    document = {
        "log": {
            "entries": [
                {
                    "startedDateTime": "2026-08-03T20:00:00Z",
                    "time": 123.5,
                    "request": {
                        "method": "POST",
                        "url": "https://api.example.com/items?id=1",
                        "httpVersion": "HTTP/2",
                        "headers": [{"name": "Accept", "value": "application/json"}],
                        "postData": {"text": "{\"name\":\"test\"}"},
                    },
                    "response": {
                        "status": 201,
                        "statusText": "Created",
                        "httpVersion": "HTTP/2",
                        "headers": [{"name": "Content-Type", "value": "application/json"}],
                        "content": {
                            "mimeType": "application/json",
                            "text": "{\"ok\":true}",
                            "size": 11,
                        },
                    },
                }
            ]
        }
    }

    flow = flows_from_har(json.dumps(document))[0]

    assert flow.method == "POST"
    assert flow.host == "api.example.com"
    assert flow.path == "/items?id=1"
    assert flow.status_code == 201
    assert flow.response_body == b'{"ok":true}'
    assert flow.duration_ms == 123.5


def test_decodes_base64_response_body() -> None:
    encoded = base64.b64encode(b"binary data").decode("ascii")
    document = {
        "log": {
            "entries": [
                {
                    "request": {"method": "GET", "url": "http://example.com/file"},
                    "response": {
                        "status": 200,
                        "content": {"text": encoded, "encoding": "base64"},
                    },
                }
            ]
        }
    }

    assert flows_from_har(json.dumps(document))[0].response_body == b"binary data"
