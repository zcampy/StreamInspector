from __future__ import annotations

import json
import tempfile
from pathlib import Path

from streaminspector.core.events import EventBus
from streaminspector.har_import import flows_from_har
from streaminspector.storage import FlowAnnotationData, StorageService


def _sample_har() -> str:
    return json.dumps(
        {
            "log": {
                "version": "1.2",
                "creator": {"name": "StreamInspector POC", "version": "1"},
                "entries": [
                    {
                        "startedDateTime": "2026-08-04T00:00:00Z",
                        "time": 42.5,
                        "request": {
                            "method": "POST",
                            "url": "https://api.example.test/login",
                            "httpVersion": "HTTP/1.1",
                            "headers": [
                                {"name": "Content-Type", "value": "application/json"}
                            ],
                            "postData": {
                                "mimeType": "application/json",
                                "text": "{\"user\":\"demo\"}",
                            },
                        },
                        "response": {
                            "status": 200,
                            "statusText": "OK",
                            "httpVersion": "HTTP/1.1",
                            "headers": [
                                {"name": "Content-Type", "value": "application/json"}
                            ],
                            "content": {
                                "size": 11,
                                "mimeType": "application/json",
                                "text": "{\"ok\":true}",
                            },
                        },
                    }
                ],
            }
        }
    )


def run_poc(base_dir: Path | None = None) -> Path:
    """Exercise HAR parsing, event persistence and annotations end to end."""
    work_dir = base_dir or Path(tempfile.mkdtemp(prefix="streaminspector-poc-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    database_path = work_dir / "poc.sqlite3"

    flows = flows_from_har(_sample_har())
    if len(flows) != 1:
        raise RuntimeError("La importación HAR no produjo exactamente una captura")
    flow = flows[0]

    bus = EventBus()
    storage = StorageService(bus, database_path)
    try:
        errors = bus.publish(flow)
        if errors:
            raise RuntimeError(f"La publicación generó errores: {errors}")
        storage.save_annotation(
            flow.flow_id,
            favorite=True,
            tags="poc, login, revisar, poc",
            note="Captura creada por la prueba de concepto.",
        )
    finally:
        storage.close()

    reopened = StorageService(EventBus(), database_path)
    try:
        stored = reopened.recent_events(limit=10)
        annotation = reopened.get_annotation(flow.flow_id)
        expected = FlowAnnotationData(
            favorite=True,
            tags="poc, login, revisar",
            note="Captura creada por la prueba de concepto.",
        )
        if len(stored) != 1 or stored[0].url != flow.url:
            raise RuntimeError("La captura no se recuperó correctamente desde SQLite")
        if annotation != expected:
            raise RuntimeError("La anotación no se recuperó correctamente desde SQLite")
        if flow.flow_id not in reopened.favorite_flow_ids():
            raise RuntimeError("La captura favorita no aparece en el índice de favoritos")
    finally:
        reopened.close()

    return database_path


def main() -> int:
    try:
        database_path = run_poc()
    except Exception as exc:
        print(f"[POC] ERROR: {exc}")
        return 1

    print("[POC] CORRECTO")
    print("[POC] HAR importado: 1 captura")
    print("[POC] Persistencia SQLite: correcta")
    print("[POC] Favorito, etiquetas y nota: correctos")
    print(f"[POC] Base temporal: {database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
