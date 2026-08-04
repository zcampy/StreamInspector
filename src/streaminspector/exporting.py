from __future__ import annotations

import csv
import io
import json
from datetime import UTC
from typing import Any

from streaminspector.core.events import HttpFlowCaptured

# Headers cuyo valor, de filtrarse, podría filtrar credenciales. La búsqueda
# es case-insensitive y por nombre exacto (no por subcadena) para no
# romper headers legítimos que contengan la palabra en medio.
# Añadir aquí cualquier header que el equipo considere sensible.
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

# Texto que sustituye al valor del header sensible en los exports. La idea
# es que sea reconocible como "esto estaba aquí pero lo quitamos" sin
# perder el nombre del header (útil para debug).
REDACTED_VALUE = "***REDACTED***"


def is_sensitive_header(name: str) -> bool:
    """True si el nombre del header (case-insensitive) está en la lista de sensibles."""
    return name.lower() in SENSITIVE_HEADERS


def count_sensitive_headers(flows: list[HttpFlowCaptured]) -> int:
    """Cuenta cuántos headers sensibles hay en el set de flows a exportar.

    Sirve para que la UI pueda avisar al usuario ("Vas a exportar N tokens
    en headers") antes de escribir el archivo.
    """
    count = 0
    for flow in flows:
        for name, _value in flow.request_headers:
            if is_sensitive_header(name):
                count += 1
        for name, _value in flow.response_headers:
            if is_sensitive_header(name):
                count += 1
    return count


def _redact_headers(
    headers: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Devuelve los headers con los valores sensibles reemplazados por ***."""
    return tuple(
        (name, REDACTED_VALUE if is_sensitive_header(name) else value)
        for name, value in headers
    )


def _sanitized_flow(flow: HttpFlowCaptured) -> HttpFlowCaptured:
    """Devuelve un flow con los headers sensibles reemplazados por ***.

    El dataclass es frozen, así que construimos uno nuevo con los
    headers saneados. El body NO se modifica: un body que contenga un
    token en JSON o texto plano es un caso más raro y rompería la
    utilidad de los exports. Si el usuario quiere sanitizar bodies,
    debe editar el archivo a posteriori.
    """
    return HttpFlowCaptured(
        flow_id=flow.flow_id,
        method=flow.method,
        scheme=flow.scheme,
        host=flow.host,
        port=flow.port,
        path=flow.path,
        url=flow.url,
        http_version=flow.http_version,
        status_code=flow.status_code,
        reason=flow.reason,
        content_type=flow.content_type,
        request_headers=_redact_headers(flow.request_headers),
        response_headers=_redact_headers(flow.response_headers),
        request_body=flow.request_body,
        response_body=flow.response_body,
        request_size=flow.request_size,
        response_size=flow.response_size,
        duration_ms=flow.duration_ms,
    )


def flows_to_csv(
    flows: list[HttpFlowCaptured], include_secrets: bool = True
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
    # El CSV no incluye headers, así que `include_secrets` es un no-op aquí.
    # Lo dejamos en la firma por simetría con las otras funciones de export.
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


def flows_to_json(
    flows: list[HttpFlowCaptured], include_secrets: bool = True
) -> str:
    """Serializa los flows a JSON.

    `include_secrets=False` reemplaza los valores de los headers sensibles
    (Authorization, Cookie, etc.) por '***REDACTED***' antes de serializar.
    """
    payload = [_flow_dict(flow) for flow in flows]
    if not include_secrets:
        for entry in payload:
            for header_name in list(entry["request"]["headers"].keys()):
                if is_sensitive_header(header_name):
                    entry["request"]["headers"][header_name] = REDACTED_VALUE
            for header_name in list(entry["response"]["headers"].keys()):
                if is_sensitive_header(header_name):
                    entry["response"]["headers"][header_name] = REDACTED_VALUE
    return json.dumps(payload, indent=2, ensure_ascii=False)


def flows_to_har(
    flows: list[HttpFlowCaptured], include_secrets: bool = True
) -> str:
    """Serializa los flows a HAR.

    `include_secrets=False` reemplaza los valores de los headers sensibles
    por '***REDACTED***'. Sin esto, un export de una sesión real puede
    contener tus tokens OAuth, cookies de sesión, etc. — un HAR filtrado
    a un repo público es un incidente de seguridad (push protection de
    GitHub bloquea estos pushes por defecto).
    """
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


def _har_entry(flow: HttpFlowCaptured, include_secrets: bool = True) -> dict[str, Any]:
    request_body = flow.request_body.decode("utf-8", errors="replace")
    response_body = flow.response_body.decode("utf-8", errors="replace")
    if include_secrets:
        request_headers = flow.request_headers
        response_headers = flow.response_headers
    else:
        request_headers = _redact_headers(flow.request_headers)
        response_headers = _redact_headers(flow.response_headers)
    return {
        "startedDateTime": flow.created_at.astimezone(UTC).isoformat(),
        "time": flow.duration_ms or 0,
        "request": {
            "method": flow.method,
            "url": flow.url,
            "httpVersion": flow.http_version,
            "headers": [
                {"name": name, "value": value} for name, value in request_headers
            ],
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
                {"name": name, "value": value} for name, value in response_headers
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
