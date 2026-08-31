"""Pydantic schemas for the backtest HTTP surface (spec 05-backtest-engine).

These schemas live only at the HTTP boundary; the internal domain format remains
the ``BacktestRequest`` / ``BacktestResult`` / ``SimulatedTrade`` dataclasses in
``services/backtest/models.py`` (no Alpaca types cross this boundary).

- :class:`BacktestRunRequest` -- the ``POST /backtest`` body. ``mode`` is a
  ``Literal["random", "predictive"]`` so an unknown mode is rejected at the API
  edge with a ``422`` before reaching the engine (same edge-validation contract as
  the bot API, R2.4). An unregistered-but-well-typed mode would surface
  :class:`UnknownStrategyError` (mapped to ``400 invalid_mode``).
- :class:`SimulatedTradeOut` -- serialization mirror of the domain
  :class:`SimulatedTrade`.
- :class:`BacktestResultOut` -- serialization mirror of the domain
  :class:`BacktestResult`, plus ``bars_evaluated`` (how many historical bars were
  replayed) for transparency.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class BacktestRunRequest(BaseModel):
    """Body of ``POST /backtest``.

    ``mode`` is constrained to the registered strategy names; any other value is
    rejected by FastAPI with a ``422`` validation error before reaching the engine
    (defense in depth, mirroring the bot API contract for R2.4).
    """

    mode: Literal["random", "predictive"]
    start: datetime
    end: datetime
    symbol: str = "BTC/USD"
    timeframe: str = "1Min"
    seed: int | None = None


class SimulatedTradeOut(BaseModel):
    """Serialized in-memory simulated trade (mirror of :class:`SimulatedTrade`)."""

    side: str
    qty: Decimal
    price: Decimal
    timestamp: datetime
    reason: str = ""
    realized_profit: Decimal | None = None


class BacktestResultOut(BaseModel):
    """Serialized backtest result (mirror of :class:`BacktestResult`).

    ``bars_evaluated`` reports how many historical bars were replayed, exposed
    purely for transparency (it is not part of the domain result).
    """

    total_return: Decimal
    trade_count: int
    win_rate: Decimal
    max_drawdown: Decimal
    trades: list[SimulatedTradeOut]
    bars_evaluated: int
