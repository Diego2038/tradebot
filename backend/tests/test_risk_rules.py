"""Unit tests for the pure risk rule helpers (spec 06-risk-manager, task 3).

Covers ``effective_allowed_max``, ``check_lot_size`` and ``check_daily_loss``.
Imports ONLY ``app.services.execution.risk`` for the port type, keeping the
tests free of the Alpaca SDK.

Requirements: 1.4, 1.5, 2.3, 2.4, 2.5, 2.6, 2.7.
"""

from decimal import Decimal

from app.services.risk.rules import (
    REASON_DAILY_LOSS,
    REASON_EQUITY_UNAVAILABLE,
    REASON_INVALID_QTY,
    REASON_MAX_LOT,
    check_daily_loss,
    check_lot_size,
    effective_allowed_max,
)


# --------------------------------------------------------------------------- #
# effective_allowed_max
# --------------------------------------------------------------------------- #

def test_effective_allowed_max_no_pct_returns_max_qty():
    assert effective_allowed_max(Decimal("2"), None, None) == Decimal("2")
    # equity is ignored when no pct is configured.
    assert effective_allowed_max(Decimal("2"), None, Decimal("1000")) == Decimal("2")


def test_effective_allowed_max_equity_derived_is_lower():
    # equity * pct / 100 = 1000 * 10 / 100 = 100, which is < max_qty (500).
    result = effective_allowed_max(Decimal("500"), Decimal("10"), Decimal("1000"))
    assert result == Decimal("100")


def test_effective_allowed_max_max_qty_is_lower():
    # equity * pct / 100 = 1000 * 50 / 100 = 500, which is > max_qty (3).
    result = effective_allowed_max(Decimal("3"), Decimal("50"), Decimal("1000"))
    assert result == Decimal("3")


def test_effective_allowed_max_equity_none_returns_none():
    assert effective_allowed_max(Decimal("5"), Decimal("10"), None) is None


def test_effective_allowed_max_equity_non_positive_returns_none():
    assert effective_allowed_max(Decimal("5"), Decimal("10"), Decimal("0")) is None
    assert effective_allowed_max(Decimal("5"), Decimal("10"), Decimal("-1")) is None


# --------------------------------------------------------------------------- #
# check_lot_size
# --------------------------------------------------------------------------- #

def test_check_lot_size_within_max_returns_none():
    assert check_lot_size(Decimal("1"), Decimal("2"), None, None) is None
    # exactly at the max is allowed.
    assert check_lot_size(Decimal("2"), Decimal("2"), None, None) is None


def test_check_lot_size_above_max_blocks():
    decision = check_lot_size(Decimal("3"), Decimal("2"), None, None)
    assert decision is not None
    assert decision.approved is False
    assert decision.reason == REASON_MAX_LOT


def test_check_lot_size_invalid_qty_blocks_without_max_comparison():
    # qty <= 0 must be rejected as invalid, even if it would be within the max.
    for bad_qty in (Decimal("0"), Decimal("-5")):
        decision = check_lot_size(bad_qty, Decimal("100"), None, None)
        assert decision is not None
        assert decision.approved is False
        assert decision.reason == REASON_INVALID_QTY


def test_check_lot_size_equity_required_but_unavailable_blocks():
    decision = check_lot_size(Decimal("1"), Decimal("5"), Decimal("10"), None)
    assert decision is not None
    assert decision.approved is False
    assert decision.reason == REASON_EQUITY_UNAVAILABLE


def test_check_lot_size_equity_derived_max_enforced():
    # allowed = min(500, 1000 * 10 / 100) = 100; qty 150 exceeds it.
    decision = check_lot_size(Decimal("150"), Decimal("500"), Decimal("10"), Decimal("1000"))
    assert decision is not None
    assert decision.approved is False
    assert decision.reason == REASON_MAX_LOT
    # qty 100 is exactly the equity-derived max -> allowed.
    assert check_lot_size(Decimal("100"), Decimal("500"), Decimal("10"), Decimal("1000")) is None


# --------------------------------------------------------------------------- #
# check_daily_loss
# --------------------------------------------------------------------------- #

def test_check_daily_loss_below_limit_returns_none():
    assert check_daily_loss(Decimal("50"), Decimal("100")) is None


def test_check_daily_loss_at_limit_blocks():
    decision = check_daily_loss(Decimal("100"), Decimal("100"))
    assert decision is not None
    assert decision.approved is False
    assert decision.reason == REASON_DAILY_LOSS


def test_check_daily_loss_above_limit_blocks():
    decision = check_daily_loss(Decimal("150"), Decimal("100"))
    assert decision is not None
    assert decision.approved is False
    assert decision.reason == REASON_DAILY_LOSS
