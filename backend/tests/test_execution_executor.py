"""Pruebas del `OrderExecutor` (Tarea 6, spec 04-order-execution).

El SDK de Alpaca se stubbea vía ``sys.modules`` ANTES de importar el ejecutor
(patrón de ``test_factory.py`` / ``test_execution_orders.py``): ni el SDK ni la
red están disponibles en el entorno de test. Se stubbean:

- ``alpaca.trading.client.TradingClient`` con ``submit_order``.
- ``alpaca.trading.requests.MarketOrderRequest``.
- ``alpaca.trading.enums.OrderSide`` / ``TimeInForce``.
- ``alpaca.common.exceptions.APIError`` con ``status_code``.

El `AlpacaClientFactory` se mockea (``build_trading_client`` devuelve un cliente
fake con ``submit_order`` configurable). El `RiskPort` se falsea (aprobar /
rechazar) y el `EventPublisher` es real, suscrito a una lista para inspección.

Cubre:
- (a) HOLD -> no llama ``submit_order`` y devuelve ``None`` (R1.4).
- (b) BUY aprobado -> llama ``submit_order`` con symbol/side/qty/client_order_id
  correctos y publica ``SUBMITTED`` (y ``FILLED`` si la orden viene llena)
  (R1.1, R1.2, R1.3, R5.1, R5.2).
- (c) riesgo rechaza -> no llama ``submit_order`` y publica ``RISK_BLOCK`` con el
  reason (R1.5, R5.3).
- (d) sin credenciales: ``build_trading_client`` lanza ``CredentialsRequiredError``
  -> ``execute_signal`` la propaga y ``submit_order`` nunca se llama (R1.8).
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar el ejecutor.
# ---------------------------------------------------------------------------


class _FakeAPIError(Exception):
    """Sustituto de alpaca.common.exceptions.APIError con status HTTP."""

    def __init__(self, message: str = "api error", status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class _FakeMarketOrderRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeOrderSide:
    BUY = "OrderSide.BUY"
    SELL = "OrderSide.SELL"


class _FakeTimeInForce:
    GTC = "TimeInForce.GTC"


class _FakeTradingClient:
    def __init__(self, api_key=None, secret_key=None, paper=True, **kwargs):
        self._paper = paper

    def submit_order(self, order_data):  # pragma: no cover - se mockea por test
        raise NotImplementedError


def _install_alpaca_stub() -> None:
    alpaca_pkg = sys.modules.get("alpaca") or types.ModuleType("alpaca")
    alpaca_pkg.__path__ = []
    trading_pkg = sys.modules.get("alpaca.trading") or types.ModuleType(
        "alpaca.trading"
    )
    trading_pkg.__path__ = []

    client_mod = sys.modules.get("alpaca.trading.client") or types.ModuleType(
        "alpaca.trading.client"
    )
    if not hasattr(client_mod, "TradingClient"):
        client_mod.TradingClient = _FakeTradingClient

    # No sobrescribir los stubs de requests/enums si otro módulo de test ya los
    # instaló: sus tests hacen ``isinstance`` contra SU propia clase, así que
    # reutilizamos lo que exista y solo rellenamos lo que falte.
    requests_mod = sys.modules.get("alpaca.trading.requests") or types.ModuleType(
        "alpaca.trading.requests"
    )
    if not hasattr(requests_mod, "MarketOrderRequest"):
        requests_mod.MarketOrderRequest = _FakeMarketOrderRequest

    enums_mod = sys.modules.get("alpaca.trading.enums") or types.ModuleType(
        "alpaca.trading.enums"
    )
    if not hasattr(enums_mod, "OrderSide"):
        enums_mod.OrderSide = _FakeOrderSide
    if not hasattr(enums_mod, "TimeInForce"):
        enums_mod.TimeInForce = _FakeTimeInForce

    common_pkg = sys.modules.get("alpaca.common") or types.ModuleType("alpaca.common")
    common_pkg.__path__ = []
    exceptions_mod = sys.modules.get(
        "alpaca.common.exceptions"
    ) or types.ModuleType("alpaca.common.exceptions")
    if not hasattr(exceptions_mod, "APIError"):
        exceptions_mod.APIError = _FakeAPIError

    sys.modules["alpaca"] = alpaca_pkg
    sys.modules["alpaca.trading"] = trading_pkg
    sys.modules["alpaca.trading.client"] = client_mod
    sys.modules["alpaca.trading.requests"] = requests_mod
    sys.modules["alpaca.trading.enums"] = enums_mod
    sys.modules["alpaca.common"] = common_pkg
    sys.modules["alpaca.common.exceptions"] = exceptions_mod


_install_alpaca_stub()

from app.services.alpaca_client.errors import (  # noqa: E402
    CredentialsRequiredError,
)
from app.services.execution.events import (  # noqa: E402
    EventPublisher,
    EventType,
)
from app.services.execution.executor import OrderExecutor  # noqa: E402
from app.services.execution.orders import make_client_order_id  # noqa: E402
from app.services.execution.risk import RiskDecision  # noqa: E402
from app.services.strategies.signals import Action, Signal  # noqa: E402

# Resolvemos OrderSide desde el mismo módulo que usa `orders` (puede haber sido
# stubbeado por otro módulo de test antes que este); así las aserciones de side
# comparan contra la clase realmente instalada, no contra una copia local.
from alpaca.trading.enums import OrderSide as _OrderSide  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class _FakeRisk:
    """RiskPort falso: aprueba o rechaza con un reason fijo."""

    def __init__(self, approved: bool, reason: str = ""):
        self._decision = RiskDecision(approved=approved, reason=reason)
        self.calls: list = []

    def evaluate(self, proposed_order):
        self.calls.append(proposed_order)
        return self._decision


class _FakeOrder:
    """Orden devuelta por submit_order con id/status/precio."""

    def __init__(self, order_id="ord-1", status="filled", filled_avg_price="42000"):
        self.id = order_id
        self.status = status
        self.filled_avg_price = filled_avg_price


def _make_factory(client):
    factory = mock.Mock()
    factory.build_trading_client.return_value = client
    return factory


def _collect_publisher():
    publisher = EventPublisher()
    events: list = []
    publisher.subscribe(events.append)
    return publisher, events


def _signal(action: Action) -> Signal:
    return Signal(
        action=action,
        reason="test",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# (a) HOLD -> no submit, devuelve None
# ---------------------------------------------------------------------------


def test_hold_submits_no_order_and_returns_none():
    client = mock.Mock()
    factory = _make_factory(client)
    risk = _FakeRisk(approved=True)
    publisher, events = _collect_publisher()

    executor = OrderExecutor(factory, risk, publisher)
    result = executor.execute_signal(_signal(Action.HOLD))

    assert result is None
    client.submit_order.assert_not_called()
    # HOLD ni siquiera consulta al riesgo ni construye el cliente.
    factory.build_trading_client.assert_not_called()
    assert risk.calls == []
    assert events == []


# ---------------------------------------------------------------------------
# (b) BUY aprobado -> submit con parámetros correctos + SUBMITTED/FILLED
# ---------------------------------------------------------------------------


def test_approved_buy_submits_with_correct_params_and_publishes():
    client = mock.Mock()
    client.submit_order.return_value = _FakeOrder(
        order_id="ord-buy", status="filled", filled_avg_price="42000.50"
    )
    factory = _make_factory(client)
    risk = _FakeRisk(approved=True)
    publisher, events = _collect_publisher()

    symbol = "BTC/USD"
    qty = Decimal("0.001")
    executor = OrderExecutor(factory, risk, publisher, symbol=symbol, qty=qty)
    signal = _signal(Action.BUY)
    result = executor.execute_signal(signal)

    # El riesgo se consulta antes de enviar, con el side "buy".
    assert len(risk.calls) == 1
    proposed = risk.calls[0]
    assert proposed.side == "buy"
    assert proposed.symbol == symbol
    assert proposed.qty == qty

    # submit_order se llama exactamente una vez con la request correcta.
    client.submit_order.assert_called_once()
    request = client.submit_order.call_args.args[0]
    assert request.symbol == symbol
    assert request.side == _OrderSide.BUY
    assert request.qty == float(qty)

    # client_order_id determinista derivado de la señal.
    attempt_key = signal.timestamp.isoformat() + "|" + signal.action.value
    expected_id = make_client_order_id(symbol, "buy", attempt_key)
    assert request.client_order_id == expected_id

    # Publica SUBMITTED y luego FILLED (orden llena).
    types_published = [e.event_type for e in events]
    assert EventType.SUBMITTED in types_published
    assert EventType.FILLED in types_published
    assert result is not None
    assert result.event_type == EventType.FILLED
    assert result.order_id == "ord-buy"
    assert result.side == "buy"
    assert result.qty == qty


def test_approved_sell_uses_sell_side():
    client = mock.Mock()
    client.submit_order.return_value = _FakeOrder(status="accepted")
    factory = _make_factory(client)
    risk = _FakeRisk(approved=True)
    publisher, events = _collect_publisher()

    executor = OrderExecutor(factory, risk, publisher)
    result = executor.execute_signal(_signal(Action.SELL))

    assert risk.calls[0].side == "sell"
    request = client.submit_order.call_args.args[0]
    assert request.side == _OrderSide.SELL
    # Sin fill confirmado: al menos SUBMITTED y ese es el evento terminal.
    assert result is not None
    assert result.event_type == EventType.SUBMITTED
    assert EventType.SUBMITTED in [e.event_type for e in events]


# ---------------------------------------------------------------------------
# (c) riesgo rechaza -> no submit + RISK_BLOCK con reason
# ---------------------------------------------------------------------------


def test_risk_rejection_blocks_order_and_publishes_risk_block():
    client = mock.Mock()
    factory = _make_factory(client)
    risk = _FakeRisk(approved=False, reason="daily loss limit reached")
    publisher, events = _collect_publisher()

    executor = OrderExecutor(factory, risk, publisher)
    result = executor.execute_signal(_signal(Action.BUY))

    client.submit_order.assert_not_called()
    factory.build_trading_client.assert_not_called()

    assert result is not None
    assert result.event_type == EventType.RISK_BLOCK
    assert result.reason == "daily loss limit reached"
    assert [e.event_type for e in events] == [EventType.RISK_BLOCK]
    assert events[0].reason == "daily loss limit reached"


# ---------------------------------------------------------------------------
# (d) sin credenciales -> propaga CredentialsRequiredError, no submit
# ---------------------------------------------------------------------------


def test_missing_credentials_propagate_and_never_submit():
    client = mock.Mock()
    factory = _make_factory(client)
    factory.build_trading_client.side_effect = CredentialsRequiredError(
        "no credentials configured"
    )
    risk = _FakeRisk(approved=True)
    publisher, events = _collect_publisher()

    executor = OrderExecutor(factory, risk, publisher)

    with pytest.raises(CredentialsRequiredError):
        executor.execute_signal(_signal(Action.BUY))

    client.submit_order.assert_not_called()
