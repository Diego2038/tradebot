"""Pruebas de `positions.py` (Tarea 5, spec 04-order-execution).

Cubren el `PositionManager` (SL/TP) usando un `EventPublisher` real (in-memory)
suscrito a una lista y un factory falso cuyo `build_trading_client` devuelve un
cliente con `close_position` registrable:

- (a) SL alcanzado (price <= SL) cierra la posición y emite STOP_LOSS_CLOSE con
      el precio (R2.4).
- (b) TP alcanzado (price >= TP) cierra y emite TAKE_PROFIT_CLOSE (R2.5).
- (c) posición sin SL ni TP -> on_quote no cierra ni emite (no-op, R2.6).
- (d) nivel inválido en open_position (stop_loss >= entry o take_profit <= entry)
      -> InvalidLevelError (R2.2).
- (e) tras cerrar por SL, un quote posterior no emite un segundo evento.

`positions.py` importa `AlpacaClientFactory` (spec 01), que a su vez importa el
SDK `alpaca`. Stubbeamos ese import vía `sys.modules` ANTES de importar el
módulo bajo prueba (patrón de tests previos). El factory usado en los tests es
un doble propio, así que el stub solo evita el ImportError de carga.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from decimal import Decimal

import pytest

# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar módulos que lo cargan de forma
# no perezosa (factory.py hace `from alpaca.trading.client import TradingClient`).
# ---------------------------------------------------------------------------


def _install_alpaca_stub() -> None:
    if "alpaca.trading.client" in sys.modules:
        return

    alpaca_pkg = sys.modules.get("alpaca") or types.ModuleType("alpaca")
    alpaca_pkg.__path__ = []
    trading_pkg = sys.modules.get("alpaca.trading") or types.ModuleType("alpaca.trading")
    trading_pkg.__path__ = []

    client_mod = types.ModuleType("alpaca.trading.client")

    class _StubTradingClient:  # pragma: no cover - nunca se instancia en estos tests
        def __init__(self, *args, **kwargs):
            pass

    client_mod.TradingClient = _StubTradingClient

    sys.modules["alpaca"] = alpaca_pkg
    sys.modules["alpaca.trading"] = trading_pkg
    sys.modules["alpaca.trading.client"] = client_mod


_install_alpaca_stub()

from app.services.data_feed.models import Quote  # noqa: E402
from app.services.execution.errors import InvalidLevelError  # noqa: E402
from app.services.execution.events import EventPublisher, EventType  # noqa: E402
from app.services.execution.positions import PositionManager  # noqa: E402


# ---------------------------------------------------------------------------
# Dobles de prueba
# ---------------------------------------------------------------------------


class _FakeTradingClient:
    """Cliente falso que registra las llamadas a `close_position`."""

    def __init__(self) -> None:
        self.closed: list[str] = []

    def close_position(self, symbol: str) -> None:
        self.closed.append(symbol)


class _FakeFactory:
    """Factory doble: `build_trading_client` devuelve siempre el mismo cliente falso."""

    def __init__(self) -> None:
        self.client = _FakeTradingClient()
        self.build_calls = 0

    def build_trading_client(self) -> _FakeTradingClient:
        self.build_calls += 1
        return self.client


def _quote(price: str) -> Quote:
    return Quote(timestamp=datetime.now(timezone.utc), price=Decimal(price))


@pytest.fixture()
def wiring():
    """Devuelve (factory, publisher, events, PositionManager) listos para usar."""
    factory = _FakeFactory()
    publisher = EventPublisher()
    events: list = []
    publisher.subscribe(events.append)
    manager = PositionManager(factory=factory, publisher=publisher)
    return factory, publisher, events, manager


# ---------------------------------------------------------------------------
# (a) Stop-Loss alcanzado
# ---------------------------------------------------------------------------


def test_stop_loss_hit_closes_and_emits(wiring):
    factory, _publisher, events, manager = wiring
    manager.open_position(
        "BTC/USD", "buy", Decimal("0.001"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
    )

    manager.on_quote(_quote("90"))  # price <= SL

    assert factory.client.closed == ["BTC/USD"]
    assert manager.position is None
    assert len(events) == 1
    event = events[0]
    assert event.event_type == EventType.STOP_LOSS_CLOSE
    assert event.symbol == "BTC/USD"
    assert event.side == "buy"
    assert event.qty == Decimal("0.001")
    assert event.price == Decimal("90")


# ---------------------------------------------------------------------------
# (b) Take-Profit alcanzado
# ---------------------------------------------------------------------------


def test_take_profit_hit_closes_and_emits(wiring):
    factory, _publisher, events, manager = wiring
    manager.open_position(
        "BTC/USD", "buy", Decimal("0.001"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
    )

    manager.on_quote(_quote("125"))  # price >= TP

    assert factory.client.closed == ["BTC/USD"]
    assert manager.position is None
    assert len(events) == 1
    event = events[0]
    assert event.event_type == EventType.TAKE_PROFIT_CLOSE
    assert event.price == Decimal("125")


# ---------------------------------------------------------------------------
# (c) Sin SL ni TP -> no-op
# ---------------------------------------------------------------------------


def test_no_levels_is_noop(wiring):
    factory, _publisher, events, manager = wiring
    manager.open_position(
        "BTC/USD", "buy", Decimal("0.001"),
        entry_price=Decimal("100"),
    )

    manager.on_quote(_quote("1"))  # precio extremo, pero no hay niveles
    manager.on_quote(_quote("100000"))

    assert factory.client.closed == []
    assert events == []
    # La posición sigue abierta.
    assert manager.position is not None


def test_on_quote_within_levels_is_noop(wiring):
    """Precio entre SL y TP no dispara nada."""
    factory, _publisher, events, manager = wiring
    manager.open_position(
        "BTC/USD", "buy", Decimal("0.001"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
    )

    manager.on_quote(_quote("100"))  # dentro del rango

    assert factory.client.closed == []
    assert events == []
    assert manager.position is not None


# ---------------------------------------------------------------------------
# (d) Nivel inválido -> InvalidLevelError
# ---------------------------------------------------------------------------


def test_invalid_stop_loss_raises(wiring):
    _factory, _publisher, _events, manager = wiring
    with pytest.raises(InvalidLevelError):
        manager.open_position(
            "BTC/USD", "buy", Decimal("0.001"),
            entry_price=Decimal("100"),
            stop_loss=Decimal("100"),  # >= entry
        )
    assert manager.position is None


def test_invalid_take_profit_raises(wiring):
    _factory, _publisher, _events, manager = wiring
    with pytest.raises(InvalidLevelError):
        manager.open_position(
            "BTC/USD", "buy", Decimal("0.001"),
            entry_price=Decimal("100"),
            take_profit=Decimal("100"),  # <= entry
        )
    assert manager.position is None


def test_invalid_level_is_also_value_error(wiring):
    """InvalidLevelError subclasea ValueError (el llamador puede capturar ambos)."""
    _factory, _publisher, _events, manager = wiring
    with pytest.raises(ValueError):
        manager.open_position(
            "BTC/USD", "buy", Decimal("0.001"),
            entry_price=Decimal("100"),
            stop_loss=Decimal("110"),
        )


# ---------------------------------------------------------------------------
# (e) Tras cerrar por SL, un quote posterior no emite un segundo evento
# ---------------------------------------------------------------------------


def test_no_second_close_after_position_closed(wiring):
    factory, _publisher, events, manager = wiring
    manager.open_position(
        "BTC/USD", "buy", Decimal("0.001"),
        entry_price=Decimal("100"),
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
    )

    manager.on_quote(_quote("85"))  # dispara SL
    assert len(events) == 1
    assert manager.position is None

    # Quote posterior (aún por debajo del SL previo): no debe emitir nada más.
    manager.on_quote(_quote("80"))
    manager.on_quote(_quote("130"))

    assert len(events) == 1
    assert factory.client.closed == ["BTC/USD"]  # una sola llamada de cierre
