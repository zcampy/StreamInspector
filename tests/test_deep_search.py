from streaminspector.core.events import HttpFlowCaptured
from streaminspector.deep_search import flow_search_text, matches_flow


def _flow() -> HttpFlowCaptured:
    return HttpFlowCaptured(
        flow_id="flow-search",
        method="POST",
        scheme="https",
        host="api.example.com",
        port=443,
        path="/users/42",
        url="https://api.example.com/users/42",
        status_code=401,
        request_headers=(("Authorization", "Bearer secret-token"),),
        response_headers=(("Content-Type", "application/json"),),
        request_body=b'{"name":"Juan"}',
        response_body=b'{"error":"Unauthorized"}',
    )


def test_searches_url_headers_and_bodies():
    flow = _flow()

    assert matches_flow(flow, "users/42", scope="url")
    assert matches_flow(flow, "secret-token", scope="headers")
    assert matches_flow(flow, "unauthorized", scope="bodies")
    assert not matches_flow(flow, "secret-token", scope="url")


def test_case_sensitive_and_empty_query():
    flow = _flow()

    assert matches_flow(flow, "juan")
    assert not matches_flow(flow, "juan", case_sensitive=True)
    assert matches_flow(flow, "")


def test_search_text_contains_status_and_method():
    text = flow_search_text(_flow())

    assert "POST" in text
    assert "401" in text
