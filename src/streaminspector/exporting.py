from __future__ import annotations

import base64
import csv
import io
import json
import re
from datetime import UTC
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from streaminspector.core.events import HttpFlowCaptured

SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-csrf-token",
        "x-xsrf-token",
        "x-access-token",
        "x-session-token",
        "www-authenticate",
        "api-key",
        "x-shopify-access-token",
        "x-shopify-storefront-access-token",
    }
)

SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "key",
        "signature",
        "sig",
        "auth",
        "authorization",
        "session",
        "sessionid",
        "jwt",
        "password",
        "passwd",
        "secret",
        "client_secret",
    }
)

REDACTED_VALUE = "***REDACTED***"
_TOKEN_PATH_RE = re.compile(r"(?i)(/(?:token|auth|session|key)[-_])([^/?#]+)")


def is_sensitive_header(name: str) -> bool:
    return name.lower() in SENSITIVE_HEADERS


def is_sensitive_field(name: str) -> bool:
    normalized = name.strip().lower().replace("-", "_")
    return normalized in SENSITIVE_FIELDS


def count_sensitive_headers(flows: list[HttpFlowCaptured]) -> int:
    count = 0
    for flow in flows:
        count += sum(is_sensitive_header(name) for name, _ in flow.request_headers)
        count += sum(is_sensitive_header(name) for name, _ in flow.response_headers)
    return count


def _redact_headers(
    headers: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, REDACTED_VALUE if is_sensitive_header(name) else value)
        for name, value in headers
    )


def sanitize_url(url: str) -> str:
    """Redacta secretos habituales en query string y rutas tokenizadas."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    query = urlencode(
        [
            (name, REDACTED_VALUE if is_sensitive_field(name) else value)
            for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        ],
        doseq=True,
    )
    path = _TOKEN_PATH_RE.sub(r"\1" + REDACTED_VALUE, parsed.path)
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, parsed.fragment))


def _header_value(headers: tuple[tuple[str, str], ...], name: str) -> str:
    target = name.lower()
    for header_name, value in headers:
        if header_name.lower() == target:
            return value
    return ""


def _mime_only(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _looks_textual(content_type: str, body: bytes) -> bool:
    mime = _mime_only(content_type)
    if (
        mime.startswith("text/")
        or mime.endswith("+json")
        or mime.endswith("+xml")
        or mime
        in {
            "application/json",
            "application/xml",
            "application/javascript",
            "application/x-javascript",
            "application/x-www-form-urlencoded",
            "application/vnd.apple.mpegurl",
            "application/x-mpegurl",
            "application/dash+xml",
            "image/svg+xml",
        }
    ):
        return True
    if not body:
        return True
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    control_count = sum(ord(char) < 32 and char not in "\r\n\t" for char in text)
    return control_count <= max(1, len(text) // 100)


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED_VALUE
            if is_sensitive_field(str(key))
            else _sanitize_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    return value


def _sanitize_text_body(text: str, content_type: str) -> str:
    mime = _mime_only(content_type)
    if mime == "application/json" or mime.endswith("+json"):
        try:
            return json.dumps(
                _sanitize_json_value(json.loads(text)),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (json.JSONDecodeError, TypeError):
            return text
    if mime == "application/x-www-form-urlencoded":
        return urlencode(
            [
                (name, REDACTED_VALUE if is_sensitive_field(name) else value)
                for name, value in parse_qsl(text, keep_blank_values=True)
            ],
            doseq=True,
        )
    return text


def _serialize_body(
    body: bytes,
    content_type: str,
    *,
    include_secrets: bool,
) -> dict[str, Any]:
    if _looks_textual(content_type, body):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            if not include_secrets:
                text = _sanitize_text_body(text, content_type)
            return {"text": text, "encoding": "utf-8"}
    return {
        "text": base64.b64encode(body).decode("ascii"),
        "encoding": "base64",
    }


def flows_to_csv(
    flows: list[HttpFlowCaptured], include_secrets: bool = False
) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "captured_at",
            "method",
            "status",
            "url",
            "host",
            "path",
            "content_type",
            "response_size",
            "duration_ms",
        ]
    )
    for flow in flows:
        url = flow.url if include_secrets else sanitize_url(flow.url)
        path = flow.path if include_secrets else sanitize_url(flow.path)
        writer.writerow(
            [
                flow.created_at.astimezone(UTC).isoformat(),
                flow.method,
                flow.status_code or "",
                url,
                flow.host,
                path,
                flow.content_type,
                flow.response_size,
                flow.duration_ms if flow.duration_ms is not None else "",
            ]
        )
    return output.getvalue()


def flows_to_json(
    flows: list[HttpFlowCaptured], include_secrets: bool = False
) -> str:
    payload = [_flow_dict(flow, include_secrets=include_secrets) for flow in flows]
    return json.dumps(payload, indent=2, ensure_ascii=False)


def flows_to_har(
    flows: list[HttpFlowCaptured], include_secrets: bool = False
) -> str:
    payload = {
        "log": {
            "version": "1.2",
            "creator": {"name": "StreamInspector", "version": "0.1"},
            "entries": [_har_entry(flow, include_secrets) for flow in flows],
        }
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def format_request(flow: HttpFlowCaptured) -> str:
    headers = "\n".join(f"{name}: {value}" for name, value in flow.request_headers)
    content_type = _header_value(flow.request_headers, "content-type")
    body = _serialize_body(flow.request_body, content_type, include_secrets=True)
    body_text = body["text"]
    if body["encoding"] == "base64":
        body_text = f"[base64]\n{body_text}"
    return f"{flow.method} {flow.url} {flow.http_version}\n{headers}\n\n{body_text}".rstrip()


def _flow_dict(
    flow: HttpFlowCaptured, *, include_secrets: bool = False
) -> dict[str, Any]:
    request_headers = (
        flow.request_headers if include_secrets else _redact_headers(flow.request_headers)
    )
    response_headers = (
        flow.response_headers if include_secrets else _redact_headers(flow.response_headers)
    )
    request_content_type = _header_value(flow.request_headers, "content-type")
    request_body = _serialize_body(
        flow.request_body,
        request_content_type,
        include_secrets=include_secrets,
    )
    response_body = _serialize_body(
        flow.response_body,
        flow.content_type,
        include_secrets=include_secrets,
    )
    return {
        "captured_at": flow.created_at.astimezone(UTC).isoformat(),
        "flow_id": flow.flow_id,
        "request": {
            "method": flow.method,
            "url": flow.url if include_secrets else sanitize_url(flow.url),
            "http_version": flow.http_version,
            "headers": dict(request_headers),
            "body": request_body["text"],
            "body_encoding": request_body["encoding"],
        },
        "response": {
            "status": flow.status_code,
            "reason": flow.reason,
            "headers": dict(response_headers),
            "body": response_body["text"],
            "body_encoding": response_body["encoding"],
            "content_type": flow.content_type,
            "size": flow.response_size,
        },
        "duration_ms": flow.duration_ms,
    }


def _har_entry(flow: HttpFlowCaptured, include_secrets: bool = False) -> dict[str, Any]:
    request_headers = (
        flow.request_headers if include_secrets else _redact_headers(flow.request_headers)
    )
    response_headers = (
        flow.response_headers if include_secrets else _redact_headers(flow.response_headers)
    )
    request_content_type = _header_value(flow.request_headers, "content-type")
    request_body = _serialize_body(
        flow.request_body,
        request_content_type,
        include_secrets=include_secrets,
    )
    response_body = _serialize_body(
        flow.response_body,
        flow.content_type,
        include_secrets=include_secrets,
    )
    post_data: dict[str, Any] | None = None
    if flow.request_body:
        post_data = {
            "mimeType": request_content_type,
            "text": request_body["text"],
        }
        if request_body["encoding"] == "base64":
            post_data["encoding"] = "base64"

    content: dict[str, Any] = {
        "size": flow.response_size,
        "mimeType": flow.content_type,
        "text": response_body["text"],
    }
    if response_body["encoding"] == "base64":
        content["encoding"] = "base64"

    return {
        "startedDateTime": flow.created_at.astimezone(UTC).isoformat(),
        "time": flow.duration_ms or 0,
        "request": {
            "method": flow.method,
            "url": flow.url if include_secrets else sanitize_url(flow.url),
            "httpVersion": flow.http_version,
            "headers": [
                {"name": name, "value": value} for name, value in request_headers
            ],
            "queryString": [],
            "cookies": [],
            "headersSize": -1,
            "bodySize": len(flow.request_body),
            "postData": post_data,
        },
        "response": {
            "status": flow.status_code or 0,
            "statusText": flow.reason,
            "httpVersion": flow.http_version,
            "headers": [
                {"name": name, "value": value} for name, value in response_headers
            ],
            "cookies": [],
            "content": content,
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": flow.response_size,
        },
        "cache": {},
        "timings": {"send": 0, "wait": flow.duration_ms or 0, "receive": 0},
    }
