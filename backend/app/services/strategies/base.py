"""Common plug-and-play strategy interface and HOLD helper (spec 03-strategy-engine)."""

from datetime import datetime, timezone
from typing import Protocol, Sequence, runtime_checkable

from app.services.data_feed.models import Bar, Quote
from app.services.strategies.signals import Action, Signal


@runtime_checkable
class Strategy(Protocol):
    """Common plug-and-play interface (R1.1).

    generate() receives market data in the single spec-02 format — a sequence of
    Bar (primary input) plus an optional latest Quote — and returns a Signal whose
    action is exactly one of {BUY, SELL, HOLD} (R1.5).
    """

    def generate(self, bars: Sequence[Bar], quote: Quote | None = None) -> Signal: ...


def hold(reason: str, ts: datetime | None = None) -> Signal:
    """Helper to build a HOLD Signal (used for empty/insufficient data, R1.6)."""
    return Signal(action=Action.HOLD, reason=reason, timestamp=ts or datetime.now(timezone.utc))
