"""Pure metric functions for the backtest engine (spec 05-backtest-engine, Task 3).

Deterministic, side-effect-free functions over ``Decimal`` computing the three
reported fractional metrics — ``total_return``, ``win_rate``, and
``max_drawdown`` — each rounded to ``METRIC_DECIMALS`` decimal places (R2.6).

No SDK, no global state, no I/O; all money math is ``Decimal`` (consistent with
specs 01/02). These functions are the sole owners of metric arithmetic so the
``BacktestEngine`` stays thin (R2.1, R2.3, R2.4, R2.5).
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal

from app.services.backtest.constants import METRIC_DECIMALS

# Quantization target: METRIC_DECIMALS places to the right of the point (R2.6).
_QUANTUM: Decimal = Decimal(1).scaleb(-METRIC_DECIMALS)


def _round(value: Decimal) -> Decimal:
    """Round a fraction to ``METRIC_DECIMALS`` places using banker's rounding (R2.6)."""

    return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def total_return(start_equity: Decimal, end_equity: Decimal) -> Decimal:
    """Relative change of equity, rounded to 6 dp (R2.3, R2.6).

    Returns ``(end_equity - start_equity) / start_equity``. With the fixed
    positive ``STARTING_EQUITY`` and simulated equity that can fall to zero but
    not below, the result is always ``>= -1``. Precondition: ``start_equity > 0``.
    """

    return _round((end_equity - start_equity) / start_equity)


def win_rate(realized_profits: Sequence[Decimal]) -> Decimal:
    """Fraction of completed round trips with profit strictly ``> 0`` (R2.4, R2.6).

    Returns ``count(p for p in realized_profits if p > 0) / len(realized_profits)``,
    yielding a value in ``[0, 1]``. Returns ``Decimal("0")`` when the sequence is
    empty (Trade_Count == 0, R2.7).
    """

    total = len(realized_profits)
    if total == 0:
        return Decimal("0")

    wins = sum(1 for profit in realized_profits if profit > 0)
    return _round(Decimal(wins) / Decimal(total))


def max_drawdown(equity_curve: Sequence[Decimal]) -> Decimal:
    """Largest peak-to-trough decline over the curve / the peak (R2.5, R2.6).

    Tracks the running peak; for each point computes ``(peak - value) / peak`` and
    returns the maximum, yielding a value in ``[0, 1]``. Returns ``Decimal("0")``
    when equity never declines from a prior peak or when the curve is empty (R2.7).
    """

    peak: Decimal | None = None
    worst = Decimal("0")
    for value in equity_curve:
        if peak is None or value > peak:
            peak = value
        # Only measure declines from a positive peak; a non-positive peak cannot
        # produce a meaningful in-range drawdown fraction.
        if peak > 0:
            decline = (peak - value) / peak
            if decline > worst:
                worst = decline

    return _round(worst)
