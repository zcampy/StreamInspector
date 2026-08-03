from __future__ import annotations

from mitmproxy import http

from streaminspector.core.events import EventBus, HttpFlowCaptured


class CaptureAddon:
    """Convert mitmproxy flows into small immutable application events."""

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
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                response_size=len(response.raw_content or b""),
                duration_ms=duration_ms,
            )
        )
