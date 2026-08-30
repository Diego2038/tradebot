"""Inline tests for the StrategyEngine registry and default wiring (spec 03, task 6).

Covers:
- (a) build_default_engine()'s default active mode is deterministic ("random")
      and get_active_name() returns it.
- (b) set_active("predictive") switches the active strategy and generate delegates
      to PredictiveStrategy (insufficient bars -> HOLD with a "predictive: ..." reason).
- (c) set_active("nope") raises UnknownStrategyError and get_active_name() is unchanged.
- (d) generate delegates to the active strategy ("random" over some bars yields a
      valid Signal with action in {BUY, SELL, HOLD}).
- (e) register adds a strategy that can then be selected by name.

Bars are constructed directly from spec-02 models; the engine has no external
dependencies, so no mocks are needed. Uses ``pytest``.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.data_feed.models import Bar, Quote
from app.services.strategies import (
    Action,
    Signal,
    StrategyEngine,
    UnknownStrategyError,
    build_default_engine,
)
from app.services.strategies.base import hold
from app.services.strategies.registry import DEFAULT_MODE


_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(closes):
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


# --- (a) deterministic default active mode --------------------------------


def test_default_active_mode_is_deterministic():
    engine = build_default_engine()
    assert engine.get_active_name() == DEFAULT_MODE == "random"


def test_default_active_mode_repeatable_across_builds():
    assert build_default_engine().get_active_name() == "random"
    assert build_default_engine().get_active_name() == "random"


# --- (b) switch to predictive and delegate --------------------------------


def test_set_active_predictive_delegates_to_predictive():
    engine = build_default_engine()
    engine.set_active("predictive")
    assert engine.get_active_name() == "predictive"

    # Insufficient bars -> PredictiveStrategy returns HOLD with a "predictive:" reason.
    sig = engine.generate(_bars([10, 11]))
    assert sig.action is Action.HOLD
    assert sig.reason.startswith("predictive:")


# --- (c) unknown name raises, active unchanged ----------------------------


def test_set_active_unknown_raises_and_leaves_active_unchanged():
    engine = build_default_engine()
    before = engine.get_active_name()
    with pytest.raises(UnknownStrategyError):
        engine.set_active("nope")
    assert engine.get_active_name() == before


def test_set_active_unknown_after_switch_keeps_previous_active():
    engine = build_default_engine()
    engine.set_active("predictive")
    with pytest.raises(UnknownStrategyError):
        engine.set_active("does-not-exist")
    assert engine.get_active_name() == "predictive"


# --- (d) generate delegates to the active strategy ------------------------


def test_generate_delegates_to_active_strategy():
    engine = build_default_engine()  # active = random
    sig = engine.generate(_bars([10, 11, 12, 13, 14]))
    assert isinstance(sig, Signal)
    assert sig.action in {Action.BUY, Action.SELL, Action.HOLD}
    assert sig.reason  # non-empty
    assert sig.timestamp is not None


def test_generate_random_no_data_is_hold():
    engine = build_default_engine()
    sig = engine.generate([], None)
    assert sig.action is Action.HOLD


# --- (e) register + select a custom strategy ------------------------------


class _AlwaysBuy:
    """Minimal Strategy conforming to the protocol for the registration test."""

    def generate(self, bars, quote=None) -> Signal:
        return Signal(action=Action.BUY, reason="always: buy", timestamp=_BASE_TS)


def test_register_and_select_custom_strategy():
    engine = build_default_engine()
    engine.register("always_buy", _AlwaysBuy())
    engine.set_active("always_buy")
    assert engine.get_active_name() == "always_buy"
    sig = engine.generate(_bars([10, 11]))
    assert sig.action is Action.BUY
    assert sig.reason == "always: buy"


# --- extra: unregistered default surfaces a clear error on generate -------


def test_generate_with_unregistered_active_raises():
    engine = StrategyEngine(default="ghost")  # never registered
    assert engine.get_active_name() == "ghost"
    with pytest.raises(UnknownStrategyError):
        engine.generate(_bars([10, 11]))


def test_register_before_setting_active_default():
    # A default registered after construction is usable and stays the active mode.
    engine = StrategyEngine(default="mine")
    engine.register("mine", _AlwaysBuy())
    assert engine.get_active_name() == "mine"
    assert engine.generate([]).action is Action.BUY
