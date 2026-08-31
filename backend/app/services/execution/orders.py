"""Deterministic idempotency key and order-request builder (spec 04-order-execution, Task 3).

This module is **owned by spec ``04-order-execution``** and provides the two pure /
SDK-boundary helpers the ``OrderExecutor`` uses to submit a paper order idempotently:

- :func:`make_client_order_id` -- a **pure** function that derives a deterministic
  ``Client_Order_Id`` from a ``Logical_Order_Attempt`` (symbol + side + attempt key).
  Equal inputs always yield an equal id, so a retry reuses it and Alpaca dedupes at
  its end (R3.1, R3.2). The id is a stable SHA-1 hash prefix, well within Alpaca's
  ``client_order_id`` length limit.
- :func:`build_market_order_request` -- builds the ``alpaca-py`` ``MarketOrderRequest``
  for one paper order, mapping the ``"buy"``/``"sell"`` side to ``OrderSide`` and
  attaching the deterministic ``client_order_id`` (R1.1, R1.2, R3.1).

The Alpaca SDK is imported **lazily inside** :func:`build_market_order_request` (as in
specs 01/02) so importing this module never requires the SDK to be installed, keeping
:func:`make_client_order_id` and the tests that only exercise it fully SDK-free.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

__all__ = ["make_client_order_id", "build_market_order_request"]


def make_client_order_id(symbol: str, side: str, attempt_key: str) -> str:
    """Return a deterministic ``Client_Order_Id`` for one ``Logical_Order_Attempt``.

    The id is derived purely from the logical attempt (``symbol``, ``side`` and
    ``attempt_key``) via a stable SHA-1 hash, prefixed with ``"tb-"``. Because the
    function is pure, equal inputs always produce the same id (so a retry reuses it,
    R3.2) and different inputs produce different ids. The hash prefix keeps the id
    short and stable, well within Alpaca's ``client_order_id`` length limit (R3.1).

    Args:
        symbol: The instrument symbol (e.g. ``"BTC/USD"``).
        side: The order side, ``"buy"`` or ``"sell"``.
        attempt_key: A value uniquely identifying the intent (e.g. the signal
            timestamp/id) so distinct attempts get distinct ids.

    Returns:
        A deterministic id of the form ``"tb-" + <24 hex chars>`` (27 chars total).
    """
    raw = f"{symbol}|{side}|{attempt_key}".encode("utf-8")
    return "tb-" + hashlib.sha1(raw).hexdigest()[:24]


def build_market_order_request(
    symbol: str, side: str, qty: Decimal, client_order_id: str
):
    """Build the ``alpaca-py`` ``MarketOrderRequest`` for a paper market order.

    Alpaca SDK symbols are imported lazily inside this function (as in specs 01/02)
    so merely importing this module never requires the SDK. The ``side`` is mapped
    case-insensitively: ``"buy"`` -> ``OrderSide.BUY`` and ``"sell"`` ->
    ``OrderSide.SELL``; any other value raises a clear :class:`ValueError`. The order
    is ``TimeInForce.GTC`` and carries the deterministic ``client_order_id`` so
    retries are idempotent (R1.1, R1.2, R3.1).

    Args:
        symbol: The instrument symbol (e.g. ``"BTC/USD"``).
        side: The order side, ``"buy"`` or ``"sell"`` (case-insensitive).
        qty: The order quantity as a :class:`~decimal.Decimal`.
        client_order_id: The deterministic id from :func:`make_client_order_id`.

    Returns:
        A configured ``MarketOrderRequest`` ready to hand to ``TradingClient.submit_order``.

    Raises:
        ValueError: If ``side`` is not ``"buy"`` or ``"sell"``.
    """
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    normalized = side.strip().lower()
    if normalized == "buy":
        order_side = OrderSide.BUY
    elif normalized == "sell":
        order_side = OrderSide.SELL
    else:
        raise ValueError(f"Invalid order side {side!r}; expected 'buy' or 'sell'.")

    return MarketOrderRequest(
        symbol=symbol,
        qty=float(qty),
        side=order_side,
        time_in_force=TimeInForce.GTC,
        client_order_id=client_order_id,
    )
