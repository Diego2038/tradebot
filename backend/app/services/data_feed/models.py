"""Single normalization format for market data.

The only market-data shapes any consumer sees. Implemented as immutable
dataclasses (pure data, no SDK types) so downstream components never depend on
Alpaca's shapes (R3.1).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Bar:
    """SDK-independent OHLCV candle — exactly these fields (R3.1)."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class Quote:
    """SDK-independent tick/quote — exactly these fields (R3.1)."""

    timestamp: datetime
    price: Decimal
