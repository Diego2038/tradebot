"""The concrete ``RiskManager`` — spec ``06-risk-manager``'s real ``RiskPort``.

``RiskManager`` is the single pre-order gate that spec ``04-order-execution``
consults before sending any order to Alpaca (paper trading only). It enforces
two protection rules:

- the configurable **daily loss limit** (R1), and
- the configurable **maximum lot size** (R2),

and answers, for every proposed order, a single yes/no :class:`RiskDecision`
with a reason (R3).

The port types (:class:`ProposedOrder`, :class:`RiskDecision`, :class:`RiskPort`)
are **owned by spec 04** and imported from ``app.services.execution.risk`` — they
are never redefined here (R3.1). Because ``RiskPort`` is ``@runtime_checkable``,
``isinstance(RiskManager(...), RiskPort)`` holds structurally, with no explicit
inheritance.

Determinism and totality: ``evaluate`` reads state but never mutates it, so
identical (state, order) inputs always return identical decisions (R3.5), and it
**never raises for a rule violation** (R3.6). The only exceptions come from
**invalid configuration at construction** (:class:`RiskConfigError`, R1.2/R2.1).

Requirements: 1.1, 1.2, 1.3, 1.6, 1.8, 2.1, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app.services.execution.risk import ProposedOrder, RiskDecision  # reused (R3.1)
from app.services.risk import rules
from app.services.risk.equity import EquityProvider
from app.services.risk.errors import RiskConfigError


class RiskManager:
    """Real ``RiskPort`` implementation: the single pre-order gate (R3.1).

    Enforces the daily loss limit (R1) and the maximum lot size (R2). Deterministic
    and total: :meth:`evaluate` never raises for a rule violation (R3.6); only
    invalid configuration raises, at construction time (R1.2, R2.1).
    """

    def __init__(
        self,
        daily_loss_limit: Decimal,
        max_qty: Decimal,
        max_equity_pct: Decimal | None = None,
        equity_provider: EquityProvider | None = None,
        publisher: object | None = None,
    ) -> None:
        """Validate configuration and initialize per-UTC-day state.

        Raises :class:`RiskConfigError` (a ``ValueError`` subclass) when:

        - ``daily_loss_limit <= 0`` (R1.2),
        - ``max_qty <= 0`` (R2.1),
        - ``max_equity_pct`` is set and not in ``(0, 100]`` (R2.2).

        Initializes ``_accumulated_loss = 0`` for the current UTC day (R1.3).

        Note on ``publisher`` (anti-double-event decision): spec 04's executor
        already emits exactly one ``RISK_BLOCK`` event whenever ``evaluate``
        returns ``approved=False`` (spec 04, R5.3). To avoid double emission,
        ``RiskManager`` does **not** publish events in the normal flow; the
        ``publisher`` parameter is reserved (accepted and stored) but is not used
        to emit on the executor-driven path (R1.7). The authoritative source of
        ``RISK_BLOCK`` is the executor.
        """
        if daily_loss_limit <= 0:
            raise RiskConfigError(
                f"daily_loss_limit must be > 0, got {daily_loss_limit!r}"
            )
        if max_qty <= 0:
            raise RiskConfigError(f"max_qty must be > 0, got {max_qty!r}")
        if max_equity_pct is not None and not (0 < max_equity_pct <= 100):
            raise RiskConfigError(
                f"max_equity_pct must be in (0, 100], got {max_equity_pct!r}"
            )

        # Immutable configuration.
        self.daily_loss_limit: Decimal = daily_loss_limit
        self.max_qty: Decimal = max_qty
        self.max_equity_pct: Decimal | None = max_equity_pct
        self._equity_provider: EquityProvider | None = equity_provider
        # Reserved for non-executor flows; never used to emit on the normal path.
        self._publisher: object | None = publisher

        # Private per-UTC-day state (R1.3, R1.6).
        self._current_utc_day: date = datetime.now(timezone.utc).date()
        self._accumulated_loss: Decimal = Decimal(0)

    @staticmethod
    def _utc_date(at: datetime | None) -> date:
        """Derive the UTC calendar day from ``at`` (defaults to now, UTC).

        A timezone-aware ``at`` is converted to UTC; a naive ``at`` is assumed to
        already be in UTC.
        """
        if at is None:
            return datetime.now(timezone.utc).date()
        if at.tzinfo is not None:
            return at.astimezone(timezone.utc).date()
        return at.date()

    def record_realized_pnl(self, amount: Decimal, at: datetime | None = None) -> None:
        """Report realized P&L to the System (R1.3, R1.6).

        ``at`` defaults to the current UTC time. If ``at``'s UTC date differs from
        the stored day, the accumulated loss is reset to zero **first** (R1.6), then
        this amount is applied.

        Convention: a **loss** is a negative ``amount`` and **increases** the day's
        accumulated loss; a **profit** is a positive ``amount`` and **reduces** it
        but never below zero. This is implemented as
        ``accumulated_loss = max(0, accumulated_loss - amount)``: with a negative
        ``amount``, ``-amount`` is positive and raises the loss; with a positive
        ``amount``, it lowers the loss down to (but not below) zero.
        """
        effective_day = self._utc_date(at)
        if effective_day != self._current_utc_day:
            self._accumulated_loss = Decimal(0)
            self._current_utc_day = effective_day

        self._accumulated_loss = max(Decimal(0), self._accumulated_loss - amount)

    def _roll_day_if_stale(self) -> None:
        """Reset the accumulated loss when the stored UTC day is stale (R1.6).

        Keeps the daily-loss block referring to the *current* UTC day. Idempotent:
        rolling to today when already on today is a no-op.
        """
        today = datetime.now(timezone.utc).date()
        if today != self._current_utc_day:
            self._accumulated_loss = Decimal(0)
            self._current_utc_day = today

    def evaluate(self, proposed_order: ProposedOrder) -> RiskDecision:
        """The single gate spec 04 consults (R3.1-R3.6).

        Treats ``proposed_order`` as an ``Opening_Order`` (``ProposedOrder`` carries
        no open/close flag; protective closes bypass risk in spec 04, so the
        daily-loss rule only reaches openings — R1.8 by construction). Applies the
        rules in a fixed order — quantity validity -> lot size -> daily loss — and
        the **first** violation wins, its reason identifying the rule (R3.4).
        Returns ``approved=True`` only if no rule is violated (R3.3).

        Never raises for a violation (R3.6). It reads state but does not mutate the
        accumulated loss for the current day, so repeated calls with the same state
        and order return identical decisions (R3.5). Rolling a stale UTC day to
        today (R1.6) is idempotent and does not affect determinism for a fixed
        state.
        """
        self._roll_day_if_stale()

        # Fetch equity only when the equity-based limit is configured; otherwise
        # equity stays None and the lot rule uses max_qty directly.
        equity: Decimal | None = None
        if self.max_equity_pct is not None and self._equity_provider is not None:
            equity = self._equity_provider.get_equity()

        # Fixed order — first violation wins.
        decision = rules.check_lot_size(
            proposed_order.qty, self.max_qty, self.max_equity_pct, equity
        )
        if decision is not None:
            return decision

        decision = rules.check_daily_loss(self._accumulated_loss, self.daily_loss_limit)
        if decision is not None:
            return decision

        return RiskDecision(approved=True, reason="")
