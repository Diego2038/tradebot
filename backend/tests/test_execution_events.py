"""Pruebas de los eventos de dominio y el publicador in-memory (Tarea 1, spec 04).

Cubren de forma acotada el ``EventPublisher`` y el ``OrderEvent`` sin dependencias
externas (todo es Python puro, sin red ni SDK de Alpaca):

- (a) Fan-out: un mismo evento se entrega a varios suscriptores (R4.1).
- (b) Aislamiento de fallos: un suscriptor que lanza NO interrumpe ``publish`` y
  los demás suscriptores SÍ reciben el evento (R4.3).
- (c) ``unsubscribe``: un suscriptor dado de baja deja de recibir eventos.
"""
from __future__ import annotations

from decimal import Decimal

from app.services.execution.events import EventPublisher, EventType, OrderEvent


def _sample_event() -> OrderEvent:
    return OrderEvent(
        event_type=EventType.SUBMITTED,
        symbol="BTC/USD",
        side="buy",
        qty=Decimal("0.001"),
        reason="test",
    )


def test_publish_fans_out_to_multiple_subscribers() -> None:
    """(a) Un evento se entrega a todos los suscriptores registrados (R4.1)."""
    publisher = EventPublisher()
    received_a: list[OrderEvent] = []
    received_b: list[OrderEvent] = []
    received_c: list[OrderEvent] = []

    publisher.subscribe(received_a.append)
    publisher.subscribe(received_b.append)
    publisher.subscribe(received_c.append)

    event = _sample_event()
    publisher.publish(event)

    assert received_a == [event]
    assert received_b == [event]
    assert received_c == [event]


def test_failing_subscriber_does_not_interrupt_others() -> None:
    """(b) Un suscriptor que lanza no interrumpe publish; los demás reciben (R4.3)."""
    publisher = EventPublisher()
    before: list[OrderEvent] = []
    after: list[OrderEvent] = []

    def boom(_event: OrderEvent) -> None:
        raise RuntimeError("subscriber failure")

    publisher.subscribe(before.append)
    publisher.subscribe(boom)
    publisher.subscribe(after.append)

    event = _sample_event()
    # publish must return normally despite the raising subscriber.
    publisher.publish(event)

    assert before == [event]
    assert after == [event]


def test_unsubscribe_stops_delivery() -> None:
    """(c) Tras unsubscribe, el suscriptor deja de recibir eventos."""
    publisher = EventPublisher()
    received: list[OrderEvent] = []

    publisher.subscribe(received.append)
    publisher.publish(_sample_event())
    assert len(received) == 1

    publisher.unsubscribe(received.append)
    publisher.publish(_sample_event())
    # No new events delivered after unsubscribe.
    assert len(received) == 1
