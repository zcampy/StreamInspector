from streaminspector.core.events import EventBus, StatusMessage


def test_publish_invokes_subscriber() -> None:
    bus = EventBus()
    received: list[str] = []

    bus.subscribe(StatusMessage, lambda event: received.append(event.message))
    errors = bus.publish(StatusMessage(message="ok"))

    assert errors == []
    assert received == ["ok"]


def test_priority_controls_order() -> None:
    bus = EventBus()
    order: list[str] = []

    bus.subscribe(StatusMessage, lambda _event: order.append("low"), priority=0)
    bus.subscribe(StatusMessage, lambda _event: order.append("high"), priority=10)
    bus.publish(StatusMessage(message="test"))

    assert order == ["high", "low"]


def test_unsubscribe_callback() -> None:
    bus = EventBus()
    received: list[str] = []

    unsubscribe = bus.subscribe(StatusMessage, lambda event: received.append(event.message))
    unsubscribe()
    bus.publish(StatusMessage(message="ignored"))

    assert received == []
