"""Inline tests for the RandomStrategy (spec 03, task 4).

Covers R2.1, R2.2, R2.4, R2.5, R1.6.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from app.services.data_feed.models import Bar
from app.services.strategies.random_strategy import RandomStrategy
from app.services.strategies.signals import Action

VALID_ACTIONS = {Action.BUY, Action.SELL, Action.HOLD}


def _make_bars(count: int) -> Sequence[Bar]:
    """Build a small deterministic sequence of example Bars."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(count):
        price = Decimal("100") + Decimal(i)
        bars.append(
            Bar(
                timestamp=base + timedelta(minutes=i),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("10"),
            )
        )
    return bars


def test_same_seed_produces_same_action_sequence() -> None:
    """(a) Same seed -> identical action sequence over the same invocations (R2.5)."""
    bars = _make_bars(3)
    n = 50

    a = RandomStrategy(42)
    b = RandomStrategy(42)

    seq_a = [a.generate(bars).action for _ in range(n)]
    seq_b = [b.generate(bars).action for _ in range(n)]

    assert seq_a == seq_b


def test_all_three_actions_reachable_with_fixed_seed() -> None:
    """(b) With a fixed seed, all of BUY/SELL/HOLD appear in N invocations (R2.2)."""
    bars = _make_bars(3)
    strat = RandomStrategy(42)

    actions = {strat.generate(bars).action for _ in range(50)}

    assert actions == VALID_ACTIONS


def test_reason_mentions_random() -> None:
    """(c) The reason metadata indicates randomness (R2.4)."""
    bars = _make_bars(3)
    strat = RandomStrategy(42)

    signal = strat.generate(bars)

    assert "random" in signal.reason.lower()


def test_no_market_data_yields_hold() -> None:
    """(d) No bars and no quote -> HOLD (R1.6)."""
    strat = RandomStrategy(42)

    signal = strat.generate([], quote=None)

    assert signal.action is Action.HOLD


def test_every_signal_has_valid_action() -> None:
    """(e) Every emitted signal carries an action in {BUY, SELL, HOLD} (R2.1)."""
    bars = _make_bars(3)
    strat = RandomStrategy(7)

    for _ in range(50):
        assert strat.generate(bars).action in VALID_ACTIONS
