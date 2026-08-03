from __future__ import annotations

from streaminspector.core.events import HttpFlowCaptured

SEARCH_SCOPES = {
    "Todo": "all",
    "URL y ruta": "url",
    "Cabeceras": "headers",
    "Cuerpos": "bodies",
}


def flow_search_text(flow: HttpFlowCaptured, scope: str = "all") -> str:
    url_text = f"{flow.method}\n{flow.url}\n{flow.host}\n{flow.path}\n{flow.status_code or ''}"
    header_text = "\n".join(
        f"{name}: {value}"
        for name, value in (*flow.request_headers, *flow.response_headers)
    )
    body_text = "\n".join(
        (
            flow.request_body.decode("utf-8", errors="replace"),
            flow.response_body.decode("utf-8", errors="replace"),
        )
    )
    if scope == "url":
        return url_text
    if scope == "headers":
        return header_text
    if scope == "bodies":
        return body_text
    return "\n".join((url_text, header_text, body_text))


def matches_flow(
    flow: HttpFlowCaptured,
    query: str,
    *,
    scope: str = "all",
    case_sensitive: bool = False,
) -> bool:
    clean_query = query.strip()
    if not clean_query:
        return True
    haystack = flow_search_text(flow, scope)
    if not case_sensitive:
        haystack = haystack.casefold()
        clean_query = clean_query.casefold()
    return clean_query in haystack
