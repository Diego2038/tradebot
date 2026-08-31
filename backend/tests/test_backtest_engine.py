"""Inline tests for the backtest replay engine (spec 05-backtest-engine, Task 4).

Covers the run() flow end to end with scripted strategies over small, known
datasets:
- a known dataset yields the expected Total_Return / Trade_Count / Win_Rate /
  Max_Drawdown;
- a HOLD-only strategy yields trade_count == 0 and total_return == 0;
- empty bars complete with zeros;
- start > end raises InvalidDateRangeError (no bar replayed);
- an unregistered name raises UnknownStrategyError (strategy never invoked);
- a scripted out-of-range action raises InvalidActionError and stops the replay;
- the same request + seed run twice yields a field-by-field equal result.

Bars are built directly from spec-02 models and strategies are registered in a
spec-03 StrategyEngine; the engine performs no Alpaca calls, so no mocks are
needed. Uses ``pytest``.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9,
2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.backtest.constants import STARTING_EQUITY
from app.services.backtest.engine import BacktestEngine
from app.services.backtest.errors import InvalidActionError, InvalidDateRangeError
from app.services.backtest.models import BacktestRequest
from app.services.data_feed.models import Bar
from app.services.strategies.registry import StrategyEngine
from app.services.strategies.errors import UnknownStrategyError
from app.services.strategies.signals import Action, Signal

_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(closes: list[str]) -> list[Bar]:
    """Build a strictly ascending Bar sequence from close prices."""
    bars: list[Bar] = []
    for i, c in enumerate(closes):
        close = Decimal(c)
        bars.append(
            Bar(
                timestamp=_BASE_TS + timedelta(minutes=i),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("1"),
            )
        )
    return bars


class _ScriptedStrategy:
    """Strategy stub emitting a predetermined action per successive call.

    Conforms structurally to the spec-03 ``Strategy`` protocol (a ``generate``
    method). ``calls`` records the number of bars seen on each invocation so tests
    can assert one call per bar in ascending order.
    """

    def __init__(self, actions: list) -> None:
        self._actions = actions
        self._i = 0
        self.calls: list[int] = []

    def generate(self, bars, quote=None) -> Signal:
        self.calls.append(len(bars))
        action = self._actions[self._i]
        self._i += 1
        # ``action`` may be a non-Action sentinel to drive the invalid-action path.
        return Signal(action=action, reason="scripted", timestamp=_BASE_TS)


class _NeverCalled:
    """Strategy stub that fails if generate is ever invoked (R1.7 guard)."""

    def generate(self, bars, quote=None) -> Signal:  # pragma: no cover - must not run
        raise AssertionError("strategy should not be invoked")


def _engine_with(name: str, strategy) -> BacktestEngine:
    registry = StrategyEngine(default=name)
    registry.register(name, strategy)
    # Fixed qty of 1000 keeps the hand-computed metrics on clean numbers.
    return BacktestEngine(registry, qty=Decimal("1000"))


# --- known dataset -> expected metrics ------------------------------------


def test_known_dataset_expected_metrics() -> None:
    # A profitable round trip then a losing one, qty=1000:
    #   BUY@100, SELL@110 -> +10000 (equity 110000)
    #   BUY@110, SELL@100 -> -10000 (equity 100000)
    strat = _ScriptedStrategy([Action.BUY, Action.SELL, Action.BUY, Action.SELL])
    engine = _engine_with("scripted", strat)
    result = engine.run(BacktestRequest("scripted"), _bars(["100", "110", "110", "100"]))

    assert result.trade_count == 2
    assert result.win_rate == Decimal("0.500000")
    # Ends back at STARTING_EQUITY -> total_return 0.
    assert result.total_return == Decimal("0.000000")
    # Peak 110000 -> trough 100000: (110000 - 100000) / 110000 = 0.090909...
    assert result.max_drawdown == Decimal("0.090909")

    # One strategy call per bar, in ascending order (history grows by one).
    assert strat.calls == [1, 2, 3, 4]
    # Four recorded trades; realized_profit only on the closing sells.
    assert [t.side for t in result.trades] == ["buy", "sell", "buy", "sell"]
    assert result.trades[0].realized_profit is None
    assert result.trades[1].realized_profit == Decimal("10000")
    assert result.trades[3].realized_profit == Decimal("-10000")


# --- HOLD-only -> zero trades / zero return -------------------------------


def test_hold_only_yields_zero_trades_and_zero_return() -> None:
    strat = _ScriptedStrategy([Action.HOLD, Action.HOLD, Action.HOLD])
    engine = _engine_with("scripted", strat)
    result = engine.run(BacktestRequest("scripted"), _bars(["100", "110", "120"]))

    assert result.trade_count == 0
    assert result.total_return == Decimal("0")
    assert result.win_rate == Decimal("0")
    assert result.max_drawdown == Decimal("0")
    assert result.trades == []


# --- empty bars -> completed run with zeros -------------------------------


def test_empty_bars_completes_with_zeros() -> None:
    strat = _ScriptedStrategy([])
    engine = _engine_with("scripted", strat)
    result = engine.run(BacktestRequest("scripted"), [])

    assert result.trade_count == 0
    assert result.total_return == Decimal("0")
    assert result.win_rate == Decimal("0")
    assert result.max_drawdown == Decimal("0")
    assert result.trades == []
    # No replay happened.
    assert strat.calls == []


# --- invalid Date_Range ---------------------------------------------------


def test_start_after_end_raises_invalid_date_range() -> None:
    strat = _ScriptedStrategy([Action.BUY])
    engine = _engine_with("scripted", strat)
    request = BacktestRequest(
        "scripted",
        start=_BASE_TS + timedelta(days=1),
        end=_BASE_TS,
    )
    with pytest.raises(InvalidDateRangeError):
        engine.run(request, _bars(["100", "110"]))
    # No bar replayed.
    assert strat.calls == []


# --- unregistered strategy name -------------------------------------------


def test_unregistered_name_raises_and_never_invokes_strategy() -> None:
    registry = StrategyEngine(default="scripted")
    registry.register("scripted", _NeverCalled())
    engine = BacktestEngine(registry, qty=Decimal("1000"))
    with pytest.raises(UnknownStrategyError):
        engine.run(BacktestRequest("does-not-exist"), _bars(["100", "110"]))


# --- out-of-range action stops the replay ---------------------------------


def test_out_of_range_action_raises_and_stops_replay() -> None:
    # Second call returns a non-Action sentinel -> InvalidActionError at bar 1.
    strat = _ScriptedStrategy([Action.BUY, "NOPE", Action.SELL])
    engine = _engine_with("scripted", strat)
    with pytest.raises(InvalidActionError):
        engine.run(BacktestRequest("scripted"), _bars(["100", "110", "120"]))
    # Replay stopped at the offending bar (2 calls, not 3).
    assert strat.calls == [1, 2]


# --- reproducibility with seed --------------------------------------------


def test_same_request_and_seed_run_twice_equal() -> None:
    # Randomized strategy resolved through the registry; seeding must make two runs
    # field-by-field equal (R4.1, R4.2, R4.4).
    from app.services.strategies.random_strategy import RandomStrategy

    registry = StrategyEngine(default="random")
    registry.register("random", RandomStrategy())
    engine = BacktestEngine(registry, qty=Decimal("1000"))

    bars = _bars([str(100 + i) for i in range(20)])
    request = BacktestRequest("random", seed=1234)

    first = engine.run(request, bars)
    second = engine.run(request, bars)

    assert first == second
    assert first.trades == second.trades
