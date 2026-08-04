from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from streaminspector.core.events import ProxyStartRequested
from streaminspector.gui.proxy_window import (
    DEFAULT_PROXY_HOST,
    DEFAULT_PROXY_PORT,
    _check_bind_error,
    _sanitize_endpoint,
)


def test_proxy_start_request_has_local_defaults() -> None:
    event = ProxyStartRequested()

    assert event.host == DEFAULT_PROXY_HOST
    assert event.port == DEFAULT_PROXY_PORT


def test_bind_diagnostic_accepts_ephemeral_local_port() -> None:
    assert _check_bind_error("127.0.0.1", 0) is None


# --- Endpoint sanitization -------------------------------------------------
# `_sanitize_endpoint` debe tolerar valores corruptos (edición manual del
# registro, crash de un cierre anterior, etc.) y caer al default en lugar de
# reventar la UI. Se testea sin tocar QSettings ni construir la ventana para
# evitar bloqueos con el registro de Windows.


def test_sanitize_endpoint_returns_defaults_for_empty_inputs() -> None:
    assert _sanitize_endpoint("", "") == (DEFAULT_PROXY_HOST, DEFAULT_PROXY_PORT)
    assert _sanitize_endpoint("   ", "") == (DEFAULT_PROXY_HOST, DEFAULT_PROXY_PORT)
    assert _sanitize_endpoint(None, None) == (DEFAULT_PROXY_HOST, DEFAULT_PROXY_PORT)


def test_sanitize_endpoint_recovers_from_invalid_port() -> None:
    assert _sanitize_endpoint("192.168.1.10", "esto-no-es-un-puerto") == (
        "192.168.1.10",
        DEFAULT_PROXY_PORT,
    )
    assert _sanitize_endpoint("10.0.0.1", "abc") == ("10.0.0.1", DEFAULT_PROXY_PORT)


def test_sanitize_endpoint_recovers_from_out_of_range_port() -> None:
    assert _sanitize_endpoint("0.0.0.0", 99999) == ("0.0.0.0", DEFAULT_PROXY_PORT)
    assert _sanitize_endpoint("0.0.0.0", 0) == ("0.0.0.0", DEFAULT_PROXY_PORT)
    assert _sanitize_endpoint("0.0.0.0", -1) == ("0.0.0.0", DEFAULT_PROXY_PORT)


def test_sanitize_endpoint_accepts_valid_values() -> None:
    assert _sanitize_endpoint("0.0.0.0", 9090) == ("0.0.0.0", 9090)
    assert _sanitize_endpoint("127.0.0.1", 8080) == ("127.0.0.1", 8080)
    assert _sanitize_endpoint("::1", 8080) == ("::1", 8080)


def test_sanitize_endpoint_strips_whitespace() -> None:
    assert _sanitize_endpoint("  192.168.1.5  ", "9090") == ("192.168.1.5", 9090)
    assert _sanitize_endpoint("\tlocalhost\t", "8080") == ("localhost", 8080)
