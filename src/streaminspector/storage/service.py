from __future__ import annotations

import json
import logging
from datetime import UTC
from pathlib import Path

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from streaminspector.core.events import (
    EventBus,
    HttpFlowCaptured,
    StatusMessage,
    StoredHistoryDeleted,
    StoredHistoryDeleteRequested,
)
from streaminspector.storage.models import Base, CapturedFlow

LOGGER = logging.getLogger(__name__)


class StorageService:
    """Persist captured flows in SQLite and expose recent history."""

    def __init__(self, event_bus: EventBus, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._event_bus = event_bus
        self._engine = create_engine(f"sqlite:///{database_path}", future=True)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        Base.metadata.create_all(self._engine)
        self._unsubscribe_flow = event_bus.subscribe(HttpFlowCaptured, self._store_flow)
        self._unsubscribe_delete = event_bus.subscribe(
            StoredHistoryDeleteRequested,
            self._delete_stored_history,
        )

    def close(self) -> None:
        self._unsubscribe_flow()
        self._unsubscribe_delete()
        self._engine.dispose()

    def recent(self, limit: int = 500) -> list[CapturedFlow]:
        with Session(self._engine) as session:
            statement = select(CapturedFlow).order_by(CapturedFlow.id.desc()).limit(limit)
            return list(reversed(session.scalars(statement).all()))

    def recent_events(self, limit: int = 500) -> list[HttpFlowCaptured]:
        return [self._to_event(flow) for flow in self.recent(limit)]

    def _store_flow(self, event: HttpFlowCaptured) -> None:
        try:
            with self._session_factory() as session:
                session.add(
                    CapturedFlow(
                        flow_id=event.flow_id,
                        captured_at=event.created_at,
                        method=event.method,
                        scheme=event.scheme,
                        host=event.host,
                        port=event.port,
                        path=event.path,
                        url=event.url,
                        http_version=event.http_version,
                        status_code=event.status_code,
                        reason=event.reason,
                        content_type=event.content_type,
                        request_headers_json=json.dumps(event.request_headers),
                        response_headers_json=json.dumps(event.response_headers),
                        request_body=event.request_body,
                        response_body=event.response_body,
                        response_size=event.response_size,
                        duration_ms=event.duration_ms,
                    )
                )
                session.commit()
        except Exception as exc:
            LOGGER.exception("Could not persist captured flow")
            self._event_bus.publish(
                StatusMessage(message=f"No se pudo guardar la captura: {exc}", level="error")
            )

    def _delete_stored_history(self, _event: StoredHistoryDeleteRequested) -> None:
        try:
            with self._session_factory() as session:
                result = session.execute(delete(CapturedFlow))
                session.commit()
                deleted_count = result.rowcount or 0
            self._event_bus.publish(StoredHistoryDeleted(deleted_count=deleted_count))
        except Exception as exc:
            LOGGER.exception("Could not delete stored history")
            self._event_bus.publish(
                StatusMessage(
                    message=f"No se pudo borrar el historial guardado: {exc}",
                    level="error",
                )
            )

    @staticmethod
    def _to_event(flow: CapturedFlow) -> HttpFlowCaptured:
        captured_at = flow.captured_at
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        else:
            captured_at = captured_at.astimezone(UTC)

        return HttpFlowCaptured(
            created_at=captured_at,
            flow_id=flow.flow_id,
            method=flow.method,
            scheme=flow.scheme,
            host=flow.host,
            port=flow.port,
            path=flow.path,
            url=flow.url,
            http_version=flow.http_version,
            status_code=flow.status_code,
            reason=flow.reason,
            content_type=flow.content_type,
            request_headers=tuple(tuple(item) for item in json.loads(flow.request_headers_json)),
            response_headers=tuple(tuple(item) for item in json.loads(flow.response_headers_json)),
            request_body=flow.request_body or b"",
            response_body=flow.response_body or b"",
            response_size=flow.response_size,
            duration_ms=flow.duration_ms,
        )
