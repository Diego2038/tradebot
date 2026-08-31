"""Backtest replay engine (spec 05-backtest-engine, Task 4).

:class:`BacktestEngine` replays an already-fetched, ordered ``Bar`` sequence through
a spec-03 strategy resolved by name, simulates the resulting trades entirely in
memory (no Alpaca, no I/O), and reports the four summary metrics via the pure
``metrics`` module.

Accounting model (long-only, single open position, round-trip based)
--------------------------------------------------------------------
- Simulated equity starts at ``STARTING_EQUITY`` (Decimal("100000"), R2.2).
- A ``BUY`` while flat OPENS a long position at the bar close (records an entry
  ``SimulatedTrade`` with ``realized_profit=None``); a ``BUY`` while already long
  records a trade but opens no new round trip.
- A ``SELL`` while long CLOSES the position at the bar close (records an exit
  ``SimulatedTrade`` whose ``realized_profit = (exit_price - entry_price) * qty``),
  adds that realized profit to simulated equity, and counts one completed round
  trip; a ``SELL`` while flat records a trade but closes no round trip.
- ``Trade_Count`` counts completed round trips (each closing ``SELL``). ``Win_Rate``
  is the fraction of those round trips with realized profit ``> 0``. The equity
  curve used for ``Max_Drawdown`` starts at ``STARTING_EQUITY`` and appends the
  running equity after each closed round trip. ``Total_Return`` is computed from
  ``STARTING_EQUITY`` to the ending equity.
- ``HOLD`` records no trade and changes nothing (R1.4).

The engine adds no randomness of its own (R4.1). When ``request.seed`` is set it
reseeds the resolved strategy's randomness before replay (R4.2); see
``_seed_strategy`` for the approach chosen given the spec-03 strategies expose no
public reseed hook.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.services.backtest.constants import STARTING_EQUITY
from app.services.backtest.errors import InvalidActionError, InvalidDateRangeError
from app.services.backtest.metrics import max_drawdown, total_return, win_rate
from app.services.backtest.models import BacktestRequest, BacktestResult, SimulatedTrade
from app.services.data_feed.models import Bar
from app.services.strategies.registry import StrategyEngine
from app.services.strategies.signals import Action

_VALID_ACTIONS = frozenset({Action.BUY, Action.SELL, Action.HOLD})


class BacktestEngine:
    """Replay historical bars through a spec-03 strategy and report metrics.

    The engine performs no Alpaca calls and no I/O; it operates only on the bars
    passed to :meth:`run`. It resolves strategies through the SAME spec-03
    :class:`StrategyEngine` used live (R3.3) and invokes them through the unaltered
    ``Strategy`` interface (R3.1).
    """

    def __init__(
        self, strategy_engine: StrategyEngine, qty: Decimal = Decimal("0.001")
    ) -> None:
        """Wire the engine to the shared spec-03 registry.

        ``qty`` is the fixed position size used for each simulated trade.
        """
        self._engine = strategy_engine
        self._qty = qty

    def run(self, request: BacktestRequest, bars: Sequence[Bar]) -> BacktestResult:
        """Run one backtest end to end and return a :class:`BacktestResult`.

        See the module docstring for the accounting model. Raises before or during
        replay for bad requests / actions and returns no result in those cases
        (R1.7, R1.8, R1.9).
        """
        # 1. Validate the Date_Range before touching the strategy (R1.8).
        if (
            request.start is not None
            and request.end is not None
            and request.start > request.end
        ):
            raise InvalidDateRangeError(
                f"invalid Date_Range: start {request.start!r} is later than "
                f"end {request.end!r}"
            )

        # 2. Resolve the strategy by name through the spec-03 registry. An
        #    unregistered name propagates UnknownStrategyError before any replay
        #    (R1.7, R3.3).
        self._engine.set_active(request.strategy_name)

        # If a Seed is provided, initialize the resolved strategy's randomness
        # before replay so the run is reproducible (R4.2). A deterministic strategy
        # simply ignores it (R4.3).
        if request.seed is not None:
            self._seed_strategy(request.strategy_name, request.seed)

        # 3. Empty bars -> complete immediately with everything pinned to zero
        #    (R1.6, R2.7).
        if not bars:
            return BacktestResult(
                total_return=Decimal("0"),
                trade_count=0,
                win_rate=Decimal("0"),
                max_drawdown=Decimal("0"),
                trades=[],
            )

        # 4. Replay in strictly ascending timestamp order, one Signal per bar (R1.1).
        ordered = sorted(bars, key=lambda bar: bar.timestamp)

        trades: list[SimulatedTrade] = []
        realized_profits: list[Decimal] = []
        equity = STARTING_EQUITY
        equity_curve: list[Decimal] = [equity]

        entry_price: Decimal | None = None  # None -> flat; else long entry price

        for i in range(len(ordered)):
            bar = ordered[i]
            signal = self._engine.generate(ordered[: i + 1])
            action = signal.action

            # Out-of-range action -> stop the replay, return no result (R1.9).
            if action not in _VALID_ACTIONS:
                raise InvalidActionError(
                    f"invalid Signal action {action!r} at bar {i} "
                    f"({bar.timestamp!r}); expected one of BUY/SELL/HOLD"
                )

            if action is Action.BUY:
                # Record the entry trade with no Alpaca call (R1.3, R1.5).
                trades.append(
                    SimulatedTrade(
                        side="buy",
                        qty=self._qty,
                        price=bar.close,
                        timestamp=bar.timestamp,
                        reason=signal.reason,
                        realized_profit=None,
                    )
                )
                # Open a long position only when currently flat.
                if entry_price is None:
                    entry_price = bar.close

            elif action is Action.SELL:
                if entry_price is not None:
                    # Close the open long: realize P&L and complete a round trip.
                    realized = (bar.close - entry_price) * self._qty
                    trades.append(
                        SimulatedTrade(
                            side="sell",
                            qty=self._qty,
                            price=bar.close,
                            timestamp=bar.timestamp,
                            reason=signal.reason,
                            realized_profit=realized,
                        )
                    )
                    realized_profits.append(realized)
                    equity += realized
                    equity_curve.append(equity)
                    entry_price = None
                else:
                    # SELL while flat: record the trade but open no round trip.
                    trades.append(
                        SimulatedTrade(
                            side="sell",
                            qty=self._qty,
                            price=bar.close,
                            timestamp=bar.timestamp,
                            reason=signal.reason,
                            realized_profit=None,
                        )
                    )
            # HOLD -> record no trade for that step (R1.4).

        # 5. Compute the metrics over completed round trips / the equity curve.
        trade_count = len(realized_profits)
        if trade_count == 0:
            # Degenerate (no completed round trip): pin all three to zero (R2.7).
            return BacktestResult(
                total_return=Decimal("0"),
                trade_count=0,
                win_rate=Decimal("0"),
                max_drawdown=Decimal("0"),
                trades=trades,
            )

        # 6. Return the four metrics plus the ordered trades (R2.1-R2.6).
        return BacktestResult(
            total_return=total_return(STARTING_EQUITY, equity),
            trade_count=trade_count,
            win_rate=win_rate(realized_profits),
            max_drawdown=max_drawdown(equity_curve),
            trades=trades,
        )

    def _seed_strategy(self, name: str, seed: int) -> None:
        """Initialize the resolved strategy's randomness with ``seed`` (R4.2).

        Approach chosen: the spec-03 strategies (e.g. ``RandomStrategy``) hold a
        private ``random.Random`` in ``self._rng`` seeded via their constructor and
        expose no public reseed hook. To reseed the SAME registered instance the
        engine resolves — without mutating the spec-03 interface — we look the
        instance up in the registry and, when it carries a ``_rng`` Random, call
        ``_rng.seed(seed)``. A deterministic strategy has no such attribute and is
        left untouched (R4.3). This keeps the ``Strategy`` interface unaltered
        (R3.1) while honouring the reproducibility contract (R4.1, R4.4).
        """
        strategy = self._engine._strategies.get(name)
        rng = getattr(strategy, "_rng", None)
        if rng is not None and hasattr(rng, "seed"):
            rng.seed(seed)
