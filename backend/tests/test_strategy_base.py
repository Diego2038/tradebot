"""Inline tests for the Strategy interface and HOLD helper (spec 03, task 2)."""

from datetime import datetime, timezone
from typing import Sequence

from app.services.data_feed.models import Bar, Quote
from app.services.strategies.base import Strategy, hold
from app.services.strategies.signals import Action, Signal


def test_hold_returns_hold_signal_with_tz_aware_timestamp() -> None:
    signal = hold("x")

    assert isinstance(signal, Signal)
    assert signal.action is Action.HOLD
    assert signal.reason == "x"
    # timestamp must be timezone-aware (UTC).
    assert signal.timestamp.tzinfo is not None
    assert signal.timestamp.utcoffset() == timezone.utc.utcoffset(None)


def test_hold_uses_provided_timestamp() -> None:
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    signal = hold("insufficient data", ts=ts)

    assert signal.action is Action.HOLD
    assert signal.timestamp == ts


def test_dummy_strategy_is_recognized_via_runtime_checkable() -> None:
    class DummyStrategy:
        def generate(self, bars: Sequence[Bar], quote: Quote | None = None) -> Signal:
            return hold("dummy")

    assert isinstance(DummyStrategy(), Strategy)


def test_object_without_generate_is_not_a_strategy() -> None:
    class NotAStrategy:
        pass

    assert not isinstance(NotAStrategy(), Strategy)
