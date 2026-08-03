from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CaptureSession(Base):
    __tablename__ = "capture_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CapturedFlow(Base):
    __tablename__ = "captured_flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flow_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    method: Mapped[str] = mapped_column(String(16))
    scheme: Mapped[str] = mapped_column(String(16))
    host: Mapped[str] = mapped_column(String(255), index=True)
    port: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    http_version: Mapped[str] = mapped_column(String(32))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(255), default="")
    request_headers_json: Mapped[str] = mapped_column(Text, default="[]")
    response_headers_json: Mapped[str] = mapped_column(Text, default="[]")
    request_body: Mapped[bytes] = mapped_column(LargeBinary, default=b"")
    response_body: Mapped[bytes] = mapped_column(LargeBinary, default=b"")
    response_size: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class FlowSessionLink(Base):
    """Associate flows with sessions without altering existing captured_flows tables."""

    __tablename__ = "flow_session_links"

    flow_pk: Mapped[int] = mapped_column(
        ForeignKey("captured_flows.id", ondelete="CASCADE"), primary_key=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("capture_sessions.id", ondelete="CASCADE"), index=True
    )
