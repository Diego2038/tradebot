"""Data models for the backtest engine (spec 05-backtest-engine).

Frozen dataclasses carrying the run configuration, in-memory simulated trades,
and the result metrics. No Alpaca types cross this boundary and the models perform
no I/O; the ordered ``Bar`` sequence is passed separately to ``BacktestEngine.run``.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class BacktestRequest:
    """Input to a backtest run (R1.1).

    The Bar_Sequence itself is passed separately to BacktestEngine.run(); this model
    carries only the run configuration. strategy_name is resolved through the spec-03
    registry (R3.3). start/end bound the Date_Range inclusively; start > end is invalid
    (R1.8). seed, when present, initializes strategy randomness before replay (R4.2);
    when absent, a randomized strategy still runs but is not guaranteed reproducible
    (R4.5).
    """

    strategy_name: str          # resolved through the spec-03 StrategyEngine/registry
    symbol: str = "BTC/USD"     # single asset in this phase
    timeframe: str = "1Min"     # one of 1Min / 5Min / 15Min / 1Hour / 1Day (spec 02)
    start: datetime | None = None   # inclusive Date_Range start (UTC)
    end: datetime | None = None     # inclusive Date_Range end (UTC)
    seed: int | None = None         # optional Seed for strategy randomness (R4.2)


@dataclass(frozen=True)
class SimulatedTrade:
    """An in-memory entry or exit derived from a Signal during replay (R1.3).

    Never reaches Alpaca. `side` is "buy" or "sell"; `price` is the bar close at which
    the trade is simulated; `timestamp` is the bar's timestamp; `realized_profit` is set
    only on the closing exit of a completed round trip (None on the opening entry).
    """

    side: str                       # "buy" / "sell"
    qty: Decimal
    price: Decimal                  # simulated fill price (bar close)
    timestamp: datetime
    reason: str = ""                # carried from the Signal for transparency
    realized_profit: Decimal | None = None   # set on the closing exit of a round trip


@dataclass(frozen=True)
class BacktestResult:
    """Output of a completed backtest run (R2.1).

    Reports exactly the four metrics plus the ordered list of Simulated_Trade. Metric
    fractions are rounded to METRIC_DECIMALS (R2.6). total_return >= -1 (R2.3); win_rate
    and max_drawdown are in [0, 1] (R2.4, R2.5). When trade_count == 0, total_return,
    win_rate, and max_drawdown are all zero (R1.6, R2.7).
    """

    total_return: Decimal           # (end_equity - start_equity) / start_equity, >= -1 (R2.3)
    trade_count: int                # completed round-trip trades (R2.1)
    win_rate: Decimal               # fraction of profitable round trips, in [0, 1] (R2.4)
    max_drawdown: Decimal           # largest peak-to-trough decline / peak, in [0, 1] (R2.5)
    trades: list[SimulatedTrade]    # ordered sequence of simulated trades (R2.1)
