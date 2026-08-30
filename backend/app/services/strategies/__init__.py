"""Strategy engine package (spec 03-strategy-engine).

Turns BTC/USD market data (spec-02 ``Bar``/``Quote``) into trading signals
(``BUY``/``SELL``/``HOLD``) via a plug-and-play ``Strategy`` interface and a
selectable set of strategies (``random``, ``predictive``) owned by a
``StrategyEngine`` registry.

Public API:
- ``Action``, ``Signal`` — the output shape every consumer sees.
- ``Strategy`` — the common plug-and-play interface.
- ``StrategyEngine`` / ``build_default_engine`` — the registry and default wiring.
- ``StrategyError`` / ``UnknownStrategyError`` — domain errors.
"""

from app.services.strategies.base import Strategy
from app.services.strategies.errors import StrategyError, UnknownStrategyError
from app.services.strategies.registry import StrategyEngine, build_default_engine
from app.services.strategies.signals import Action, Signal

__all__ = [
    "Action",
    "Signal",
    "Strategy",
    "StrategyEngine",
    "build_default_engine",
    "StrategyError",
    "UnknownStrategyError",
]
