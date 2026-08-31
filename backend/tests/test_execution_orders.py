"""Pruebas de `orders.py` (Tarea 3, spec 04-order-execution).

Cubren:

- `make_client_order_id`: función pura y determinista. Misma
  ``(symbol, side, attempt_key)`` -> mismo id; cambiar cualquiera de los tres ->
  id distinto. El id empieza con ``"tb-"`` y tiene longitud acotada (R3.1, R3.2).
- `build_market_order_request`: se stubbea el SDK de Alpaca vía ``sys.modules``
  ANTES de importar ``orders`` (los módulos ``alpaca.trading.requests`` y
  ``alpaca.trading.enums`` no están instalados y no deben tocar red). Se verifica
  que la request se construye con símbolo, side, qty y client_order_id correctos, y
  que un side inválido produce ``ValueError`` (R1.1, R1.2, R3.1).
"""
from __future__ import annotations

import sys
import types
from decimal import Decimal

import pytest

# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar `orders` (patrón de test_factory.py).
# `build_market_order_request` importa PEREZOSAMENTE
# `alpaca.trading.requests.MarketOrderRequest` y
# `alpaca.trading.enums.{OrderSide, TimeInForce}`.
# ---------------------------------------------------------------------------


class _FakeMarketOrderRequest:
    """Captura los kwargs con los que se construye la request."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        # También como atributos para comodidad de aserción.
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeOrderSide:
    BUY = "OrderSide.BUY"
    SELL = "OrderSide.SELL"


class _FakeTimeInForce:
    GTC = "TimeInForce.GTC"


def _install_alpaca_stub() -> None:
    if "alpaca.trading.requests" in sys.modules and "alpaca.trading.enums" in sys.modules:
        return

    alpaca_pkg = sys.modules.get("alpaca") or types.ModuleType("alpaca")
    alpaca_pkg.__path__ = []
    trading_pkg = sys.modules.get("alpaca.trading") or types.ModuleType("alpaca.trading")
    trading_pkg.__path__ = []

    requests_mod = types.ModuleType("alpaca.trading.requests")
    requests_mod.MarketOrderRequest = _FakeMarketOrderRequest

    enums_mod = types.ModuleType("alpaca.trading.enums")
    enums_mod.OrderSide = _FakeOrderSide
    enums_mod.TimeInForce = _FakeTimeInForce

    sys.modules["alpaca"] = alpaca_pkg
    sys.modules["alpaca.trading"] = trading_pkg
    sys.modules["alpaca.trading.requests"] = requests_mod
    sys.modules["alpaca.trading.enums"] = enums_mod


_install_alpaca_stub()

from app.services.execution.orders import (  # noqa: E402
    build_market_order_request,
    make_client_order_id,
)


# ---------------------------------------------------------------------------
# make_client_order_id
# ---------------------------------------------------------------------------


def test_make_client_order_id_is_deterministic():
    """Misma entrada -> mismo id (R3.1, R3.2)."""
    first = make_client_order_id("BTC/USD", "buy", "attempt-1")
    second = make_client_order_id("BTC/USD", "buy", "attempt-1")
    assert first == second


def test_make_client_order_id_prefix_and_bounded_length():
    """El id empieza con 'tb-' y su longitud está acotada al límite de Alpaca."""
    order_id = make_client_order_id("BTC/USD", "buy", "attempt-1")
    assert order_id.startswith("tb-")
    # "tb-" (3) + 24 hex = 27 chars, muy por debajo del límite de Alpaca.
    assert len(order_id) == 27
    assert len(order_id) <= 128


@pytest.mark.parametrize(
    "a, b",
    [
        # cambia symbol
        (("ETH/USD", "buy", "k"), ("BTC/USD", "buy", "k")),
        # cambia side
        (("BTC/USD", "sell", "k"), ("BTC/USD", "buy", "k")),
        # cambia attempt_key
        (("BTC/USD", "buy", "k1"), ("BTC/USD", "buy", "k2")),
    ],
)
def test_make_client_order_id_differs_when_any_input_changes(a, b):
    """Distinta entrada (en cualquiera de los tres campos) -> id distinto."""
    assert make_client_order_id(*a) != make_client_order_id(*b)


# ---------------------------------------------------------------------------
# build_market_order_request
# ---------------------------------------------------------------------------


def test_build_market_order_request_buy():
    """Construye la request con símbolo, side BUY, qty y client_order_id correctos."""
    request = build_market_order_request(
        "BTC/USD", "buy", Decimal("0.001"), "tb-x"
    )
    # Se compara contra la clase realmente instalada en sys.modules (otro módulo
    # de test puede haber stubbeado el SDK antes que este), no contra la copia
    # local, para no depender del orden de recolección.
    from alpaca.trading.enums import OrderSide
    from alpaca.trading.requests import MarketOrderRequest

    assert isinstance(request, MarketOrderRequest)
    assert request.symbol == "BTC/USD"
    assert request.side == OrderSide.BUY
    assert request.qty == float(Decimal("0.001"))
    assert request.client_order_id == "tb-x"


def test_build_market_order_request_sell_case_insensitive():
    """side 'SELL' (mayúsculas) mapea a OrderSide.SELL."""
    request = build_market_order_request(
        "BTC/USD", "SELL", Decimal("0.5"), "tb-y"
    )
    from alpaca.trading.enums import OrderSide

    assert request.side == OrderSide.SELL
    assert request.qty == float(Decimal("0.5"))


def test_build_market_order_request_invalid_side_raises_value_error():
    """side inválido -> ValueError claro."""
    with pytest.raises(ValueError):
        build_market_order_request("BTC/USD", "hold", Decimal("0.001"), "tb-z")
