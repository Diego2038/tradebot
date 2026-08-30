"""Risk port types shared between order execution (spec 04) and the risk manager (spec 06).

This module is **owned by spec ``04-order-execution``** and defines the interface
that order execution uses to gate every order before it is sent to Alpaca:

- :class:`ProposedOrder` -- the input handed to the risk layer.
- :class:`RiskDecision` -- the yes/no answer (with a reason) returned by the risk layer.
- :class:`RiskPort` -- the ``runtime_checkable`` ``Protocol`` the executor depends on.

Spec ``06-risk-manager`` imports these types (never redefines them) and provides
the real ``RiskManager`` that implements ``RiskPort``. Because ``RiskPort`` is
``@runtime_checkable``, any object exposing a matching ``evaluate`` method
satisfies ``isinstance(obj, RiskPort)`` structurally, without explicit inheritance.

The module is **pure Python** (dataclasses, ``Decimal``, ``typing``): it imports
nothing from the Alpaca SDK and can be imported in isolation, keeping the risk
package and its tests free of any SDK dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ProposedOrder:
    """The order the executor asks the risk layer to approve.

    Attributes:
        symbol: The instrument symbol (e.g. ``"BTC/USD"``).
        side: The order side, either ``"buy"`` or ``"sell"``.
        qty: The requested order quantity as a :class:`~decimal.Decimal`.
    """

    symbol: str
    side: str  # "buy" / "sell"
    qty: Decimal


@dataclass(frozen=True)
class RiskDecision:
    """The result of a risk evaluation.

    Attributes:
        approved: ``True`` if the proposed order is allowed, ``False`` if blocked.
        reason: A human-readable, secret-free explanation. Empty string when the
            order is approved.
    """

    approved: bool
    reason: str = ""


@runtime_checkable
class RiskPort(Protocol):
    """The single risk-evaluation gate the executor consults before sending an order.

    The real implementation is provided by spec ``06-risk-manager``; consumers
    depend only on this port. As a ``runtime_checkable`` ``Protocol``, conformance
    is structural: any object with a compatible ``evaluate`` method is an instance.
    """

    def evaluate(self, proposed_order: ProposedOrder) -> RiskDecision: ...
