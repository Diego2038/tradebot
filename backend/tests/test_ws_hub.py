"""Pruebas del WebSocketHub y la serialización de eventos (Tarea 2, spec 07).

Cubren de forma acotada el hub sin necesitar un servidor WebSocket real: se usa
un ``EventPublisher`` real y fakes async de WebSocket. Casos:

- (a) ``broadcast`` entrega el evento serializado a varios clientes sanos (R3.2).
- (b) Un cliente cuyo ``send_json`` lanza es descartado; los demás SÍ reciben y
  ``broadcast`` no lanza (R3.5).
- (c) ``serialize_event`` no contiene secretos: solo las claves declaradas del
  ``OrderEvent`` y ningún api_key/secret inventado (R3.3).
- (d) ``_on_event`` encola y el consumo (vía ``broadcast``) entrega a los clientes
  (R3.2), probando el puente síncrono→async del callback del publisher.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.api.ws import WebSocketHub, serialize_event
from app.services.execution.events import EventPublisher, EventType, OrderEvent


class FakeWebSocket:
    """Fake WebSocket que acumula los payloads enviados por ``send_json``."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class FailingWebSocket:
    """Fake WebSocket cuyo ``send_json`` siempre lanza."""

    def __init__(self) -> None:
        self.calls = 0

    async def send_json(self, data: dict) -> None:
        self.calls += 1
        raise RuntimeError("client broken")


def _sample_event() -> OrderEvent:
    return OrderEvent(
        event_type=EventType.FILLED,
        symbol="BTC/USD",
        side="buy",
        qty=Decimal("0.001"),
        price=Decimal("64000.50"),
        order_id="abc-123",
        reason="filled",
    )


@pytest.mark.asyncio
async def test_broadcast_fans_out_serialized_event_to_all_clients() -> None:
    """(a) broadcast entrega el evento serializado a todos los clientes sanos (R3.2)."""
    hub = WebSocketHub(EventPublisher())
    client_a = FakeWebSocket()
    client_b = FakeWebSocket()
    client_c = FakeWebSocket()
    hub._connections.update({client_a, client_b, client_c})

    event = _sample_event()
    await hub.broadcast(event)

    expected = serialize_event(event)
    assert client_a.sent == [expected]
    assert client_b.sent == [expected]
    assert client_c.sent == [expected]


@pytest.mark.asyncio
async def test_broadcast_drops_failing_client_and_keeps_others() -> None:
    """(b) Un cliente que falla se descarta; los demás reciben; broadcast no lanza (R3.5)."""
    hub = WebSocketHub(EventPublisher())
    healthy_1 = FakeWebSocket()
    failing = FailingWebSocket()
    healthy_2 = FakeWebSocket()
    hub._connections.update({healthy_1, failing, healthy_2})

    event = _sample_event()
    # No debe lanzar aunque un cliente falle.
    await hub.broadcast(event)

    expected = serialize_event(event)
    assert healthy_1.sent == [expected]
    assert healthy_2.sent == [expected]
    # El cliente que falló fue descartado del set de conexiones.
    assert failing not in hub._connections
    assert healthy_1 in hub._connections
    assert healthy_2 in hub._connections


def test_serialize_event_is_secret_free_and_only_declared_fields() -> None:
    """(c) serialize_event solo contiene las claves declaradas, sin secretos (R3.3)."""
    event = _sample_event()
    payload = serialize_event(event)

    assert set(payload.keys()) == {
        "event_type",
        "symbol",
        "side",
        "qty",
        "price",
        "order_id",
        "reason",
        "timestamp",
    }
    # Valores serializados JSON-safe.
    assert payload["event_type"] == "FILLED"
    assert payload["symbol"] == "BTC/USD"
    assert payload["side"] == "buy"
    assert payload["qty"] == "0.001"
    assert payload["price"] == "64000.50"
    assert payload["order_id"] == "abc-123"
    assert payload["reason"] == "filled"
    assert payload["timestamp"] == event.timestamp.isoformat()

    # Ningún material de credenciales aparece, ni por clave ni por valor.
    fake_api_key = "PKFAKEAPIKEY1234"
    fake_secret = "supersecretvalue"
    serialized_text = repr(payload).lower()
    assert "api_key" not in payload
    assert "secret" not in payload
    assert "credential" not in payload
    assert fake_api_key.lower() not in serialized_text
    assert fake_secret.lower() not in serialized_text


def test_serialize_event_handles_none_optional_fields() -> None:
    """serialize_event deja None los campos opcionales ausentes (qty/price/side)."""
    event = OrderEvent(event_type=EventType.ERROR, symbol="BTC/USD", reason="boom")
    payload = serialize_event(event)

    assert payload["side"] is None
    assert payload["qty"] is None
    assert payload["price"] is None
    assert payload["order_id"] is None
    assert payload["event_type"] == "ERROR"


@pytest.mark.asyncio
async def test_on_event_enqueues_and_consumption_delivers_to_clients() -> None:
    """(d) _on_event encola; el consumo vía broadcast entrega a los clientes (R3.2)."""
    publisher = EventPublisher()
    hub = WebSocketHub(publisher)
    client = FakeWebSocket()
    hub._connections.add(client)

    # El hub se suscribió al publisher en __init__: publicar dispara _on_event,
    # que encola el evento (puente síncrono -> async, sin bloquear al publisher).
    event = _sample_event()
    publisher.publish(event)

    assert hub._queue.qsize() == 1
    queued = await hub._queue.get()
    assert queued is event

    # Consumir = broadcast: el cliente recibe el evento serializado.
    await hub.broadcast(queued)
    assert client.sent == [serialize_event(event)]
