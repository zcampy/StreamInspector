from streaminspector.core.events import HttpFlowCaptured
from streaminspector.gui.performance_dialog import performance_summary


def _flow(**kwargs) -> HttpFlowCaptured:
    defaults: dict[str, object] = {
        "flow_id": "f1",
        "method": "GET",
        "scheme": "https",
        "host": "example.com",
        "port": 443,
        "path": "/",
        "url": "https://example.com/",
        "http_version": "HTTP/2",
        "status_code": 200,
        "reason": "OK",
        "content_type": "application/json",
        "request_headers": (),
        "response_headers": (),
        "request_body": b"",
        "response_body": b"",
        "response_size": 0,
        "duration_ms": 0.0,
    }
    defaults.update(kwargs)
    return HttpFlowCaptured(**defaults)  # type: ignore[arg-type]


def test_performance_summary_counts_requests_errors_and_bytes() -> None:
    flows = [
        _flow(flow_id="1", request_size=5, response_size=100, duration_ms=10.0),
        _flow(
            flow_id="2",
            method="POST",
            request_size=7,
            response_size=200,
            status_code=500,
            duration_ms=30.0,
        ),
        _flow(flow_id="3", request_size=0, response_size=50, duration_ms=20.0),
    ]

    summary = performance_summary(flows)

    assert summary["requests"] == 3
    assert summary["errors"] == 1
    assert summary["error_rate"] == pytest_approx(1 / 3 * 100)
    assert summary["total_bytes"] == 5 + 100 + 7 + 200 + 0 + 50
    assert summary["average_ms"] == pytest_approx(20.0)
    assert summary["median_ms"] == pytest_approx(20.0)
    assert summary["maximum_ms"] == pytest_approx(30.0)


def test_performance_summary_handles_empty_list() -> None:
    summary = performance_summary([])

    assert summary["requests"] == 0
    assert summary["errors"] == 0
    assert summary["error_rate"] == 0.0
    assert summary["total_bytes"] == 0
    assert summary["average_ms"] == 0.0
    assert summary["median_ms"] == 0.0
    assert summary["maximum_ms"] == 0.0


def test_performance_summary_uses_request_size_field() -> None:
    """El diálogo usa el campo real `request_size`; debe ser el valor pasado, no derivado."""
    flows = [_flow(flow_id="only", request_size=4096, response_size=10)]

    summary = performance_summary(flows)

    assert summary["total_bytes"] == 4096 + 10


def test_performance_summary_ignores_request_body_for_total() -> None:
    """Aunque `request_body` esté presente, el total se calcula con `request_size`.

    Esto evita ambigüedad: si el addon o el importador HAR no rellenan
    `request_size`, el total no se infla con el body por error.
    """
    flows = [
        _flow(
            flow_id="only",
            request_size=10,
            request_body=b"x" * 4096,
            response_size=5,
        )
    ]

    summary = performance_summary(flows)

    assert summary["total_bytes"] == 10 + 5


def pytest_approx(value: float) -> object:
    import pytest

    return pytest.approx(value)
