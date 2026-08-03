from __future__ import annotations

from mitmproxy import http

from streaminspector.core.events import EventBus, HttpFlowCaptured


class CaptureAddon:
    """Convert mitmproxy flows into immutable application events."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def response(self, flow: http.HTTPFlow) -> None:
        request = flow.request
        response = flow.response
        if response is None:
            return

        duration_ms: float | None = None
        if request.timestamp_start and response.timestamp_end:
            duration_ms = max(0.0, (response.timestamp_end - request.timestamp_start) * 1000)

        self._event_bus.publish(
            HttpFlowCaptured(
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
                response_size=len(response.raw_content or b""),
                duration_ms=duration_ms,
            )
        )
