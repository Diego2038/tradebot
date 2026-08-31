"""Pure rule helpers for the Risk Manager (spec 06-risk-manager, task 3).

These helpers are **pure and deterministic**: they take ``Decimal`` inputs and
return a blocking :class:`~app.services.execution.risk.RiskDecision` (or ``None``
when the rule does not block). They hold no global state and perform no I/O, which
makes them cheap to unit- and property-test.

The port type :class:`RiskDecision` is **imported, never redefined** — it is owned
by spec ``04-order-execution`` and lives in ``app.services.execution.risk``.

Requirements: 1.4, 1.5, 2.3, 2.4, 2.5, 2.6, 2.7.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.execution.risk import RiskDecision

# Stable, human-readable reason strings (no secrets).
REASON_INVALID_QTY = "invalid quantity"
REASON_MAX_LOT = "maximum lot size exceeded"
REASON_EQUITY_UNAVAILABLE = "equity-based limit could not be determined"
REASON_DAILY_LOSS = "daily loss limit reached"


def effective_allowed_max(
    max_qty: Decimal,
    max_equity_pct: Decimal | None,
    equity: Decimal | None,
) -> Decimal | None:
    """Return the ``Effective_Allowed_Max`` for the lot-size rule (R2.2).

    - No ``max_equity_pct`` configured -> ``max_qty``.
    - ``max_equity_pct`` configured and ``equity`` available and positive ->
      ``min(max_qty, equity * max_equity_pct / 100)``.
    - ``max_equity_pct`` configured but ``equity`` is ``None`` or ``<= 0`` ->
      ``None`` (signals "cannot determine"; the caller treats this as
      ``approved=False``, R2.7).
    """
    if max_equity_pct is None:
        return max_qty
    if equity is None or equity <= 0:
        return None
    equity_derived = equity * max_equity_pct / Decimal(100)
    return min(max_qty, equity_derived)


def check_lot_size(
    qty: Decimal,
    max_qty: Decimal,
    max_equity_pct: Decimal | None,
    equity: Decimal | None,
) -> RiskDecision | None:
    """Apply the lot-size rule (R2.3-R2.7).

    Returns a blocking :class:`RiskDecision`, or ``None`` when this rule does not
    block:

    - ``qty <= 0`` -> ``approved=False``, :data:`REASON_INVALID_QTY`, **without**
      comparing against the maximum (R2.6).
    - equity required (``max_equity_pct`` set) but unavailable/non-positive ->
      ``approved=False``, :data:`REASON_EQUITY_UNAVAILABLE` (R2.7).
    - ``qty > effective_allowed_max`` -> ``approved=False``,
      :data:`REASON_MAX_LOT` (R2.5).
    - otherwise -> ``None`` (this rule allows the order, R2.4).
    """
    if qty <= 0:
        return RiskDecision(approved=False, reason=REASON_INVALID_QTY)

    allowed_max = effective_allowed_max(max_qty, max_equity_pct, equity)
    if allowed_max is None:
        return RiskDecision(approved=False, reason=REASON_EQUITY_UNAVAILABLE)

    if qty > allowed_max:
        return RiskDecision(approved=False, reason=REASON_MAX_LOT)

    return None


def check_daily_loss(
    accumulated_loss: Decimal,
    daily_loss_limit: Decimal,
) -> RiskDecision | None:
    """Apply the daily-loss rule for an opening order (R1.4, R1.5).

    Returns a blocking :class:`RiskDecision` when
    ``accumulated_loss >= daily_loss_limit`` (R1.4), else ``None`` (R1.5).
    """
    if accumulated_loss >= daily_loss_limit:
        return RiskDecision(approved=False, reason=REASON_DAILY_LOSS)
    return None
