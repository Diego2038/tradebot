"""Inline tests for the pure indicators (spec 03, task 3).

Covers SMA (constant series, insufficient data, a known value), RSI (range
[0, 100], strictly increasing -> high RSI, insufficient data) and determinism
of both functions. Uses ``Decimal`` and ``pytest``.
"""

from decimal import Decimal

import pytest

from app.services.strategies.indicators import rsi, sma


def _dec(values):
    return [Decimal(str(v)) for v in values]


# --- SMA -----------------------------------------------------------------


def test_sma_constant_series_is_constant():
    # (a) SMA of a constant series equals that constant.
    values = _dec([5, 5, 5, 5])
    result = sma(values, period=2)
    assert result == _dec([5, 5, 5])
    assert all(v == Decimal(5) for v in result)


def test_sma_insufficient_data_returns_empty():
    # (b) len(values) < period -> [].
    assert sma(_dec([1, 2]), period=3) == []
    assert sma([], period=1) == []


def test_sma_known_values():
    # (c) [1,2,3,4], period 2 -> [1.5, 2.5, 3.5].
    result = sma(_dec([1, 2, 3, 4]), period=2)
    assert result == _dec(["1.5", "2.5", "3.5"])


def test_sma_length_matches_window_positions():
    values = _dec([1, 2, 3, 4, 5, 6])
    period = 3
    result = sma(values, period)
    assert len(result) == len(values) - period + 1


def test_sma_period_less_than_one_raises():
    with pytest.raises(ValueError):
        sma(_dec([1, 2, 3]), period=0)


def test_sma_deterministic():
    values = _dec(["1.1", "2.2", "3.3", "4.4"])
    assert sma(values, 2) == sma(values, 2)


# --- RSI -----------------------------------------------------------------


@pytest.mark.parametrize(
    "series",
    [
        [1, 2, 3, 4, 5, 6, 7, 8],
        [10, 9, 8, 7, 6, 5, 4, 3],
        [5, 3, 8, 2, 9, 1, 7, 4, 6],
        ["1.5", "1.4", "1.6", "1.55", "1.7", "1.2"],
    ],
)
def test_rsi_values_within_range(series):
    # (d) all RSI values in [0, 100] for several series.
    result = rsi(_dec(series), period=3)
    assert result  # non-empty for these lengths
    for v in result:
        assert Decimal(0) <= v <= Decimal(100)


def test_rsi_strictly_increasing_is_high():
    # (d) strictly increasing series -> RSI high (>= 70) at last position.
    values = _dec([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    result = rsi(values, period=3)
    assert result[-1] >= Decimal(70)


def test_rsi_all_gains_is_hundred():
    values = _dec([1, 2, 3, 4, 5])
    result = rsi(values, period=3)
    # No losses at all -> average loss zero -> RSI 100.
    assert result[-1] == Decimal(100)


def test_rsi_insufficient_data_returns_empty():
    # (d) fewer than period + 1 values -> [].
    assert rsi(_dec([1, 2, 3]), period=3) == []
    assert rsi(_dec([1, 2, 3]), period=4) == []
    assert rsi([], period=1) == []


def test_rsi_period_less_than_one_raises():
    with pytest.raises(ValueError):
        rsi(_dec([1, 2, 3]), period=0)


def test_rsi_deterministic():
    # (e) same input -> same output.
    values = _dec([5, 3, 8, 2, 9, 1, 7, 4, 6, 10])
    assert rsi(values, 4) == rsi(values, 4)
