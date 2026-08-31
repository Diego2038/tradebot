"""Backtest engine package (spec 05-backtest-engine).

Replays an ordered sequence of spec-02 ``Bar``\\ s through a spec-03 strategy
entirely in memory (no Alpaca, no DB, no network) and reports four metrics —
Total_Return, Trade_Count, Win_Rate, Max_Drawdown — plus the ordered trades.

Public API:
- ``BacktestRequest``, ``SimulatedTrade``, ``BacktestResult`` — the data models.
- ``BacktestEngine`` — the replay loop that produces a ``BacktestResult``.
- ``BacktestError`` / ``InvalidDateRangeError`` / ``InvalidActionError`` — domain errors.
- ``STARTING_EQUITY`` / ``METRIC_DECIMALS`` — run constants.
"""

from app.services.backtest.constants import METRIC_DECIMALS, STARTING_EQUITY
from app.services.backtest.engine import BacktestEngine
from app.services.backtest.errors import (
    BacktestError,
    InvalidActionError,
    InvalidDateRangeError,
)
from app.services.backtest.models import (
    BacktestRequest,
    BacktestResult,
    SimulatedTrade,
)

__all__ = [
    "BacktestRequest",
    "SimulatedTrade",
    "BacktestResult",
    "BacktestEngine",
    "BacktestError",
    "InvalidDateRangeError",
    "InvalidActionError",
    "STARTING_EQUITY",
    "METRIC_DECIMALS",
]
