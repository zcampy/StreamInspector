from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from streaminspector.capture_policy import CapturePolicy
from streaminspector.core.events import (
    EventBus,
    HttpFlowCaptured,
    StatusMessage,
    StoredHistoryDeleted,
    StoredHistoryDeleteRequested,
)
from streaminspector.storage.models import (
    Base,
    CapturedFlow,
    CaptureSession,
    FlowAnnotation,
    FlowSessionLink,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionSummary:
    id: int
    name: str
    started_at: datetime
    ended_at: datetime | None
    flow_count: int


@dataclass(frozen=True, slots=True)
class FlowAnnotationData:
    favorite: bool = False
    tags: str = ""
    note: str = ""


class StorageService:
    """Persist captured flows and group new traffic into capture sessions."""

    def __init__(self, event_bus: EventBus, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._event_bus = event_bus
        self._engine = create_engine(f"sqlite:///{database_path}", future=True)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._capture_filter: Callable[[HttpFlowCaptured], bool] = lambda _flow: True
        Base.metadata.create_all(self._engine)
        self._ensure_schema()
        self._active_session_id = self.create_session()
        self._unsubscribe_flow = event_bus.subscribe(HttpFlowCaptured, self._store_flow)
        self._unsubscribe_delete = event_bus.subscribe(
            StoredHistoryDeleteRequested,
            self._delete_stored_history,
        )

    def _ensure_schema(self) -> None:
        """Aplica migraciones ligeras para columnas añadidas tras la creación inicial.

        `Base.metadata.create_all` solo crea tablas si no existen; no añade columnas
        a tablas ya existentes. Esto añade de forma idempotente las columnas que se
        hayan incorporado en versiones posteriores (p.ej. `request_size`).
        """
        with self._engine.begin() as conn:
            existing = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(captured_flows)")).all()
            }
            if "request_size" not in existing:
                conn.execute(
                    text(
                        "ALTER TABLE captured_flows "
                        "ADD COLUMN request_size INTEGER NOT NULL DEFAULT 0"
                    )
                )

    @property
    def active_session_id(self) -> int:
        return self._active_session_id

    def set_capture_filter(
        self,
        predicate: Callable[[HttpFlowCaptured], bool],
        policy: CapturePolicy | None = None,
    ) -> None:
        self._capture_filter = predicate
        # Si nos pasan el policy, lo guardamos para que la UI lo reuse
        # en lugar de crear uno nuevo. Esto evita que el storage y la UI
        # tengan policies distintas y se desincronicen.
        if policy is not None:
            self._capture_policy_ref = policy

    @property
    def capture_policy(self) -> CapturePolicy | None:
        """Devuelve la policy registrada con `set_capture_filter`, si hay.

        La usa la UI (`SelectiveCaptureWindow`) para reusar la misma
        instancia que el storage y el proxy, en lugar de crear una nueva.
        """
        return getattr(self, "_capture_policy_ref", None)

    def close(self) -> None:
        self.end_session(self._active_session_id)
        self._unsubscribe_flow()
        self._unsubscribe_delete()
        self._engine.dispose()

    def create_session(self, name: str | None = None) -> int:
        started_at = datetime.now(UTC)
        session_name = name or f"Sesión {started_at.astimezone().strftime('%d/%m/%Y %H:%M')}"
        with self._session_factory() as session:
            model = CaptureSession(name=session_name, started_at=started_at)
            session.add(model)
            session.commit()
            return model.id

    def rename_session(self, session_id: int, name: str) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("El nombre de la sesión no puede estar vacío")
        with self._session_factory() as session:
            result = session.execute(
                update(CaptureSession)
                .where(CaptureSession.id == session_id)
                .values(name=clean_name)
            )
            if result.rowcount == 0:
                raise ValueError("La sesión no existe")
            session.commit()

    def delete_session(self, session_id: int) -> int:
        if session_id == self._active_session_id:
            raise ValueError("La sesión activa no se puede eliminar")
        with self._session_factory() as session:
            flow_pks = list(
                session.scalars(
                    select(FlowSessionLink.flow_pk).where(
                        FlowSessionLink.session_id == session_id
                    )
                )
            )
            flow_ids = list(
                session.scalars(select(CapturedFlow.flow_id).where(CapturedFlow.id.in_(flow_pks)))
            )
            session.execute(
                delete(FlowSessionLink).where(FlowSessionLink.session_id == session_id)
            )
            if flow_pks:
                session.execute(delete(CapturedFlow).where(CapturedFlow.id.in_(flow_pks)))
            if flow_ids:
                session.execute(delete(FlowAnnotation).where(FlowAnnotation.flow_id.in_(flow_ids)))
            result = session.execute(
                delete(CaptureSession).where(CaptureSession.id == session_id)
            )
            if result.rowcount == 0:
                raise ValueError("La sesión no existe")
            session.commit()
            return len(flow_pks)

    def end_session(self, session_id: int) -> None:
        with self._session_factory() as session:
            session.execute(
                update(CaptureSession)
                .where(CaptureSession.id == session_id, CaptureSession.ended_at.is_(None))
                .values(ended_at=datetime.now(UTC))
            )
            session.commit()

    def list_sessions(self, limit: int = 100) -> list[SessionSummary]:
        with self._session_factory() as session:
            statement = (
                select(
                    CaptureSession.id,
                    CaptureSession.name,
                    CaptureSession.started_at,
                    CaptureSession.ended_at,
                    func.count(FlowSessionLink.flow_pk),
                )
                .outerjoin(FlowSessionLink, FlowSessionLink.session_id == CaptureSession.id)
                .group_by(CaptureSession.id)
                .order_by(CaptureSession.started_at.desc())
                .limit(limit)
            )
            return [
                SessionSummary(
                    id=row.id,
                    name=row.name,
                    started_at=_as_utc(row.started_at),
                    ended_at=_as_utc(row.ended_at) if row.ended_at else None,
                    flow_count=row[4],
                )
                for row in session.execute(statement)
            ]

    def recent(self, limit: int = 500) -> list[CapturedFlow]:
        with Session(self._engine) as session:
            statement = select(CapturedFlow).order_by(CapturedFlow.id.desc()).limit(limit)
            return list(reversed(session.scalars(statement).all()))

    def recent_events(self, limit: int = 500) -> list[HttpFlowCaptured]:
        return [self._to_event(flow) for flow in self.recent(limit)]

    def session_events(self, session_id: int, limit: int = 500) -> list[HttpFlowCaptured]:
        with self._session_factory() as session:
            statement = (
                select(CapturedFlow)
                .join(FlowSessionLink, FlowSessionLink.flow_pk == CapturedFlow.id)
                .where(FlowSessionLink.session_id == session_id)
                .order_by(CapturedFlow.id.desc())
                .limit(limit)
            )
            flows = list(reversed(session.scalars(statement).all()))
        return [self._to_event(flow) for flow in flows]

    def get_annotation(self, flow_id: str) -> FlowAnnotationData:
        with self._session_factory() as session:
            model = session.get(FlowAnnotation, flow_id)
            if model is None:
                return FlowAnnotationData()
            return FlowAnnotationData(
                favorite=model.favorite,
                tags=model.tags,
                note=model.note,
            )

    def save_annotation(
        self,
        flow_id: str,
        *,
        favorite: bool,
        tags: str,
        note: str,
    ) -> None:
        clean_tags = ", ".join(
            dict.fromkeys(tag.strip() for tag in tags.split(",") if tag.strip())
        )
        with self._session_factory() as session:
            model = session.get(FlowAnnotation, flow_id)
            if model is None:
                model = FlowAnnotation(flow_id=flow_id)
                session.add(model)
            model.favorite = favorite
            model.tags = clean_tags
            model.note = note.strip()
            session.commit()

    def favorite_flow_ids(self) -> set[str]:
        with self._session_factory() as session:
            return set(
                session.scalars(
                    select(FlowAnnotation.flow_id).where(FlowAnnotation.favorite.is_(True))
                )
            )

    def _store_flow(self, event: HttpFlowCaptured) -> None:
        if not self._capture_filter(event):
            return
        try:
            with self._session_factory() as session:
                model = CapturedFlow(
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
                    request_size=event.request_size,
                    response_size=event.response_size,
                    duration_ms=event.duration_ms,
                )
                session.add(model)
                session.flush()
                session.add(
                    FlowSessionLink(flow_pk=model.id, session_id=self._active_session_id)
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
                deleted_count = session.scalar(select(func.count(CapturedFlow.id))) or 0
                session.execute(delete(FlowAnnotation))
                session.execute(delete(FlowSessionLink))
                session.execute(delete(CapturedFlow))
                session.execute(
                    delete(CaptureSession).where(CaptureSession.id != self._active_session_id)
                )
                session.commit()
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
        return HttpFlowCaptured(
            created_at=_as_utc(flow.captured_at),
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
            request_size=flow.request_size,
            response_size=flow.response_size,
            duration_ms=flow.duration_ms,
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
