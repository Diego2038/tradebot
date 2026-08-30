"""Inline tests for the predictive strategy (spec 03, task 5).

Covers:
- (a) constructed SMA crossover up -> BUY; down -> SELL.
- (b) RSI pushed above overbought -> SELL; below oversold (exit) -> BUY.
- (c) insufficient bars -> HOLD.
- (d) invalid parameters -> ValueError.
- (e) determinism: same input twice -> same Signal.
- (f) reason names the triggering indicator (SMA/RSI).

Series are engineered with small periods (short=2, long=3) so the crossover can
be constructed by hand and verified against the SMA/RSI definitions in
``indicators.py``. Uses ``Decimal`` and ``pytest``.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.data_feed.models import Bar, Quote
from app.services.strategies.predictive_strategy import (
    PERIOD_MAX,
    PERIOD_MIN,
    PredictiveStrategy,
)
from app.services.strategies.signals import Action


_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(closes):
    """Build Bars with increasing timestamps and a given close.

    open/high/low/volume are derived from the close so each Bar is valid; only
    the close matters for the predictive strategy.
    """
    bars = []
    for i, c in enumerate(closes):
        close = Decimal(str(c))
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


# --- (a) SMA crossover ----------------------------------------------------


def test_sma_cross_up_emits_buy():
    # short=2, long=3. We want short_prev <= long_prev and short_last > long_last
    # on the last aligned position.
    #
    # closes = [10, 10, 10, 8, 14]
    #   short(2): [10, 10, 9, 11]        -> prev=9,   last=11
    #   long(3):  [10, 9.333, 10.667]    -> prev=9.33, last=10.667
    #   short_prev(9) <= long_prev(9.33) and short_last(11) > long_last(10.667) -> BUY
    strat = PredictiveStrategy(
        short_period=2, long_period=3, rsi_period=2, rsi_oversold=30, rsi_overbought=70
    )
    bars = _bars([10, 10, 10, 8, 14])
    sig = strat.generate(bars)
    assert sig.action is Action.BUY
    assert "SMA" in sig.reason


def test_sma_cross_down_emits_sell():
    # Mirror: short_prev >= long_prev and short_last < long_last.
    #
    # closes = [10, 10, 10, 12, 6]
    #   short(2): [10, 10, 11, 9]        -> prev=11,   last=9
    #   long(3):  [10, 10.667, 9.333]    -> prev=10.667, last=9.333
    #   short_prev(11) >= long_prev(10.667) and short_last(9) < long_last(9.333) -> SELL
    strat = PredictiveStrategy(
        short_period=2, long_period=3, rsi_period=2, rsi_oversold=30, rsi_overbought=70
    )
    bars = _bars([10, 10, 10, 12, 6])
    sig = strat.generate(bars)
    assert sig.action is Action.SELL
    assert "SMA" in sig.reason


# --- (b) RSI --------------------------------------------------------------


def test_rsi_overbought_emits_sell():
    # Isolate RSI overbought entry with no SMA crossover on the last position.
    #
    # closes = [10, 12, 11, 13, 12, 16] with short=2, long=3, rsi_period=2.
    #   The oscillating rise keeps rsi_prev in the mid band (~54.5, i.e. > oversold
    #   and < overbought) and the final strong gain 12->16 lifts rsi_last to ~88
    #   (>= overbought) -> entry into overbought -> SELL. The final SMAs do not
    #   cross (both keep rising with short above long), so RSI decides. Because
    #   rsi_prev is mid-band, the oversold-exit BUY rule does not fire, isolating
    #   the overbought SELL effect.
    strat = PredictiveStrategy(
        short_period=2, long_period=3, rsi_period=2, rsi_oversold=30, rsi_overbought=70
    )
    bars = _bars([10, 12, 11, 13, 12, 16])
    sig = strat.generate(bars)
    assert sig.action is Action.SELL
    assert "RSI" in sig.reason


def test_rsi_exit_oversold_emits_buy():
    # Isolate RSI exit from oversold with no SMA crossover on the last position.
    #
    # closes = [20, 18, 16, 14, 12, 13] with short=2, long=3, rsi_period=2.
    #   The declining prefix drives RSI to 0 (all losses -> oversold). The final
    #   uptick 12->13 lifts RSI above oversold on the last position (exit) -> BUY.
    #   The final short/long SMAs still both fall (short_last < long_last with
    #   short_prev < long_prev), so no SMA cross fires and RSI decides.
    strat = PredictiveStrategy(
        short_period=2, long_period=3, rsi_period=2, rsi_oversold=30, rsi_overbought=70
    )
    bars = _bars([20, 18, 16, 14, 12, 13])
    sig = strat.generate(bars)
    assert sig.action is Action.BUY
    assert "RSI" in sig.reason


# --- (c) insufficient bars ------------------------------------------------


def test_insufficient_bars_returns_hold():
    # required = max(long_period=3, rsi_period+1=3) = 3; 2 bars -> HOLD.
    strat = PredictiveStrategy(
        short_period=2, long_period=3, rsi_period=2, rsi_oversold=30, rsi_overbought=70
    )
    sig = strat.generate(_bars([10, 11]))
    assert sig.action is Action.HOLD
    assert "insufficient" in sig.reason


def test_empty_bars_returns_hold():
    strat = PredictiveStrategy(short_period=2, long_period=3, rsi_period=2)
    sig = strat.generate([])
    assert sig.action is Action.HOLD


# --- (d) invalid parameters ----------------------------------------------


def test_short_ge_long_raises():
    with pytest.raises(ValueError):
        PredictiveStrategy(short_period=5, long_period=5)
    with pytest.raises(ValueError):
        PredictiveStrategy(short_period=6, long_period=5)


def test_period_zero_raises():
    with pytest.raises(ValueError):
        PredictiveStrategy(short_period=0, long_period=5)
    with pytest.raises(ValueError):
        PredictiveStrategy(short_period=2, long_period=3, rsi_period=0)


def test_period_above_max_raises():
    with pytest.raises(ValueError):
        PredictiveStrategy(short_period=2, long_period=PERIOD_MAX + 1)
    with pytest.raises(ValueError):
        PredictiveStrategy(short_period=2, long_period=3, rsi_period=PERIOD_MAX + 1)


def test_oversold_ge_overbought_raises():
    with pytest.raises(ValueError):
        PredictiveStrategy(rsi_oversold=70, rsi_overbought=70)
    with pytest.raises(ValueError):
        PredictiveStrategy(rsi_oversold=80, rsi_overbought=70)


def test_overbought_ge_hundred_raises():
    with pytest.raises(ValueError):
        PredictiveStrategy(rsi_oversold=30, rsi_overbought=100)


def test_oversold_le_zero_raises():
    with pytest.raises(ValueError):
        PredictiveStrategy(rsi_oversold=0, rsi_overbought=70)


def test_defaults_are_valid():
    strat = PredictiveStrategy()
    assert strat.rsi_oversold == 30
    assert strat.rsi_overbought == 70


def test_period_bounds_inclusive_are_valid():
    strat = PredictiveStrategy(
        short_period=PERIOD_MIN, long_period=PERIOD_MAX, rsi_period=PERIOD_MAX
    )
    assert strat.short_period == PERIOD_MIN
    assert strat.long_period == PERIOD_MAX


# --- (e) determinism ------------------------------------------------------


def test_deterministic_same_input_same_signal():
    strat = PredictiveStrategy(
        short_period=2, long_period=3, rsi_period=2, rsi_oversold=30, rsi_overbought=70
    )
    bars = _bars([10, 10, 10, 8, 14])
    a = strat.generate(bars)
    b = strat.generate(bars)
    assert a.action is b.action
    assert a.reason == b.reason
    assert a.timestamp == b.timestamp


# --- (f) reason names indicator when nothing triggers ---------------------


def test_no_signal_returns_hold_with_reason():
    # A flat series: SMAs equal (no cross) and RSI stays at a neutral/undefined
    # region without crossing thresholds -> HOLD "no signal".
    strat = PredictiveStrategy(
        short_period=2, long_period=3, rsi_period=2, rsi_oversold=30, rsi_overbought=70
    )
    sig = strat.generate(_bars([10, 10, 10, 10, 10]))
    assert sig.action is Action.HOLD
    assert "no signal" in sig.reason


def test_generate_accepts_optional_quote():
    strat = PredictiveStrategy(short_period=2, long_period=3, rsi_period=2)
    bars = _bars([10, 10, 10, 8, 14])
    quote = Quote(timestamp=_BASE_TS, price=Decimal("14"))
    sig = strat.generate(bars, quote)
    assert sig.action is Action.BUY
