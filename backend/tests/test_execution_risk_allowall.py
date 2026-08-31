"""Tests for the pass-through AllowAllRiskManager (spec 04, Task 2).

Validates: Requirements 5.1, 5.2
"""

from decimal import Decimal

from app.services.execution.risk import (
    AllowAllRiskManager,
    ProposedOrder,
    RiskPort,
)


def test_allow_all_approves_proposed_order() -> None:
    manager = AllowAllRiskManager()
    decision = manager.evaluate(ProposedOrder("BTC/USD", "buy", Decimal("0.001")))

    assert decision.approved is True
    assert decision.reason == "allow-all pass-through"


def test_allow_all_satisfies_risk_port_protocol() -> None:
    # RiskPort is runtime_checkable, so structural conformance is enough.
    assert isinstance(AllowAllRiskManager(), RiskPort)
