"""Reproducible random baseline strategy (spec 03-strategy-engine, R2)."""

import random
from datetime import datetime, timezone
from typing import Sequence

from app.services.data_feed.models import Bar, Quote
from app.services.strategies.base import hold
from app.services.strategies.signals import Action, Signal


class RandomStrategy:
    """Reproducible baseline strategy (R2)."""

    def __init__(self, seed: int | None = None) -> None:
        """Use a private Random instance so seeding is reproducible (R2.5) and does
        not affect global RNG state. seed=None -> non-reproducible across runs (R2.6)."""
        self._rng = random.Random(seed)

    def generate(self, bars: Sequence[Bar], quote: Quote | None = None) -> Signal:
        """Emit a Signal whose action is randomly one of BUY/SELL/HOLD (R2.1, R2.2).

        With empty/insufficient data still returns a valid Signal; when there is no
        market data at all it returns HOLD (R1.6). The reason indicates randomness
        (R2.4)."""
        if not bars and quote is None:
            return hold("random: no market data")
        action = self._rng.choice([Action.BUY, Action.SELL, Action.HOLD])
        return Signal(
            action=action,
            reason="random: randomly generated signal",
            timestamp=datetime.now(timezone.utc),
        )
