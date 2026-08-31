"""Risk Manager configuration errors (spec ``06-risk-manager``)."""

from __future__ import annotations


class RiskConfigError(ValueError):
    """Raised at ``RiskManager`` construction when configuration is invalid.

    Subclasses :class:`ValueError` so callers can catch either. It signals an
    invalid limit or percentage supplied to ``RiskManager`` (``daily_loss_limit
    <= 0`` (R1.2), ``max_qty <= 0`` (R2.1), or ``max_equity_pct`` outside
    ``(0, 100]`` (R2.2)).

    It is **never** raised by ``evaluate`` -- rule violations are returned as
    ``RiskDecision(approved=False, ...)``, never as exceptions (R3.6). A
    constructed ``RiskManager`` is therefore always in a valid state.
    """
