"""Pure, deterministic technical indicators over close prices (spec 03, R3.1).

These functions have no side effects, no global state, and no external
numeric dependencies (no numpy/pandas). They operate on ``Decimal`` values and
return one value per window position so callers can compare consecutive
positions (e.g. to detect an SMA crossover).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence


def sma(values: Sequence[Decimal], period: int) -> list[Decimal]:
    """Simple Moving Average over ``values`` (R3.1).

    Averages ``period`` consecutive closes. Returns one SMA value per window
    position: ``len(result) == len(values) - period + 1`` when
    ``len(values) >= period``, else ``[]`` (insufficient data). Deterministic.

    Precondition: ``period >= 1``; otherwise raises ``ValueError``.
    """
    if period < 1:
        raise ValueError(f"sma period must be >= 1, got {period}")

    n = len(values)
    if n < period:
        return []

    period_dec = Decimal(period)
    result: list[Decimal] = []
    # Rolling window sum for determinism and O(n) work.
    window_sum = sum(values[0:period], Decimal(0))
    result.append(window_sum / period_dec)
    for i in range(period, n):
        window_sum += values[i] - values[i - period]
        result.append(window_sum / period_dec)
    return result


def rsi(values: Sequence[Decimal], period: int) -> list[Decimal]:
    """Relative Strength Index over ``values`` (R3.1).

    Classic RSI using average gains/losses over ``period``. Returns one RSI
    value per window position, each within the closed range ``[0, 100]``.
    Returns ``[]`` when there are fewer than ``period + 1`` values. When the
    average loss is zero the value is defined as ``100``. Deterministic.

    Precondition: ``period >= 1``; otherwise raises ``ValueError``.
    """
    if period < 1:
        raise ValueError(f"rsi period must be >= 1, got {period}")

    n = len(values)
    if n < period + 1:
        return []

    hundred = Decimal(100)
    zero = Decimal(0)
    period_dec = Decimal(period)

    # Per-step gains and losses (both non-negative). There are n-1 deltas.
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for i in range(1, n):
        delta = values[i] - values[i - 1]
        if delta > 0:
            gains.append(delta)
            losses.append(zero)
        else:
            gains.append(zero)
            losses.append(-delta)

    result: list[Decimal] = []
    # First value: simple average of the first `period` gains/losses.
    avg_gain = sum(gains[0:period], zero) / period_dec
    avg_loss = sum(losses[0:period], zero) / period_dec
    result.append(_rsi_value(avg_gain, avg_loss, hundred))

    # Subsequent values: Wilder's smoothing over the remaining deltas.
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period_dec - 1) + gains[i]) / period_dec
        avg_loss = (avg_loss * (period_dec - 1) + losses[i]) / period_dec
        result.append(_rsi_value(avg_gain, avg_loss, hundred))

    return result


def _rsi_value(avg_gain: Decimal, avg_loss: Decimal, hundred: Decimal) -> Decimal:
    """Compute a single RSI value, clamped to the closed range ``[0, 100]``."""
    if avg_loss == 0:
        # No losses -> RSI defined as 100 (R3.1).
        return hundred
    rs = avg_gain / avg_loss
    value = hundred - (hundred / (Decimal(1) + rs))
    # Guard against any rounding drift outside the closed range.
    if value < 0:
        return Decimal(0)
    if value > hundred:
        return hundred
    return value
