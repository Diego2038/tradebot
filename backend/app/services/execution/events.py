"""Domain events and in-memory publisher for the order-execution layer (spec 04).

This module defines the secret-free domain events emitted by the execution layer
and a minimal in-memory pub/sub publisher used to fan them out to subscribers
(R4.1, R4.2, R4.3, R4.4):

- :class:`EventType` -- the closed set of execution event kinds.
- :class:`OrderEvent` -- an immutable, secret-free description of a state change.
- :data:`EventCallback` -- the callable signature every subscriber implements.
- :class:`EventPublisher` -- an in-memory publisher that fans out each event and
  isolates subscriber failures so the caller is never interrupted.

Spec ``07-bot-api`` subscribes to :class:`EventPublisher` to bridge these events
onto the frontend WebSocket; this spec only publishes to it (R4.4).

The module is **pure Python** (dataclasses, ``Decimal``, ``datetime``, ``enum``,
``logging``): it imports nothing from the Alpaca SDK and carries no secrets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Domain event kinds emitted by the execution layer (R4.1).

    ``str``-backed so consumers (e.g. spec 07) can serialize the value directly
    without a custom encoder.
    """

    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"
    RISK_BLOCK = "RISK_BLOCK"
    STOP_LOSS_CLOSE = "STOP_LOSS_CLOSE"
    TAKE_PROFIT_CLOSE = "TAKE_PROFIT_CLOSE"


@dataclass(frozen=True)
class OrderEvent:
    """A structured, secret-free description of an execution state change (R4.1, R4.2).

    Carries **only** non-sensitive data -- never API keys, secrets, or raw
    credential material.

    Attributes:
        event_type: The kind of state change (see :class:`EventType`).
        symbol: The instrument symbol (e.g. ``"BTC/USD"``).
        side: The order side ``"buy"`` / ``"sell"``; ``None`` for purely
            informational events.
        qty: The order quantity when applicable.
        price: The relevant price when applicable (fills, SL/TP closes).
        order_id: The Alpaca order id when known.
        reason: A human-readable, secret-free explanation.
        timestamp: When the event was created (UTC), defaulting to now.
    """

    event_type: EventType
    symbol: str
    side: str | None = None
    qty: Decimal | None = None
    price: Decimal | None = None
    order_id: str | None = None
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


EventCallback = Callable[[OrderEvent], None]


class EventPublisher:
    """In-memory pub/sub for domain events (R4.1, R4.3, R4.4).

    Spec ``07-bot-api`` subscribes to this publisher to bridge events to the
    frontend WebSocket. Subscribers are notified in registration order; a
    subscriber that raises is caught and logged so it never interrupts the
    caller or the remaining subscribers (R4.3).
    """

    def __init__(self) -> None:
        self._subscribers: list[EventCallback] = []

    def subscribe(self, callback: EventCallback) -> None:
        """Register a subscriber to receive every published :class:`OrderEvent`.

        Registering the same callback twice is a no-op (it is added only once).
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: EventCallback) -> None:
        """Remove a previously registered subscriber.

        Unsubscribing a callback that is not registered is a no-op.
        """
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def publish(self, event: OrderEvent) -> None:
        """Fan out an event to all subscribers.

        Iterates over a **copy** of the subscriber list (so subscribe/unsubscribe
        during delivery is safe) and wraps each callback in ``try/except``. A
        subscriber that raises is caught and logged (without secrets); the
        remaining subscribers still receive the event and the caller is never
        interrupted (R4.3).
        """
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception:
                logger.exception(
                    "Event subscriber %r failed handling event %s; continuing",
                    getattr(callback, "__name__", repr(callback)),
                    event.event_type,
                )
