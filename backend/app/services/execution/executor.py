"""Order executor: turns a Signal into (at most) one paper order (spec 04, Task 6).

This module is **owned by spec ``04-order-execution``** and provides the
:class:`OrderExecutor` that ties together the whole submission pipeline:

    Signal -> risk gate (RiskPort) -> deterministic client_order_id (orders)
           -> MarketOrderRequest (orders) -> TradingClient via AlpacaClientFactory
           -> submit with idempotent retries -> record -> OrderEvent (EventPublisher)

Design decisions honoured here (see design.md):

- **Factory-only client access.** The executor never constructs an Alpaca client
  directly; it always calls ``AlpacaClientFactory.build_trading_client()`` so it
  inherits decrypted credentials and the paper-only barrier (R1.1, R1.2).
- **Risk gate first.** Every BUY/SELL goes through ``RiskPort.evaluate`` before any
  submission; a rejection submits nothing and emits ``RISK_BLOCK`` (R5.1, R5.3).
- **Deterministic idempotency.** A single ``attempt_key`` (from the signal) yields one
  ``client_order_id`` reused across up to :data:`OrderExecutor.MAX_ATTEMPTS` tries, so
  a retry never creates a second order (R3.1, R3.2, R3.3, R3.4, R3.5).
- **Stay alive on Alpaca errors.** Non-auth API rejections become ``REJECTED`` events;
  transient (timeout/network) failures are retried and, on exhaustion, become an
  ``ERROR`` event. Only :class:`CredentialsRequiredError` propagates (R1.6, R1.7, R1.8).

Alpaca's ``APIError`` type is imported **lazily** (as in spec 01's factory) so importing
this module never requires the SDK, and error classification stays defensive across SDK
versions (by type when available, by attributes/name otherwise).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from app.services.alpaca_client.errors import (
    CredentialsRequiredError,
    TransientAlpacaError,
)
from app.services.alpaca_client.factory import AlpacaClientFactory
from app.services.execution.events import EventPublisher, EventType, OrderEvent
from app.services.execution.orders import (
    build_market_order_request,
    make_client_order_id,
)
from app.services.execution.risk import ProposedOrder, RiskPort
from app.services.strategies.signals import Action, Signal

logger = logging.getLogger(__name__)

__all__ = ["OrderExecutor", "OrderRecord"]

# HTTP statuses that mean "authentication failed" — these are NOT non-auth
# rejections and are handled by the credentials path, not turned into REJECTED.
_AUTH_STATUS_CODES = frozenset({401, 403})


@dataclass(frozen=True)
class OrderRecord:
    """The non-sensitive result recorded for a successfully submitted order (R1.3)."""

    order_id: str | None
    status: str | None
    symbol: str
    qty: Decimal
    side: str


def _extract_status_code(error: Exception) -> int | None:
    """Defensively extract an HTTP status code from an Alpaca ``APIError``.

    The SDK has exposed the code under different attributes across versions
    (``status_code`` or ``code``); try both without coupling to one.
    """
    for attr in ("status_code", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _is_transient_error(error: Exception) -> bool:
    """Return ``True`` for a timeout / network failure (by type or by name).

    Mirrors the factory's classifier (spec 01): recognises the stdlib
    ``TimeoutError`` / ``ConnectionError`` and common ``requests``/``httpx`` type
    names by MRO so it works whether or not those libraries are installed.
    """
    if isinstance(error, (TimeoutError, ConnectionError, TransientAlpacaError)):
        return True
    transient_names = {
        "Timeout",
        "ConnectTimeout",
        "ReadTimeout",
        "ConnectionError",
        "ConnectError",
        "NewConnectionError",
        "MaxRetryError",
    }
    for klass in type(error).__mro__:
        if klass.__name__ in transient_names:
            return True
    return False


def _is_non_auth_api_error(error: Exception) -> bool:
    """Return ``True`` for a **non-authentication** Alpaca API rejection (R1.6).

    Detects the SDK ``APIError`` via a lazy import (so this module never requires
    the SDK) and, defensively, by type-name/attribute when the import is
    unavailable. Auth statuses (401/403) are excluded so they are not swallowed as
    plain rejections.
    """
    try:
        from alpaca.common.exceptions import APIError
    except Exception:  # noqa: BLE001 - SDK may be absent/stubbed
        APIError = None  # type: ignore[assignment]

    is_api_error = False
    if APIError is not None and isinstance(error, APIError):
        is_api_error = True
    else:
        # Defensive fallback: recognise by type name if the SDK is not importable.
        for klass in type(error).__mro__:
            if klass.__name__ == "APIError":
                is_api_error = True
                break

    if not is_api_error:
        return False

    status = _extract_status_code(error)
    return status not in _AUTH_STATUS_CODES


def _extract_order_field(order: object, *names: str) -> object | None:
    """Read the first present attribute (or mapping key) from an SDK order object."""
    for name in names:
        value = getattr(order, name, None)
        if value is not None:
            return value
        if isinstance(order, dict) and order.get(name) is not None:
            return order.get(name)
    return None


class OrderExecutor:
    """Turns a :class:`Signal` into (at most) one paper order, gated by risk, with events.

    Args:
        factory: The sole source of an authenticated paper ``TradingClient`` (R1.1).
        risk: The :class:`RiskPort` consulted before every submission (R5.1).
        publisher: The :class:`EventPublisher` every state change is emitted through.
        symbol: The single traded instrument (default ``"BTC/USD"``).
        qty: The fixed order quantity (default ``Decimal("0.001")``).
    """

    MAX_ATTEMPTS = 3
    SUBMISSION_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        factory: AlpacaClientFactory,
        risk: RiskPort,
        publisher: EventPublisher,
        symbol: str = "BTC/USD",
        qty: Decimal = Decimal("0.001"),
    ) -> None:
        self._factory = factory
        self._risk = risk
        self._publisher = publisher
        self._symbol = symbol
        self._qty = qty

    def execute_signal(self, signal: Signal) -> OrderEvent | None:
        """Execute one :class:`Signal` end to end (R1.1-R1.8, R3, R5).

        Returns the terminal :class:`OrderEvent` for the signal (the success event,
        ``RISK_BLOCK``, ``REJECTED`` or ``ERROR``), or ``None`` for a ``HOLD`` signal.

        Raises:
            CredentialsRequiredError: If no credentials are configured; propagated so
                the caller (spec 07) can surface it. No order is attempted (R1.8).
        """
        # HOLD -> no submission, no event, return None (R1.4).
        if signal.action is Action.HOLD:
            logger.debug("HOLD signal at %s: no order submitted", signal.timestamp)
            return None

        side = "buy" if signal.action is Action.BUY else "sell"

        # Risk gate BEFORE any submission (R5.1).
        decision = self._risk.evaluate(
            ProposedOrder(symbol=self._symbol, side=side, qty=self._qty)
        )
        if not decision.approved:
            logger.info(
                "Risk blocked %s %s %s: %s",
                side,
                self._qty,
                self._symbol,
                decision.reason,
            )
            event = OrderEvent(
                event_type=EventType.RISK_BLOCK,
                symbol=self._symbol,
                side=side,
                qty=self._qty,
                reason=decision.reason,
            )
            self._publisher.publish(event)
            return event

        # Deterministic idempotency key for the whole logical attempt (R3.1, R3.2).
        attempt_key = signal.timestamp.isoformat() + "|" + signal.action.value
        client_order_id = make_client_order_id(self._symbol, side, attempt_key)
        request = build_market_order_request(
            self._symbol, side, self._qty, client_order_id
        )

        # Only credentials errors are allowed to propagate (R1.8). The client is
        # obtained ONCE and reused across retries with the SAME client_order_id.
        client = self._factory.build_trading_client()

        last_error: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                order = client.submit_order(request)
            except Exception as exc:  # noqa: BLE001 - classify below
                if _is_non_auth_api_error(exc):
                    # Non-auth API rejection: stay alive, emit REJECTED (R1.6).
                    logger.warning(
                        "Alpaca rejected %s %s %s (client_order_id=%s): %s",
                        side,
                        self._qty,
                        self._symbol,
                        client_order_id,
                        exc,
                    )
                    event = OrderEvent(
                        event_type=EventType.REJECTED,
                        symbol=self._symbol,
                        side=side,
                        qty=self._qty,
                        order_id=client_order_id,
                        reason=str(exc),
                    )
                    self._publisher.publish(event)
                    return event

                if _is_transient_error(exc):
                    # Timeout/network: retry with the SAME client_order_id (R3.4).
                    last_error = exc
                    logger.warning(
                        "Transient failure submitting %s %s %s "
                        "(attempt %d/%d, client_order_id=%s): %s",
                        side,
                        self._qty,
                        self._symbol,
                        attempt,
                        self.MAX_ATTEMPTS,
                        client_order_id,
                        exc,
                    )
                    continue

                # Anything else unexpected: treat as an error, stay alive.
                last_error = exc
                logger.exception(
                    "Unexpected failure submitting %s %s %s (client_order_id=%s)",
                    side,
                    self._qty,
                    self._symbol,
                    client_order_id,
                )
                break

            # Success: record and emit. A response whose client_order_id matches the
            # one we sent is the same logical order — recorded once (R3.3).
            return self._on_submitted(order, side, client_order_id)

        # Retries exhausted (or unexpected error): unconfirmed submission (R3.4, R3.5).
        logger.error(
            "Unconfirmed submission of %s %s %s after %d attempt(s) "
            "(client_order_id=%s); creating no further order. Last error: %s",
            side,
            self._qty,
            self._symbol,
            self.MAX_ATTEMPTS,
            client_order_id,
            last_error,
        )
        event = OrderEvent(
            event_type=EventType.ERROR,
            symbol=self._symbol,
            side=side,
            qty=self._qty,
            order_id=client_order_id,
            reason="unconfirmed submission after retries",
        )
        self._publisher.publish(event)
        return event

    def _on_submitted(
        self, order: object, side: str, client_order_id: str
    ) -> OrderEvent:
        """Record a submitted order and emit ``SUBMITTED`` then (if filled) ``FILLED``.

        Records ``(id, status, symbol, qty, side)`` (R1.3). Always emits at least
        ``SUBMITTED``; if the order reports a filled status it additionally emits
        ``FILLED`` and returns that as the terminal success event.
        """
        order_id = _extract_order_field(order, "id", "order_id", "client_order_id")
        if order_id is not None:
            order_id = str(order_id)
        status = _extract_order_field(order, "status")
        status_str = str(status) if status is not None else None
        fill_price = _extract_order_field(
            order, "filled_avg_price", "filled_avg", "price"
        )

        record = OrderRecord(
            order_id=order_id,
            status=status_str,
            symbol=self._symbol,
            qty=self._qty,
            side=side,
        )
        logger.info(
            "Recorded order id=%s status=%s %s %s %s (client_order_id=%s)",
            record.order_id,
            record.status,
            record.side,
            record.qty,
            record.symbol,
            client_order_id,
        )

        submitted_event = OrderEvent(
            event_type=EventType.SUBMITTED,
            symbol=self._symbol,
            side=side,
            qty=self._qty,
            order_id=order_id,
            reason=f"submitted (status={status_str})" if status_str else "submitted",
        )
        self._publisher.publish(submitted_event)

        if self._is_filled(status_str):
            price = self._to_decimal(fill_price)
            filled_event = OrderEvent(
                event_type=EventType.FILLED,
                symbol=self._symbol,
                side=side,
                qty=self._qty,
                price=price,
                order_id=order_id,
                reason="filled",
            )
            self._publisher.publish(filled_event)
            return filled_event

        return submitted_event

    @staticmethod
    def _is_filled(status: str | None) -> bool:
        """Return ``True`` when the order status denotes a completed fill."""
        if not status:
            return False
        normalized = status.split(".")[-1].strip().lower()
        return normalized == "filled"

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        """Best-effort conversion of an SDK price value to :class:`Decimal`."""
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:  # noqa: BLE001 - price is informational, never crash
            return None
