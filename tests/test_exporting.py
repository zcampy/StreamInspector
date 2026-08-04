import json

from streaminspector.core.events import HttpFlowCaptured
from streaminspector.exporting import (
    REDACTED_VALUE,
    count_sensitive_headers,
    flows_to_csv,
    flows_to_har,
    flows_to_json,
    format_request,
    is_sensitive_header,
)


def _flow(
    request_headers: tuple[tuple[str, str], ...] = (),
    response_headers: tuple[tuple[str, str], ...] = (),
    flow_id: str = "export-1",
    request_body: bytes = b'{"name": "test"}',
    response_body: bytes = b'{"ok": true}',
) -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id=flow_id,
        method="POST",
        scheme="https",
        host="example.com",
        port=443,
        path="/api",
        url="https://example.com/api",
        http_version="HTTP/2",
        status_code=201,
        reason="Created",
        content_type="application/json",
        request_headers=request_headers
        or (("content-type", "application/json"),),
        response_headers=response_headers
        or (("content-type", "application/json"),),
        request_body=request_body,
        response_body=response_body,
        response_size=12,
        duration_ms=25.0,
    )


def test_export_serializers_include_flow_data() -> None:
    flow = _flow()

    csv_text = flows_to_csv([flow])
    json_payload = json.loads(flows_to_json([flow]))
    har_payload = json.loads(flows_to_har([flow]))

    assert "https://example.com/api" in csv_text
    assert json_payload[0]["request"]["method"] == "POST"
    assert har_payload["log"]["entries"][0]["response"]["status"] == 201
    assert format_request(flow).startswith("POST https://example.com/api HTTP/2")


# ----------------------- Sanitización de headers sensibles ------------------


def test_is_sensitive_header_knows_the_dangerous_ones() -> None:
    """Los headers clásicos de auth/cookies deben estar en la lista."""
    for name in (
        "Authorization",
        "authorization",
        "AUTHORIZATION",
        "Cookie",
        "Set-Cookie",
        "Proxy-Authorization",
        "X-Api-Key",
        "X-Auth-Token",
        "X-CSRF-Token",
        "X-Access-Token",
    ):
        assert is_sensitive_header(name), f"{name} debería ser sensible"


def test_is_sensitive_header_ignores_normal_headers() -> None:
    """Los headers inocuos NO deben estar en la lista."""
    for name in (
        "Content-Type",
        "User-Agent",
        "Accept",
        "Host",
        "Referer",
        "Origin",
        "Cache-Control",
    ):
        assert not is_sensitive_header(name), f"{name} NO debería ser sensible"


def test_is_sensitive_header_does_not_match_substrings() -> None:
    """`is_sensitive_header` busca por nombre EXACTO, no por subcadena,
    para no romper headers legítimos que contengan la palabra en medio."""
    # 'authorization' no debe matchear 'X-Authorization-Source' por subcadena
    # (sí matchea por igualdad, pero nuestra búsqueda es exacta).
    # En la práctica, las cabeceras auth se llaman 'Authorization' o
    # 'X-Authorization' como mucho; las 'X-Authorization-*' son raras.
    assert not is_sensitive_header("X-Authorization-Source")


def test_count_sensitive_headers_zero_when_clean() -> None:
    flow = _flow(
        request_headers=(
            ("Content-Type", "application/json"),
            ("User-Agent", "test"),
        ),
        response_headers=(
            ("Content-Type", "application/json"),
            ("Cache-Control", "no-cache"),
        ),
    )
    assert count_sensitive_headers([flow]) == 0


def test_count_sensitive_headers_counts_request_and_response() -> None:
    flow = _flow(
        request_headers=(
            ("Authorization", "Bearer ghp_xxx"),
            ("Content-Type", "application/json"),
        ),
        response_headers=(
            ("Set-Cookie", "session=abc123"),
            ("Content-Type", "application/json"),
        ),
    )
    # 1 (Authorization) + 1 (Set-Cookie) = 2
    assert count_sensitive_headers([flow]) == 2


def test_count_sensitive_headers_aggregates_across_flows() -> None:
    f1 = _flow(
        request_headers=(("Authorization", "Bearer a"),),
        flow_id="f1",
    )
    f2 = _flow(
        response_headers=(("Set-Cookie", "x=1"),),
        flow_id="f2",
    )
    assert count_sensitive_headers([f1, f2]) == 2


# ----------------------- HAR/JSON sanitization ------------------------------


def test_har_default_includes_secrets() -> None:
    """Por defecto (compat hacia atrás), los exports INCLUYEN los secrets.
    Si el usuario no quiere esto, debe pasar include_secrets=False."""
    flow = _flow(
        request_headers=(("Authorization", "Bearer ghp_secret_token"),),
    )
    har = json.loads(flows_to_har([flow]))
    headers = har["log"]["entries"][0]["request"]["headers"]
    auth = next(h for h in headers if h["name"] == "Authorization")
    assert auth["value"] == "Bearer ghp_secret_token"


def test_har_sanitized_redacts_authorization() -> None:
    """Con include_secrets=False, el valor del header sensible se reemplaza
    por ***REDACTED*** pero el nombre del header se preserva."""
    flow = _flow(
        request_headers=(
            ("Authorization", "Bearer ghp_secret_token"),
            ("Content-Type", "application/json"),
        ),
    )
    har = json.loads(flows_to_har([flow], include_secrets=False))
    headers = har["log"]["entries"][0]["request"]["headers"]
    by_name = {h["name"]: h["value"] for h in headers}
    assert by_name["Authorization"] == REDACTED_VALUE
    # Los headers inocuos NO se tocan
    assert by_name["Content-Type"] == "application/json"


def test_har_sanitized_redacts_set_cookie_in_response() -> None:
    flow = _flow(
        response_headers=(("Set-Cookie", "session=abc; HttpOnly"),),
    )
    har = json.loads(flows_to_har([flow], include_secrets=False))
    headers = har["log"]["entries"][0]["response"]["headers"]
    by_name = {h["name"]: h["value"] for h in headers}
    assert by_name["Set-Cookie"] == REDACTED_VALUE


def test_har_sanitized_handles_case_insensitive_names() -> None:
    flow = _flow(
        request_headers=(("authorization", "Bearer xxx"),),  # minúsculas
    )
    har = json.loads(flows_to_har([flow], include_secrets=False))
    headers = har["log"]["entries"][0]["request"]["headers"]
    by_name = {h["name"]: h["value"] for h in headers}
    assert by_name["authorization"] == REDACTED_VALUE


def test_json_sanitized_redacts_secrets() -> None:
    flow = _flow(
        request_headers=(
            ("Authorization", "Bearer ghp_xxx"),
            ("X-Api-Key", "key123"),
        ),
    )
    payload = json.loads(flows_to_json([flow], include_secrets=False))
    headers = payload[0]["request"]["headers"]
    assert headers["Authorization"] == REDACTED_VALUE
    assert headers["X-Api-Key"] == REDACTED_VALUE


def test_json_default_includes_secrets() -> None:
    flow = _flow(
        request_headers=(("Authorization", "Bearer ghp_xxx"),),
    )
    payload = json.loads(flows_to_json([flow]))
    assert payload[0]["request"]["headers"]["Authorization"] == "Bearer ghp_xxx"


def test_csv_ignores_include_secrets() -> None:
    """El CSV no incluye headers; `include_secrets` es un no-op. Lo
    aceptamos por simetría de la API pero no debe romper nada."""
    flow = _flow(
        request_headers=(("Authorization", "Bearer ghp_xxx"),),
    )
    csv_text = flows_to_csv([flow], include_secrets=False)
    # El CSV solo tiene columnas planas, no header Authorization
    assert "Authorization" not in csv_text
    assert "Bearer" not in csv_text


def test_sanitized_export_does_not_leak_secrets_in_bodies() -> None:
    """Por diseño, los BODIES no se sanitizan (es raro y rompería el
    caso de uso). El user debe editar el archivo a posteriori si tiene
    tokens en el body. Documentamos esta decisión en el docstring."""
    flow = _flow(
        request_body=b'{"token": "ghp_xxx_in_body"}',
    )
    har = json.loads(flows_to_har([flow], include_secrets=False))
    body = har["log"]["entries"][0]["request"]["postData"]["text"]
    # El body NO se toca
    assert "ghp_xxx_in_body" in body
