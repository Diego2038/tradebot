"""Real-time BTC/USD market data streamer (`MarketDataStreamer`).

Publisher/subscriber component with an async reconnection loop. When the bot
becomes active it builds an Alpaca crypto data stream via the
``AlpacaClientFactory`` (R2.1), subscribes to BTC/USD, and fans out each
received update — normalized to the single :class:`Bar` / :class:`Quote` format
(R2.2) — to all internal consumers (strategy engine, WebSocket bridge).

Every raw update passes through :class:`Normalizer`; ``None`` results (malformed
data) are logged and discarded without interrupting processing (R3.3).

On a dropped connection while active, the streamer reconnects with exponential
backoff starting at 1s, doubling up to a 30s cap, indefinitely, without letting
any exception terminate the process (R2.3). Stopping clears the active flag and
releases the Alpaca connection (R2.4).

The reconnection loop is designed to be testable: the backoff schedule is a pure
function (:func:`_next_backoff`) and the sleep is injectable, so the bounds can
be exercised without sleeping and without a real Alpaca event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from app.services.alpaca_client.factory import AlpacaClientFactory
from app.services.data_feed.models import Bar, Quote
from app.services.data_feed.normalizer import Normalizer

logger = logging.getLogger(__name__)

#: A consumer of normalized market data (strategy engine, WebSocket bridge).
MarketDataCallback = Callable[[Bar | Quote], None]

#: Initial delay (seconds) before the first reconnection attempt (R2.3).
INITIAL_BACKOFF = 1
#: Maximum delay (seconds) between reconnection attempts (R2.3).
MAX_BACKOFF = 30


def _next_backoff(delay: int | float) -> int | float:
    """Return the next backoff delay: double the current one, capped at the max.

    Pure function so the schedule (1, 2, 4, 8, 16, 30, 30, ...) can be tested
    without sleeping (R2.3).
    """
    return min(delay * 2, MAX_BACKOFF)


class MarketDataStreamer:
    """Subscribe to Alpaca's BTC/USD stream and fan out normalized updates.

    Holds a list of callbacks; consumers subscribe independently and the
    streamer never depends on their concrete types (R2.2). The async
    :meth:`start` loop reconnects with exponential backoff while active (R2.3);
    :meth:`stop` clears the flag and releases the connection (R2.4).
    """

    def __init__(
        self,
        factory: AlpacaClientFactory,
        symbol: str = "BTC/USD",
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._factory = factory
        self._symbol = symbol
        # Injectable sleep so the backoff loop can be tested without waiting.
        self._sleep = sleep
        self._subscribers: list[MarketDataCallback] = []
        self._active = False
        self._stream: Any | None = None

    # -- pub/sub ------------------------------------------------------------

    def subscribe(self, callback: MarketDataCallback) -> None:
        """Register an internal consumer (strategy engine, WebSocket bridge) (R2.2).

        Idempotent: registering the same callback twice keeps a single entry so
        a datum is delivered once per distinct subscriber.
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: MarketDataCallback) -> None:
        """Deregister a previously subscribed consumer.

        No-op if the callback was not subscribed.
        """
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _publish(self, datum: Bar | Quote) -> None:
        """Fan out a normalized datum to every subscriber (R2.2).

        A failing subscriber is logged and skipped so one bad consumer cannot
        prevent the others from receiving the datum.
        """
        for callback in list(self._subscribers):
            try:
                callback(datum)
            except Exception:  # noqa: BLE001 - one bad consumer must not break fan-out
                logger.exception(
                    "Subscriber callback raised while handling market data "
                    "(symbol=%s); skipping",
                    self._symbol,
                )

    # -- normalization dispatch --------------------------------------------

    def _handle_raw(self, raw: Any, *, is_quote: bool = False) -> None:
        """Normalize a raw Alpaca update and publish it, or discard if malformed.

        ``None`` results from the :class:`Normalizer` are logged inside the
        normalizer and skipped here without interrupting processing (R3.2, R3.3).
        """
        if is_quote:
            datum: Bar | Quote | None = Normalizer.from_alpaca_quote(raw)
        else:
            datum = Normalizer.from_alpaca_bar(raw)
        if datum is None:
            # Malformed: normalizer already logged the discard. Skip and continue.
            return
        self._publish(datum)

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Run the streaming loop while active, reconnecting with backoff (R2.1, R2.3).

        Marks the streamer active, then repeatedly builds the stream via the
        factory, subscribes to the configured symbol and runs the receive loop.
        Any exception from a connection attempt (including a disconnect) is
        caught: while still active, the loop sleeps for the current backoff
        delay, grows it via :func:`_next_backoff`, and retries — indefinitely,
        without terminating the process. A successful, clean connection resets
        the backoff to :data:`INITIAL_BACKOFF`.
        """
        self._active = True
        delay: int | float = INITIAL_BACKOFF

        while self._active:
            try:
                await self._run_stream_once()
            except Exception:  # noqa: BLE001 - reconnection must never crash the process (R2.3)
                if not self._active:
                    break
                logger.warning(
                    "Market data stream disconnected (symbol=%s); "
                    "reconnecting in %ss",
                    self._symbol,
                    delay,
                )
                await self._sleep(delay)
                delay = _next_backoff(delay)
                continue
            else:
                # Clean return from the stream: reset backoff. If we are still
                # active this means the stream ended without error, so loop and
                # reconnect immediately with a fresh schedule.
                delay = INITIAL_BACKOFF

    async def _run_stream_once(self) -> None:
        """Build the stream, subscribe to the symbol and run its receive loop.

        Isolated so the reconnection loop in :meth:`start` only has to deal with
        "connect + run once, raising on failure". Subscribes both bars and
        quotes when the underlying stream exposes those methods, wiring each to
        the normalizing handler.
        """
        stream = self._factory.build_crypto_data_stream()
        self._stream = stream

        # Wire handlers defensively: not every fake/stream exposes both.
        subscribe_bars = getattr(stream, "subscribe_bars", None)
        if callable(subscribe_bars):
            subscribe_bars(self._on_bar, self._symbol)

        # Alpaca crypto Quotes are bid/ask pairs (no single `price`); Trades carry
        # `price`. Subscribe to trades so the normalizer receives a usable price.
        # Fall back to quotes only if the stream does not expose trades.
        subscribe_trades = getattr(stream, "subscribe_trades", None)
        if callable(subscribe_trades):
            subscribe_trades(self._on_trade, self._symbol)
        else:
            subscribe_quotes = getattr(stream, "subscribe_quotes", None)
            if callable(subscribe_quotes):
                subscribe_quotes(self._on_quote, self._symbol)

        await self._run(stream)

    async def _run(self, stream: Any) -> None:
        """Run the underlying stream's receive loop, awaiting async runners.

        alpaca-py's ``CryptoDataStream`` exposes an async ``_run_forever`` and a
        blocking ``run``; prefer the async runner and fall back defensively.
        """
        runner = getattr(stream, "_run_forever", None)
        if runner is None:
            runner = getattr(stream, "run", None)
        if runner is None:
            raise RuntimeError("stream exposes no run method")

        result = runner()
        if asyncio.iscoroutine(result):
            await result

    async def _on_bar(self, raw: Any) -> None:
        """Async handler for raw bar updates from the stream."""
        self._handle_raw(raw, is_quote=False)

    async def _on_quote(self, raw: Any) -> None:
        """Async handler for raw quote/trade updates from the stream."""
        self._handle_raw(raw, is_quote=True)

    async def _on_trade(self, raw: Any) -> None:
        """Async handler for raw trade updates from the stream.

        Trades carry a single `price`, so they are normalized through the same
        quote path (timestamp + price) into the internal Quote format.
        """
        self._handle_raw(raw, is_quote=True)

    async def stop(self) -> None:
        """Stop streaming: clear the active flag and release the connection (R2.4).

        Attempts to close the stream through whichever teardown method it
        exposes (``stop``, ``close``, or the async ``stop_ws``), tolerating
        either sync or async variants, then drops the reference.
        """
        self._active = False

        stream = self._stream
        if stream is None:
            return

        for name in ("stop", "close", "stop_ws"):
            closer = getattr(stream, name, None)
            if callable(closer):
                try:
                    result = closer()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:  # noqa: BLE001 - teardown must not raise
                    logger.exception(
                        "Error releasing market data stream via %s()", name
                    )
                break

        self._stream = None
