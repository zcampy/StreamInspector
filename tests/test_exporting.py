import base64
import json

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.exporting import (
    REDACTED_VALUE,
    flows_to_csv,
    flows_to_har,
    flows_to_json,
    sanitize_url,
)


def _flow(
    *,
    url: str = "https://example.com/api?token=secret",
    request_headers: tuple[tuple[str, str], ...] = (),
    response_headers: tuple[tuple[str, str], ...] = (),
    request_body: bytes = b'{"name":"test"}',
    response_body: bytes = b'{"ok":true}',
    request_content_type: str = "application/json",
    response_content_type: str = "application/json",
) -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id="export-1",
        method="POST",
        scheme="https",
        host="example.com",
        port=443,
        path="/api?token=secret",
        url=url,
        http_version="HTTP/2",
        status_code=201,
        reason="Created",
        content_type=response_content_type,
        request_headers=request_headers
        or (("content-type", request_content_type),),
        response_headers=response_headers
        or (("content-type", response_content_type),),
        request_body=request_body,
        response_body=response_body,
        response_size=len(response_body),
        duration_ms=25.0,
    )


def test_exports_are_sanitized_by_default() -> None:
    flow = _flow(
        request_headers=(
            ("Content-Type", "application/json"),
            ("Authorization", "Bearer secret"),
            ("Cookie", "session=secret"),
        ),
        response_headers=(("Set-Cookie", "session=secret"),),
    )
    json_text = flows_to_json([flow])
    har_text = flows_to_har([flow])
    csv_text = flows_to_csv([flow])
    for exported in (json_text, har_text, csv_text):
        assert "Bearer secret" not in exported
        assert "session=secret" not in exported
        assert "token=secret" not in exported
    assert REDACTED_VALUE in json_text
    assert REDACTED_VALUE in har_text


def test_full_export_requires_explicit_opt_in() -> None:
    flow = _flow(request_headers=(("Authorization", "Bearer secret"),))
    payload = json.loads(flows_to_json([flow], include_secrets=True))
    assert payload[0]["request"]["headers"]["Authorization"] == "Bearer secret"
    assert "token=secret" in payload[0]["request"]["url"]


def test_sanitize_url_redacts_query_and_tokenized_path() -> None:
    sanitized = sanitize_url(
        "https://cdn.example/token-abc123/index.m3u8?sig=xyz&quality=hd"
    )
    assert "abc123" not in sanitized
    assert "xyz" not in sanitized
    assert "quality=hd" in sanitized
    assert REDACTED_VALUE in sanitized
    assert "%2A%2A%2AREDACTED%2A%2A%2A" in sanitized


def test_json_body_fields_are_sanitized_recursively() -> None:
    flow = _flow(
        request_body=b'{"user":"ana","token":"abc","nested":{"password":"123"}}'
    )
    payload = json.loads(flows_to_json([flow]))
    body = json.loads(payload[0]["request"]["body"])
    assert body["user"] == "ana"
    assert body["token"] == REDACTED_VALUE
    assert body["nested"]["password"] == REDACTED_VALUE


def test_form_body_fields_are_sanitized() -> None:
    flow = _flow(
        request_body=b"user=ana&password=123&token=abc",
        request_content_type="application/x-www-form-urlencoded",
    )
    payload = json.loads(flows_to_json([flow]))
    body = payload[0]["request"]["body"]
    assert "user=ana" in body
    assert "123" not in body
    assert "abc" not in body
    assert REDACTED_VALUE.replace("*", "%2A") in body


def test_binary_json_export_uses_base64_without_data_loss() -> None:
    binary = b"\x00\xff\x10\x80binary"
    flow = _flow(
        response_body=binary,
        response_content_type="application/octet-stream",
    )
    payload = json.loads(flows_to_json([flow]))
    response = payload[0]["response"]
    assert response["body_encoding"] == "base64"
    assert base64.b64decode(response["body"]) == binary


def test_binary_har_export_uses_standard_base64_marker() -> None:
    binary = b"\x89PNG\r\n\x1a\n\x00\xff"
    flow = _flow(response_body=binary, response_content_type="image/png")
    payload = json.loads(flows_to_har([flow]))
    content = payload["log"]["entries"][0]["response"]["content"]
    assert content["encoding"] == "base64"
    assert base64.b64decode(content["text"]) == binary


def test_text_body_keeps_utf8_encoding_metadata() -> None:
    payload = json.loads(flows_to_json([_flow(response_body="áé".encode())]))
    assert payload[0]["response"]["body_encoding"] == "utf-8"
    assert payload[0]["response"]["body"] == "áé"
