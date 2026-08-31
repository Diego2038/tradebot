"""Unit / example tests for ``RiskManager`` (spec 06-risk-manager, task 4).

Covers configuration validation, the fixed rule order in ``evaluate``, the daily
loss limit with UTC-day reset, determinism, equity-unavailable handling, and the
structural conformance to spec 04's ``RiskPort``.

Imports ONLY ``app.services.execution.risk`` for the port types, keeping the
tests free of the Alpaca SDK.

Requirements: 1.1, 1.2, 1.3, 1.6, 1.8, 2.1, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.execution.risk import ProposedOrder, RiskDecision, RiskPort
from app.services.risk import RiskConfigError, RiskManager
from app.services.risk.rules import (
    REASON_DAILY_LOSS,
    REASON_EQUITY_UNAVAILABLE,
    REASON_INVALID_QTY,
    REASON_MAX_LOT,
)


class _StubEquityProvider:
    """Minimal ``EquityProvider`` stub returning a configured ``Decimal | None``."""

    def __init__(self, equity: Decimal | None) -> None:
        self._equity = equity

    def get_equity(self) -> Decimal | None:
        return self._equity


def _order(qty: Decimal, side: str = "buy") -> ProposedOrder:
    return ProposedOrder(symbol="BTC/USD", side=side, qty=qty)


# --------------------------------------------------------------------------- #
# (a) configuration validation
# --------------------------------------------------------------------------- #

def test_invalid_daily_loss_limit_raises():
    for bad in (Decimal("0"), Decimal("-1")):
        with pytest.raises(RiskConfigError):
            RiskManager(daily_loss_limit=bad, max_qty=Decimal("1"))


def test_invalid_max_qty_raises():
    for bad in (Decimal("0"), Decimal("-2")):
        with pytest.raises(RiskConfigError):
            RiskManager(daily_loss_limit=Decimal("100"), max_qty=bad)


def test_invalid_max_equity_pct_raises():
    with pytest.raises(RiskConfigError):
        RiskManager(
            daily_loss_limit=Decimal("100"),
            max_qty=Decimal("1"),
            max_equity_pct=Decimal("0"),
        )
    with pytest.raises(RiskConfigError):
        RiskManager(
            daily_loss_limit=Decimal("100"),
            max_qty=Decimal("1"),
            max_equity_pct=Decimal("101"),
        )


def test_valid_config_constructs_ok():
    rm = RiskManager(
        daily_loss_limit=Decimal("100"),
        max_qty=Decimal("5"),
        max_equity_pct=Decimal("50"),
        equity_provider=_StubEquityProvider(Decimal("1000")),
    )
    assert rm.daily_loss_limit == Decimal("100")
    assert rm.max_qty == Decimal("5")
    assert rm.max_equity_pct == Decimal("50")


# --------------------------------------------------------------------------- #
# (b) approves within limits
# --------------------------------------------------------------------------- #

def test_evaluate_approves_within_limits():
    rm = RiskManager(daily_loss_limit=Decimal("100"), max_qty=Decimal("5"))
    decision = rm.evaluate(_order(Decimal("2")))
    assert decision == RiskDecision(approved=True, reason="")


# --------------------------------------------------------------------------- #
# (c) lot-size rule
# --------------------------------------------------------------------------- #

def test_evaluate_blocks_qty_above_max():
    rm = RiskManager(daily_loss_limit=Decimal("100"), max_qty=Decimal("5"))
    decision = rm.evaluate(_order(Decimal("6")))
    assert decision.approved is False
    assert decision.reason == REASON_MAX_LOT


def test_evaluate_blocks_invalid_qty():
    rm = RiskManager(daily_loss_limit=Decimal("100"), max_qty=Decimal("5"))
    for bad in (Decimal("0"), Decimal("-3")):
        decision = rm.evaluate(_order(bad))
        assert decision.approved is False
        assert decision.reason == REASON_INVALID_QTY


# --------------------------------------------------------------------------- #
# (d) daily-loss rule
# --------------------------------------------------------------------------- #

def test_evaluate_blocks_when_daily_loss_reached():
    rm = RiskManager(daily_loss_limit=Decimal("100"), max_qty=Decimal("5"))
    rm.record_realized_pnl(Decimal("-100"))  # loss raises accumulated loss to 100
    decision = rm.evaluate(_order(Decimal("1")))
    assert decision.approved is False
    assert decision.reason == REASON_DAILY_LOSS


# --------------------------------------------------------------------------- #
# (e) UTC-day reset
# --------------------------------------------------------------------------- #

def test_record_realized_pnl_resets_on_utc_day_change():
    rm = RiskManager(daily_loss_limit=Decimal("100"), max_qty=Decimal("5"))
    day1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    day2 = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)

    # Day 1: a loss of 200 -> accumulated loss capped at... note there is no cap
    # on accumulated_loss; it becomes 200 (>= limit).
    rm.record_realized_pnl(Decimal("-200"), at=day1)
    assert rm._accumulated_loss == Decimal("200")

    # Day 2: the day changed -> reset to zero before applying the (0) amount.
    rm.record_realized_pnl(Decimal("0"), at=day2)
    assert rm._accumulated_loss == Decimal("0")
    assert rm._current_utc_day == day2.date()


def test_profit_reduces_loss_not_below_zero():
    rm = RiskManager(daily_loss_limit=Decimal("100"), max_qty=Decimal("5"))
    at = datetime(2024, 3, 1, 9, 0, tzinfo=timezone.utc)
    rm.record_realized_pnl(Decimal("-50"), at=at)
    assert rm._accumulated_loss == Decimal("50")
    # A big profit lowers the loss but never below zero.
    rm.record_realized_pnl(Decimal("500"), at=at)
    assert rm._accumulated_loss == Decimal("0")


# --------------------------------------------------------------------------- #
# (f) determinism
# --------------------------------------------------------------------------- #

def test_evaluate_is_deterministic_for_same_state_and_order():
    rm = RiskManager(daily_loss_limit=Decimal("100"), max_qty=Decimal("5"))
    order = _order(Decimal("2"))
    first = rm.evaluate(order)
    second = rm.evaluate(order)
    assert first == second


# --------------------------------------------------------------------------- #
# (g) RiskPort conformance
# --------------------------------------------------------------------------- #

def test_risk_manager_satisfies_risk_port():
    rm = RiskManager(daily_loss_limit=Decimal("100"), max_qty=Decimal("5"))
    assert isinstance(rm, RiskPort)


# --------------------------------------------------------------------------- #
# (h) equity-based limit with unavailable equity
# --------------------------------------------------------------------------- #

def test_evaluate_blocks_when_equity_unavailable():
    rm = RiskManager(
        daily_loss_limit=Decimal("100"),
        max_qty=Decimal("5"),
        max_equity_pct=Decimal("10"),
        equity_provider=_StubEquityProvider(None),
    )
    decision = rm.evaluate(_order(Decimal("1")))
    assert decision.approved is False
    assert decision.reason == REASON_EQUITY_UNAVAILABLE
