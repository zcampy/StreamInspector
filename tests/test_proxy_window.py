from streaminspector.core.events import ProxyStartRequested
from streaminspector.gui.proxy_window import (
    DEFAULT_PROXY_HOST,
    DEFAULT_PROXY_PORT,
    _check_bind_error,
)


def test_proxy_start_request_has_local_defaults() -> None:
    event = ProxyStartRequested()

    assert event.host == DEFAULT_PROXY_HOST
    assert event.port == DEFAULT_PROXY_PORT


def test_bind_diagnostic_accepts_ephemeral_local_port() -> None:
    assert _check_bind_error("127.0.0.1", 0) is None
