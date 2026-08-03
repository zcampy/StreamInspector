from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
