"""Signal types produced by strategies (spec 03-strategy-engine)."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Action(str, Enum):
    """The decision carried by a Signal — exactly one of these (R1.2)."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Signal:
    """Output of a strategy (R1.2)."""

    action: Action              # one of BUY / SELL / HOLD
    reason: str                 # human-readable explanation (non-empty)
    timestamp: datetime         # when the signal was produced (UTC)
