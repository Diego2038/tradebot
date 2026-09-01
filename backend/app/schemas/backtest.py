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
  replayed) and the derived absolute figures (``starting_equity``, ``net_profit``,
  ``final_equity``) for interpretability.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    """Body of ``POST /backtest``.

    ``mode`` is constrained to the registered strategy names; any other value is
    rejected by FastAPI with a ``422`` validation error before reaching the engine
    (defense in depth, mirroring the bot API contract for R2.4).

    ``qty`` is validated at the same HTTP edge with ``gt=0``, so a non-positive
    position size is rejected with a ``422`` before the engine is even built --
    exactly like an out-of-range ``mode``, keeping edge validation in one place
    instead of introducing a new domain error code.
    """

    mode: Literal["random", "predictive"]
    start: datetime
    end: datetime
    symbol: str = "BTC/USD"
    timeframe: str = "1Min"
    seed: int | None = None
    qty: Decimal | None = Field(default=None, gt=0)
    """Position size (in units of the asset, e.g. BTC) used on every simulated trade.

    When omitted, the engine's own default is used (``0.001`` BTC). That default is
    tiny relative to the simulated ``STARTING_EQUITY`` of ``100000``: at BTC around
    79,000 the notional per trade is roughly 79, i.e. about 0.08% of the capital, so
    percentage metrics (``total_return``, ``max_drawdown``) come out vanishingly
    small and hard to judge. A larger ``qty`` produces percentages with actual
    meaning against the starting capital (e.g. ``qty=1`` is close to deploying the
    whole 100,000 with BTC around 79,000).

    Must be strictly positive; ``0`` or a negative value is rejected with ``422``.
    """


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

    ``starting_equity`` / ``net_profit`` / ``final_equity`` are absolute figures
    DERIVED at this HTTP layer for interpretability: percentages alone are hard to
    read when the position size is small, so the money amounts are reported next to
    them. The domain result still reports exactly the four spec metrics
    (``total_return``, ``trade_count``, ``win_rate``, ``max_drawdown``); these three
    are an HTTP-layer convenience, same as ``bars_evaluated``.
    """

    total_return: Decimal
    trade_count: int
    win_rate: Decimal
    max_drawdown: Decimal
    starting_equity: Decimal
    """Simulated capital every run starts from (``STARTING_EQUITY``, 100000)."""
    net_profit: Decimal
    """Sum of the realized P&L of every completed round trip (absolute, derived)."""
    final_equity: Decimal
    """``starting_equity + net_profit`` (absolute, derived)."""
    trades: list[SimulatedTradeOut]
    bars_evaluated: int
