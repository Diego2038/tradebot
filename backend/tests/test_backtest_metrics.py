"""Tests for the pure backtest metric functions (spec 05-backtest-engine, Task 3).

Covers ``total_return``, ``win_rate``, and ``max_drawdown``: their defining
formulas, the 6-decimal rounding, and the edge/degenerate cases (empty inputs,
non-decreasing curves, zero-trade runs).

Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7
"""

from decimal import Decimal

from app.services.backtest.constants import METRIC_DECIMALS
from app.services.backtest.metrics import max_drawdown, total_return, win_rate


def _dp(value: Decimal) -> int:
    """Number of fractional decimal places carried by ``value``."""

    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) else 0


# --- total_return ---------------------------------------------------------


def test_total_return_matches_formula() -> None:
    # (end - start) / start = (110000 - 100000) / 100000 = 0.1 (R2.3).
    assert total_return(Decimal("100000"), Decimal("110000")) == Decimal("0.100000")


def test_total_return_can_be_negative_down_to_minus_one() -> None:
    # A wipeout to zero equity yields exactly -1 (R2.3).
    assert total_return(Decimal("100000"), Decimal("0")) == Decimal("-1.000000")


def test_total_return_rounded_to_six_decimals() -> None:
    # 1/3 of the start equity -> 0.333333... rounded to 6 dp (R2.6).
    result = total_return(Decimal("3"), Decimal("4"))
    assert result == Decimal("0.333333")
    assert _dp(result) == METRIC_DECIMALS


# --- win_rate -------------------------------------------------------------


def test_win_rate_all_positive_is_one() -> None:
    # Every profit strictly > 0 -> 1 (R2.4).
    assert win_rate([Decimal("5"), Decimal("1"), Decimal("0.01")]) == Decimal("1.000000")


def test_win_rate_empty_is_zero() -> None:
    # No completed trades -> 0 (R2.7).
    assert win_rate([]) == Decimal("0")


def test_win_rate_within_unit_interval() -> None:
    # 1 win out of 3 (zero and negative do not count) -> 0.333333, in [0, 1] (R2.4).
    result = win_rate([Decimal("10"), Decimal("0"), Decimal("-4")])
    assert result == Decimal("0.333333")
    assert Decimal("0") <= result <= Decimal("1")
    assert _dp(result) == METRIC_DECIMALS


# --- max_drawdown ---------------------------------------------------------


def test_max_drawdown_non_decreasing_curve_is_zero() -> None:
    # Equity never declines from a prior peak -> 0 (R2.5).
    curve = [Decimal("100"), Decimal("100"), Decimal("150"), Decimal("150")]
    assert max_drawdown(curve) == Decimal("0")


def test_max_drawdown_empty_curve_is_zero() -> None:
    # Empty curve -> 0 (R2.7).
    assert max_drawdown([]) == Decimal("0")


def test_max_drawdown_known_peak_to_trough() -> None:
    # Peak 200 -> trough 150 gives the largest decline: (200 - 150) / 200 = 0.25 (R2.5).
    curve = [Decimal("100"), Decimal("200"), Decimal("150"), Decimal("180")]
    result = max_drawdown(curve)
    assert result == Decimal("0.250000")
    assert Decimal("0") <= result <= Decimal("1")
    assert _dp(result) == METRIC_DECIMALS
