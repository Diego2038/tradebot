"""Pydantic output schemas for the market-data HTTP surface (Task 6).

``BarOut`` is the serialization mirror of the internal :class:`Bar` dataclass
(``services/data_feed/models.py``). It exposes exactly the single normalized
bar fields — timestamp, open, high, low, close, volume — so the REST response
stays SDK-independent (R3.1). The internal domain format remains the ``Bar``
dataclass; this schema is used only at the HTTP boundary for serialization.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class BarOut(BaseModel):
    """Serialized normalized OHLCV candle for the HTTP surface (R1.1, R3.1)."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
