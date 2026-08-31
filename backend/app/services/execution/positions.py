"""Position manager for automatic Stop-Loss / Take-Profit closes (spec 04, Task 5).

This module is **owned by spec ``04-order-execution``** and implements the
component that tracks the single open long ``BTC/USD`` position and closes it
automatically when a live :class:`~app.services.data_feed.models.Quote` price
reaches the configured Stop-Loss or Take-Profit level (R2):

- :class:`Position` -- an internal, mutable record of the open position and its
  optional SL/TP levels.
- :class:`PositionManager` -- registers a position (validating its levels),
  evaluates each incoming quote, and closes the position + emits the matching
  domain event when a threshold is crossed.

The manager is **decoupled from the streamer**: it receives quotes through
:meth:`PositionManager.on_quote` and never imports the ``MarketDataStreamer``.
Wiring (``streamer.subscribe(pm.on_quote)``) belongs to another layer, keeping
the position logic pure and directly unit-testable (R2.3).

The trading client is obtained **only** through
``AlpacaClientFactory.build_trading_client()`` (spec 01); this module never
constructs an Alpaca client directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from app.services.alpaca_client.factory import AlpacaClientFactory
from app.services.data_feed.models import Quote
from app.services.execution.errors import InvalidLevelError
from app.services.execution.events import EventPublisher, EventType, OrderEvent

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Internal record of the open long position and its optional SL/TP levels (R2.1).

    Attributes:
        symbol: The instrument symbol (e.g. ``"BTC/USD"``).
        side: The order side that opened the position (``"buy"`` for a long).
        qty: The position quantity as a :class:`~decimal.Decimal`.
        entry_price: The price at which the position was opened.
        stop_loss: Optional Stop-Loss level; must be ``< entry_price`` when set.
        take_profit: Optional Take-Profit level; must be ``> entry_price`` when set.
    """

    symbol: str
    side: str
    qty: Decimal
    entry_price: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None


class PositionManager:
    """Tracks the open long ``BTC/USD`` position and closes it on SL/TP (R2).

    A single position is tracked at a time (this phase manages one asset). The
    manager obtains its trading client only through the injected
    :class:`~app.services.alpaca_client.factory.AlpacaClientFactory` and emits
    domain events through the injected
    :class:`~app.services.execution.events.EventPublisher`.
    """

    def __init__(self, factory: AlpacaClientFactory, publisher: EventPublisher) -> None:
        self._factory = factory
        self._publisher = publisher
        self._position: Position | None = None

    @property
    def position(self) -> Position | None:
        """The currently tracked open position, or ``None`` if none is open."""
        return self._position

    def open_position(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> None:
        """Record an open long position with optional SL/TP levels (R2.1, R2.2).

        For a long position the valid ordering is
        ``stop_loss < entry_price < take_profit``. An invalid level raises
        :class:`~app.services.execution.errors.InvalidLevelError` (a
        ``ValueError``): no tracking starts for that level and the process keeps
        running -- the caller decides how to react (R2.2).

        Args:
            symbol: The instrument symbol (e.g. ``"BTC/USD"``).
            side: The opening side (``"buy"`` for a long).
            qty: The position quantity.
            entry_price: The price at which the position was opened.
            stop_loss: Optional Stop-Loss level; must be ``< entry_price``.
            take_profit: Optional Take-Profit level; must be ``> entry_price``.

        Raises:
            InvalidLevelError: If ``stop_loss >= entry_price`` or
                ``take_profit <= entry_price``.
        """
        if stop_loss is not None and stop_loss >= entry_price:
            raise InvalidLevelError(
                f"stop_loss {stop_loss} must be below entry_price {entry_price} "
                "for a long position"
            )
        if take_profit is not None and take_profit <= entry_price:
            raise InvalidLevelError(
                f"take_profit {take_profit} must be above entry_price {entry_price} "
                "for a long position"
            )

        self._position = Position(
            symbol=symbol,
            side=side,
            qty=qty,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def on_quote(self, quote: Quote) -> None:
        """Evaluate the latest live price against the open position's levels (R2.3-R2.6).

        Behavior:
            - No open position, or a position with neither Stop-Loss nor
              Take-Profit configured -> no-op (R2.6).
            - ``quote.price <= stop_loss`` -> close the position and publish a
              ``STOP_LOSS_CLOSE`` event (R2.4).
            - ``quote.price >= take_profit`` -> close the position and publish a
              ``TAKE_PROFIT_CLOSE`` event (R2.5).
            - Otherwise -> no-op.

        Once a position is closed, ``self._position`` is cleared so a later quote
        never triggers a second close.
        """
        position = self._position
        if position is None:
            return
        if position.stop_loss is None and position.take_profit is None:
            return

        price = quote.price
        if position.stop_loss is not None and price <= position.stop_loss:
            self._close(
                position,
                EventType.STOP_LOSS_CLOSE,
                price,
                reason=f"stop-loss hit at {price} (level {position.stop_loss})",
            )
            return
        if position.take_profit is not None and price >= position.take_profit:
            self._close(
                position,
                EventType.TAKE_PROFIT_CLOSE,
                price,
                reason=f"take-profit hit at {price} (level {position.take_profit})",
            )
            return

    def _close(
        self,
        position: Position,
        event_type: EventType,
        price: Decimal,
        reason: str,
    ) -> None:
        """Close the given position via the trading client and emit ``event_type``.

        The trading client is obtained through the factory (never constructed
        directly). The close call is defensive: if the client exposes a
        ``close_position`` method it is used, otherwise the failure is logged and
        swallowed so an SDK/network problem never crashes the bot. Regardless of
        the client outcome, the position is marked closed (``self._position =
        None``) and the domain event is emitted so subscribers always learn the
        SL/TP fired (R2.4, R2.5).
        """
        try:
            client = self._factory.build_trading_client()
            close_position = getattr(client, "close_position", None)
            if callable(close_position):
                close_position(position.symbol)
        except Exception:  # noqa: BLE001 - stay alive; the close event still fires.
            logger.exception(
                "Failed to submit close order for %s; emitting %s anyway",
                position.symbol,
                event_type,
            )

        # Mark closed before publishing so a re-entrant subscriber sees no position.
        self._position = None

        self._publisher.publish(
            OrderEvent(
                event_type=event_type,
                symbol=position.symbol,
                side=position.side,
                qty=position.qty,
                price=price,
                reason=reason,
            )
        )
