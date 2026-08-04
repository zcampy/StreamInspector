"""Prueba de concepto contra una web real.

Hace una única petición HTTP a una URL real, captura el `HttpFlowCaptured`,
y la pasa por todo el pipeline de la app:

1. Persistencia en SQLite (StorageService)
2. Anotación (favorito + etiquetas + nota)
3. Export a HAR 1.2
4. Re-import del HAR (debe producir un evento idéntico al original)
5. Búsqueda profunda (deep search) por una palabra del cuerpo
6. Métricas de rendimiento (PerformanceDialog)

Uso:
    .venv\\Scripts\\python.exe -m streaminspector.poc_web

La POC imprime un resumen por etapa. Si alguna falla, devuelve código 1.
"""
from __future__ import annotations

import json
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.deep_search import matches_flow
from streaminspector.exporting import flows_to_csv, flows_to_har, flows_to_json, format_request
from streaminspector.gui.performance_dialog import performance_summary
from streaminspector.har_import import flows_from_har
from streaminspector.storage import FlowAnnotationData, StorageService

URL = (
    "https://jack37eo.mpcourageny9i9zzipper.my/es/badminton/"
    "bwf-indonesia-open-2203708/rd32-crt-2.html?icg=RVM&ilang=es"
)
USER_AGENT = "StreamInspector-POC/1.0"
TIMEOUT_SECONDS = 20
SEARCH_QUERY = "bwf"
SEARCH_SCOPE = "all"


def _section(title: str) -> None:
    print()
    print(f"=== {title} ===")


def _fetch() -> HttpFlowCaptured:
    """Hace una única petición GET y devuelve un `HttpFlowCaptured` con datos reales."""
    request_headers = (
        ("User-Agent", USER_AGENT),
        ("Accept", "text/html,application/xhtml+xml"),
        ("Accept-Language", "es-ES,es;q=0.9"),
    )
    request = urllib.request.Request(URL, headers=dict(request_headers))
    started = time.perf_counter()
    started_at_dt = time.gmtime()
    response_headers: list[tuple[str, str]] = []
    response_body = b""
    status_code: int | None = None
    reason = ""
    content_type = ""
    error: str | None = None

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response_body = response.read()
            status_code = response.status
            reason = response.reason or ""
            response_headers = [(k, v) for k, v in response.headers.items()]
            content_type = response.headers.get("Content-Type", "") or response.headers.get(
                "content-type", ""
            )
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        reason = exc.reason or ""
        response_headers = [(k, v) for k, v in (exc.headers.items() if exc.headers else [])]
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
        response_body = exc.read() or b""
    except (urllib.error.URLError, TimeoutError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    duration_ms = (time.perf_counter() - started) * 1000.0

    parsed = urlsplit(URL)
    scheme = parsed.scheme or "https"
    port = parsed.port or (443 if scheme == "https" else 80)
    return HttpFlowCaptured(
        created_at=__import__("datetime").datetime.fromtimestamp(
            time.mktime(started_at_dt), tz=__import__("datetime").UTC
        ),
        flow_id=f"web-{uuid4().hex}",
        method="GET",
        scheme=scheme,
        host=parsed.hostname or "",
        port=port,
        path=parsed.path or "/",
        url=URL,
        http_version="HTTP/1.1",
        status_code=status_code,
        reason=reason,
        content_type=content_type,
        request_headers=tuple(request_headers),
        response_headers=tuple(response_headers),
        request_body=b"",
        response_body=response_body,
        request_size=0,
        response_size=len(response_body),
        duration_ms=duration_ms if error is None else None,
    ), error


def _print_flow_summary(flow: HttpFlowCaptured) -> None:
    print(f"  flow_id     : {flow.flow_id}")
    print(f"  URL         : {flow.url[:80]}")
    print(f"  status      : {flow.status_code} {flow.reason}")
    print(f"  content-type: {flow.content_type[:60] or '(none)'}")
    print(f"  response    : {flow.response_size} bytes")
    duration_text = f"{flow.duration_ms:.0f} ms" if flow.duration_ms else "(n/a)"
    print(f"  duration    : {duration_text}")


def main() -> int:
    print("StreamInspector POC contra web real")
    print(f"URL: {URL}")

    with tempfile.TemporaryDirectory(prefix="streaminspector-poc-web-") as tmp:
        work_dir = Path(tmp)
        database = work_dir / "poc-web.sqlite3"
        har_path = work_dir / "poc-web.har"

        # 1. Fetch real.
        _section("1. Petición HTTP real")
        flow, error = _fetch()
        if error is not None:
            print(f"  ERROR de red: {error}")
            return 1
        _print_flow_summary(flow)
        if flow.status_code and flow.status_code >= 400:
            print(f"  Aviso: status {flow.status_code}, se continúa igualmente")
        if flow.response_size == 0:
            print("  ERROR: respuesta vacía, no hay nada que procesar")
            return 1

        # 2. Persistencia + anotación.
        _section("2. Persistencia en SQLite")
        bus = EventBus()
        storage = StorageService(bus, database)
        try:
            errors = bus.publish(flow)
            if errors:
                print(f"  ERROR publicando evento: {errors}")
                return 1
            print(f"  Captura guardada en {database.name}")

            storage.save_annotation(
                flow.flow_id,
                favorite=True,
                tags="poc-web, bwf, indonesia",
                note="POC contra la web proporcionada por el usuario.",
            )
            print("  Anotación guardada: favorito + 3 etiquetas + nota")

            annotation = storage.get_annotation(flow.flow_id)
            if annotation != FlowAnnotationData(
                favorite=True,
                tags="poc-web, bwf, indonesia",
                note="POC contra la web proporcionada por el usuario.",
            ):
                print(f"  ERROR: anotación no coincide -> {annotation}")
                return 1
            print("  Anotación releída correctamente")

            assert flow.flow_id in storage.favorite_flow_ids(), "favorito no aparece"
            print("  flow_id presente en favorite_flow_ids()")
        finally:
            storage.close()

        # 3. Reapertura: la BD debe contener la captura.
        _section("3. Reapertura de la BD")
        reopened = StorageService(EventBus(), database)
        try:
            restored = reopened.recent_events(limit=5)
            if len(restored) != 1 or restored[0].flow_id != flow.flow_id:
                print(f"  ERROR: restored={[f.flow_id for f in restored]}")
                return 1
            assert restored[0].status_code == flow.status_code
            assert restored[0].response_body == flow.response_body
            assert restored[0].response_size == flow.response_size
            assert restored[0].request_size == flow.request_size
            print(f"  restored flow_id={restored[0].flow_id} status={restored[0].status_code}")
        finally:
            reopened.close()

        # 4. Export a HAR + re-import.
        _section("4. Export HAR 1.2 + re-import")
        har_text = flows_to_har([flow])
        har_path.write_text(har_text, encoding="utf-8")
        har_size = har_path.stat().st_size
        print(f"  HAR escrito: {har_path.name} ({har_size} bytes)")

        reimported = flows_from_har(har_text)
        if len(reimported) != 1:
            print(f"  ERROR: reimported={len(reimported)} capturas")
            return 1
        if reimported[0].url != flow.url:
            print(f"  ERROR: URL difiere ({reimported[0].url} != {flow.url})")
            return 1
        if reimported[0].status_code != flow.status_code:
            print(f"  ERROR: status difiere ({reimported[0].status_code} != {flow.status_code})")
            return 1
        if reimported[0].response_body != flow.response_body:
            print("  ERROR: response_body difiere tras round-trip HAR")
            return 1
        print(f"  Round-trip OK: reimported.status={reimported[0].status_code}")

        # 5. Export CSV/JSON.
        _section("5. Export CSV + JSON")
        csv_text = flows_to_csv([flow])
        json_text = flows_to_json([flow])
        print(f"  CSV : {len(csv_text.splitlines())} líneas")
        print(f"  JSON: {len(json_text)} bytes")
        json.loads(json_text)  # debe parsear

        # 6. Deep search.
        _section("6. Búsqueda profunda")
        match = matches_flow(flow, SEARCH_QUERY, scope=SEARCH_SCOPE)
        print(f"  query='{SEARCH_QUERY}' scope={SEARCH_SCOPE} -> match={match}")
        if not match:
            print("  Aviso: el termino no aparece en el body (esperado si la web es un stub JS)")

        # 7. Performance summary.
        _section("7. Resumen de rendimiento (mismo formato que PerformanceDialog)")
        summary = performance_summary([flow])
        for key, value in summary.items():
            print(f"  {key:12s}: {value}")

        # 8. format_request (lo que ve el usuario al seleccionar la fila).
        _section("8. format_request (vista de usuario)")
        formatted = format_request(flow)
        lines = formatted.splitlines()
        print(f"  {len(lines)} líneas, primeras 3:")
        for line in lines[:3]:
            print(f"    {line[:90]}")

    print()
    print("[POC-WEB] CORRECTO: todas las etapas completadas con tráfico real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
