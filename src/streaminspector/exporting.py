from __future__ import annotations

import csv
import io
import json
from datetime import UTC
from typing import Any

from streaminspector.core.events import HttpFlowCaptured


def flows_to_csv(flows: list[HttpFlowCaptured]) -> str:
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
        writer.writerow(
            [
                flow.created_at.astimezone(UTC).isoformat(),
                flow.method,
                flow.status_code or "",
                flow.url,
                flow.host,
                flow.path,
                flow.content_type,
                flow.response_size,
                flow.duration_ms if flow.duration_ms is not None else "",
            ]
        )
    return output.getvalue()


def flows_to_json(flows: list[HttpFlowCaptured]) -> str:
    return json.dumps([_flow_dict(flow) for flow in flows], indent=2, ensure_ascii=False)


def flows_to_har(flows: list[HttpFlowCaptured]) -> str:
    payload = {
        "log": {
            "version": "1.2",
            "creator": {"name": "StreamInspector", "version": "0.1"},
            "entries": [_har_entry(flow) for flow in flows],
        }
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def format_request(flow: HttpFlowCaptured) -> str:
    headers = "\n".join(f"{name}: {value}" for name, value in flow.request_headers)
    body = flow.request_body.decode("utf-8", errors="replace")
    return f"{flow.method} {flow.url} {flow.http_version}\n{headers}\n\n{body}".rstrip()


def _flow_dict(flow: HttpFlowCaptured) -> dict[str, Any]:
    return {
        "captured_at": flow.created_at.astimezone(UTC).isoformat(),
        "flow_id": flow.flow_id,
        "request": {
            "method": flow.method,
            "url": flow.url,
            "http_version": flow.http_version,
            "headers": dict(flow.request_headers),
            "body": flow.request_body.decode("utf-8", errors="replace"),
        },
        "response": {
            "status": flow.status_code,
            "reason": flow.reason,
            "headers": dict(flow.response_headers),
            "body": flow.response_body.decode("utf-8", errors="replace"),
            "content_type": flow.content_type,
            "size": flow.response_size,
        },
        "duration_ms": flow.duration_ms,
    }


def _har_entry(flow: HttpFlowCaptured) -> dict[str, Any]:
    request_body = flow.request_body.decode("utf-8", errors="replace")
    response_body = flow.response_body.decode("utf-8", errors="replace")
    return {
        "startedDateTime": flow.created_at.astimezone(UTC).isoformat(),
        "time": flow.duration_ms or 0,
        "request": {
            "method": flow.method,
            "url": flow.url,
            "httpVersion": flow.http_version,
            "headers": [{"name": name, "value": value} for name, value in flow.request_headers],
            "queryString": [],
            "cookies": [],
            "headersSize": -1,
            "bodySize": len(flow.request_body),
            "postData": {"mimeType": "", "text": request_body} if request_body else None,
        },
        "response": {
            "status": flow.status_code or 0,
            "statusText": flow.reason,
            "httpVersion": flow.http_version,
            "headers": [
                {"name": name, "value": value} for name, value in flow.response_headers
            ],
            "cookies": [],
            "content": {
                "size": flow.response_size,
                "mimeType": flow.content_type,
                "text": response_body,
            },
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": flow.response_size,
        },
        "cache": {},
        "timings": {"send": 0, "wait": flow.duration_ms or 0, "receive": 0},
    }
