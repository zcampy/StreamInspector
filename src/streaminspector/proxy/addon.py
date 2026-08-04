from __future__ import annotations

from mitmproxy import http

from streaminspector.capture_policy import CapturePolicy
from streaminspector.core.events import EventBus, HttpFlowCaptured


class CaptureAddon:
    """Convert mitmproxy flows into immutable application events.

    Filtra los flows según `policy.accepts(...)` ANTES de emitir el evento
    al bus. Esto garantiza que cuando el modo es WHITELIST o el dominio
    está excluido, los datos sensibles ni siquiera llegan al bus ni a la
    base de datos: el proxy los procesa y los reenvía transparente al
    destino real, pero StreamInspector no los guarda.
    """

    def __init__(self, event_bus: EventBus, policy: CapturePolicy) -> None:
        self._event_bus = event_bus
        self._policy = policy

    def response(self, flow: http.HTTPFlow) -> None:
        request = flow.request
        response = flow.response
        if response is None:
            return

        duration_ms: float | None = None
        if request.timestamp_start and response.timestamp_end:
            duration_ms = max(0.0, (response.timestamp_end - request.timestamp_start) * 1000)

        event = HttpFlowCaptured(
            flow_id=flow.id,
            method=request.method,
            scheme=request.scheme,
            host=request.host,
            port=request.port,
            path=request.path,
            url=request.pretty_url,
            http_version=request.http_version,
            status_code=response.status_code,
            reason=response.reason,
            content_type=response.headers.get("content-type", ""),
            request_headers=tuple(request.headers.items(multi=True)),
            response_headers=tuple(response.headers.items(multi=True)),
            request_body=request.raw_content or b"",
            response_body=response.raw_content or b"",
            request_size=len(request.raw_content or b""),
            response_size=len(response.raw_content or b""),
            duration_ms=duration_ms,
        )
        # El filtro corre aquí (no en storage) para que los datos de
        # dominios no deseados no lleguen al EventBus ni a SQLite.
        if not self._policy.accepts(event):
            return
        self._event_bus.publish(event)
