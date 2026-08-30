"""Strategy engine registry and default wiring (spec 03-strategy-engine, R4).

The :class:`StrategyEngine` is the only stateful object in the package and the
sole entry point for consumers (bot-api, execution). It owns the active mode and
delegates signal generation to the currently selected :class:`Strategy`, so
consumers depend only on the engine and :class:`Signal`, never on a concrete
strategy (R1.3, R4.3).

Failure model:
- Selecting an unregistered name raises :class:`UnknownStrategyError` and leaves
  the active mode unchanged, checking membership *before* mutating any state
  (R1.4, R4.4).
- Data conditions never raise here; concrete strategies map thin/empty data to
  ``HOLD`` (R1.6).
"""

from __future__ import annotations

from typing import Sequence

from app.services.data_feed.models import Bar, Quote
from app.services.strategies.base import Strategy
from app.services.strategies.errors import UnknownStrategyError
from app.services.strategies.predictive_strategy import PredictiveStrategy
from app.services.strategies.random_strategy import RandomStrategy
from app.services.strategies.signals import Signal


class StrategyEngine:
    """Registry + active-mode holder; sole entry point for consumers (R1.3, R4)."""

    def __init__(self, default: str) -> None:
        """Set the deterministic default active mode (R4.5).

        The default name is recorded as the active mode immediately; it MUST be
        registered (before or after construction) for :meth:`generate` and
        :meth:`get_active_name` to resolve to a usable strategy. Keeping the
        default as the active mode from construction makes startup deterministic
        (R4.5).
        """
        self._strategies: dict[str, Strategy] = {}
        self._default = default
        self._active = default

    def register(self, name: str, strategy: Strategy) -> None:
        """Register a Strategy under a name (R1.3, R4.2)."""
        self._strategies[name] = strategy

    def get_active_name(self) -> str:
        """Return the name of the currently active strategy (R4.1)."""
        return self._active

    def set_active(self, name: str) -> None:
        """Switch the active mode by name (R4.2, R4.3).

        Checks membership *before* mutating: if ``name`` is not registered, raise
        :class:`UnknownStrategyError` and leave the active mode unchanged
        (R1.4, R4.4).
        """
        if name not in self._strategies:
            raise UnknownStrategyError(
                f"unknown strategy '{name}'; registered: "
                f"{sorted(self._strategies)}"
            )
        self._active = name

    def generate(self, bars: Sequence[Bar], quote: Quote | None = None) -> Signal:
        """Delegate to the active strategy and return its Signal (R4.3).

        If the active mode is not registered (e.g. the default was never
        registered), raise a clear :class:`UnknownStrategyError` (R1.4).
        """
        strategy = self._strategies.get(self._active)
        if strategy is None:
            raise UnknownStrategyError(
                f"active strategy '{self._active}' is not registered; registered: "
                f"{sorted(self._strategies)}"
            )
        return strategy.generate(bars, quote)


# Default active mode: "random" is the safe sanity-check baseline (R2). It is the
# deterministic startup default (R4.5) because it has no data requirements and is
# meant to validate the whole pipeline end to end before switching to predictive.
DEFAULT_MODE = "random"


def build_default_engine() -> StrategyEngine:
    """Build a :class:`StrategyEngine` wired with the standard strategies (R4).

    Registers ``random`` (:class:`RandomStrategy`) and ``predictive``
    (:class:`PredictiveStrategy`) and sets the deterministic default active mode
    to ``random`` — the safe baseline used to sanity-check the pipeline (R4.5).
    """
    engine = StrategyEngine(default=DEFAULT_MODE)
    engine.register("random", RandomStrategy())
    engine.register("predictive", PredictiveStrategy())
    return engine
