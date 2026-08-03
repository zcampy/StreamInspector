from __future__ import annotations

import tempfile
from pathlib import Path

from streaminspector.core.events import EventBus, HttpFlowCaptured
from streaminspector.storage import FlowAnnotationData, StorageService


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="streaminspector-poc-") as directory:
        database = Path(directory) / "poc.sqlite3"
        flow = HttpFlowCaptured(
            flow_id="poc-login-001",
            method="POST",
            scheme="https",
            host="api.example.test",
            port=443,
            path="/login",
            url="https://api.example.test/login",
            http_version="HTTP/2",
            status_code=401,
            reason="Unauthorized",
            content_type="application/json",
            response_body=b'{"error":"invalid credentials"}',
            response_size=31,
            duration_ms=125.5,
        )

        bus = EventBus()
        storage = StorageService(bus, database)
        session_id = storage.active_session_id
        bus.publish(flow)
        storage.save_annotation(
            flow.flow_id,
            favorite=True,
            tags="login, error, poc",
            note="Validar respuesta 401 y tratamiento del token.",
        )
        storage.close()

        reopened = StorageService(EventBus(), database)
        try:
            restored = reopened.session_events(session_id)
            annotation = reopened.get_annotation(flow.flow_id)
            expected = FlowAnnotationData(
                favorite=True,
                tags="login, error, poc",
                note="Validar respuesta 401 y tratamiento del token.",
            )
            if len(restored) != 1 or restored[0].flow_id != flow.flow_id:
                raise RuntimeError("La captura no se recuperó correctamente")
            if annotation != expected:
                raise RuntimeError("La anotación no se recuperó correctamente")
        finally:
            reopened.close()

    print("POC OK: captura, sesión, favorito, etiquetas y nota persistieron tras reiniciar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
