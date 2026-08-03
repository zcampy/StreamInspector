from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import TypeVar

EventHandler = Callable[["Event"], None]
TEvent = TypeVar("TEvent", bound="Event")


@dataclass(frozen=True, slots=True)
class Event:
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ApplicationStarted(Event):
    version: str = ""


@dataclass(frozen=True, slots=True)
class StatusMessage(Event):
    message: str = ""
    level: str = "info"


@dataclass(frozen=True, slots=True)
class ProxyStartRequested(Event):
    pass


@dataclass(frozen=True, slots=True)
class ProxyStopRequested(Event):
    pass


@dataclass(frozen=True, slots=True)
class ProxyStateChanged(Event):
    running: bool = False
    host: str = ""
    port: int = 0


@dataclass(frozen=True, slots=True)
class ProxyError(Event):
    message: str = ""


@dataclass(frozen=True, slots=True)
class HttpFlowCaptured(Event):
    flow_id: str = ""
    method: str = ""
    scheme: str = ""
    host: str = ""
    port: int = 0
    path: str = ""
    url: str = ""
    http_version: str = ""
    status_code: int | None = None
    reason: str = ""
    content_type: str = ""
    request_headers: tuple[tuple[str, str], ...] = ()
    response_headers: tuple[tuple[str, str], ...] = ()
    request_body: bytes = b""
    response_body: bytes = b""
    response_size: int = 0
    duration_ms: float | None = None


class EventBus:
    """Small thread-safe in-process publish/subscribe bus."""

    def __init__(self) -> None:
        self._subscribers: dict[type[Event], list[tuple[int, EventHandler]]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], None],
        *,
        priority: int = 0,
    ) -> Callable[[], None]:
        with self._lock:
            handlers = self._subscribers[event_type]
            handlers.append((priority, handler))
            handlers.sort(key=lambda item: item[0], reverse=True)

        def unsubscribe() -> None:
            self.unsubscribe(event_type, handler)

        return unsubscribe

    def unsubscribe(self, event_type: type[TEvent], handler: Callable[[TEvent], None]) -> None:
        with self._lock:
            self._subscribers[event_type] = [
                item for item in self._subscribers[event_type] if item[1] is not handler
            ]

    def publish(self, event: Event) -> list[Exception]:
        with self._lock:
            handlers = list(self._subscribers.get(type(event), ()))
            handlers += list(self._subscribers.get(Event, ()))

        errors: list[Exception] = []
        for _, handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # listeners must not break the publisher
                errors.append(exc)
        return errors

    def subscriber_count(self, event_type: type[Event] | None = None) -> int:
        with self._lock:
            if event_type is not None:
                return len(self._subscribers.get(event_type, ()))
            return sum(len(items) for items in self._subscribers.values())
