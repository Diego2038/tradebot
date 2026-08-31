"""Order execution package (spec 04-order-execution).

The order-execution pipeline is owned by spec ``04-order-execution`` and lives in
this package:

- :mod:`~app.services.execution.events` -- domain events and the in-memory publisher.
- :mod:`~app.services.execution.risk` -- the ``RiskPort`` interface and a
  pass-through ``AllowAllRiskManager`` (the real manager arrives in spec 06).
- :mod:`~app.services.execution.orders` -- the deterministic idempotency key and the
  ``MarketOrderRequest`` builder.
- :mod:`~app.services.execution.errors` -- execution-layer domain errors.
- :mod:`~app.services.execution.positions` -- the ``PositionManager`` (SL/TP).
- :mod:`~app.services.execution.executor` -- the ``OrderExecutor`` tying signal ->
  risk gate -> submit -> record -> events.

The risk port types are reused as-is by spec ``06-risk-manager``, whose
``RiskManager`` implements ``RiskPort``; both specs share this exact module path and
type definitions so there is no duplication or conflict.
"""

from app.services.execution.errors import ExecutionError, InvalidLevelError
from app.services.execution.events import EventPublisher, EventType, OrderEvent
from app.services.execution.executor import OrderExecutor
from app.services.execution.orders import (
    build_market_order_request,
    make_client_order_id,
)
from app.services.execution.risk import (
    AllowAllRiskManager,
    ProposedOrder,
    RiskDecision,
    RiskPort,
)

__all__ = [
    # events
    "EventType",
    "OrderEvent",
    "EventPublisher",
    # risk
    "ProposedOrder",
    "RiskDecision",
    "RiskPort",
    "AllowAllRiskManager",
    # errors
    "ExecutionError",
    "InvalidLevelError",
    # orders
    "make_client_order_id",
    "build_market_order_request",
    # executor
    "OrderExecutor",
]

# PositionManager (spec 04, Task 5) is exported when its module is present. Kept
# conditional so importing this package never fails if positions.py is not yet
# available in a given checkout.
try:  # pragma: no cover - import guard
    from app.services.execution.positions import PositionManager

    __all__.append("PositionManager")
except ImportError:  # pragma: no cover - positions.py not present
    pass
