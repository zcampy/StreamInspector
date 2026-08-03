from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from streaminspector.core.events import HttpFlowCaptured


def flows_from_har(text: str) -> list[HttpFlowCaptured]:
    document = json.loads(text)
    entries = document.get("log", {}).get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("El archivo HAR no contiene una lista de entradas válida")
    return [_entry_to_flow(entry) for entry in entries if isinstance(entry, dict)]


def _entry_to_flow(entry: dict) -> HttpFlowCaptured:
    request = entry.get("request") or {}
    response = entry.get("response") or {}
    url = str(request.get("url") or "")
    parsed = urlsplit(url)
    scheme = parsed.scheme or "http"
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    started = _parse_datetime(entry.get("startedDateTime"))
    request_body = _content_bytes((request.get("postData") or {}).get("text"), None)
    content = response.get("content") or {}
    response_body = _content_bytes(content.get("text"), content.get("encoding"))
    response_size = _as_int(content.get("size"), len(response_body))

    return HttpFlowCaptured(
        created_at=started,
        flow_id=f"har-{uuid4().hex}",
        method=str(request.get("method") or "GET"),
        scheme=scheme,
        host=parsed.hostname or "",
        port=port,
        path=path,
        url=url,
        http_version=str(response.get("httpVersion") or request.get("httpVersion") or "HTTP/1.1"),
        status_code=_as_int(response.get("status"), 0) or None,
        reason=str(response.get("statusText") or ""),
        content_type=str(content.get("mimeType") or ""),
        request_headers=_headers(request.get("headers")),
        response_headers=_headers(response.get("headers")),
        request_body=request_body,
        response_body=response_body,
        response_size=response_size,
        duration_ms=float(entry.get("time") or 0.0),
    )


def _headers(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        return ()
    result: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            result.append((str(item.get("name") or ""), str(item.get("value") or "")))
    return tuple(result)


def _content_bytes(text: object, encoding: object) -> bytes:
    if text is None:
        return b""
    value = str(text)
    if str(encoding or "").lower() == "base64":
        try:
            return base64.b64decode(value)
        except ValueError as exc:
            raise ValueError("El HAR contiene un cuerpo base64 no válido") from exc
    return value.encode("utf-8", errors="replace")


def _parse_datetime(value: object) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
