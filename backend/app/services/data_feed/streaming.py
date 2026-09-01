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
import inspect
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

#: Teardown methods tried, **in this order**, to release the provider connection
#: on :meth:`MarketDataStreamer.stop` (R2.4). Both are coroutines in alpaca-py's
#: ``DataStream``:
#:
#: - ``stop_ws()`` only *signals*: clears the stream's ``_should_run`` flag and
#:   queues a sentinel so its ``_run_forever`` receive loop returns cleanly.
#: - ``close()`` performs the actual release: ``await self._ws.close()`` and drops
#:   the socket, which is what frees the connection slot on Alpaca's side.
#:
#: Both run on every stop: signalling without closing leaves the socket open (and
#: the provider still counting the connection), closing without signalling leaves
#: the receive loop spinning on a reconnect.
ASYNC_CLOSERS = ("stop_ws", "close")

#: Last-resort teardown method, used **only** when the stream exposes none of
#: :data:`ASYNC_CLOSERS` (e.g. simple test doubles with sync-only methods).
#: alpaca-py's ``DataStream.stop()`` is synchronous and implemented as
#: ``asyncio.run_coroutine_threadsafe(self.stop_ws(), self._loop).result(timeout=5)``,
#: i.e. it is meant to be called from *another* thread. Calling it from inside the
#: event loop (as this streamer runs) blocks the very loop that must execute the
#: scheduled coroutine: a deadlock that ends in ``TimeoutError`` after 5s with the
#: socket still open, so it is never used when an async closer exists.
SYNC_CLOSER = "stop"


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

    async def _call_closer(self, name: str, closer: Callable[[], Any]) -> bool:
        """Invoke one teardown method, awaiting it if it returns an awaitable.

        Returns ``True`` if it completed without raising. Failures are logged and
        reported as ``False`` so the caller can keep trying the remaining
        teardown methods instead of aborting the release.
        """
        try:
            result = closer()
            # isawaitable covers coroutines and futures/tasks alike, so an
            # implementation returning a future is awaited too.
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - teardown must not raise
            logger.exception("Error releasing market data stream via %s()", name)
            return False
        logger.info("Market data stream released via %s()", name)
        return True

    async def _release_stream(self, stream: Any) -> None:
        """Release the provider connection held by ``stream`` (R2.4).

        Runs the **full** async teardown sequence, in order: ``stop_ws()`` to
        signal the receive loop to finish, then ``close()`` to actually close the
        socket and free the connection slot on the provider (Alpaca's free plan
        allows a single data connection, so a socket left open makes the next
        start fail with ``connection limit exceeded``).

        Every step is attempted: a failure in one is logged and does not skip the
        next, because ``close()`` is precisely the step that releases the
        connection. The synchronous ``stop()`` is used only as a last resort when
        the object exposes neither async closer (see :data:`SYNC_CLOSER` for why
        it must not be called from inside the event loop).
        """
        closers: list[tuple[str, Callable[[], Any]]] = []
        for name in ASYNC_CLOSERS:
            closer = getattr(stream, name, None)
            if callable(closer):
                closers.append((name, closer))

        if not closers:
            fallback = getattr(stream, SYNC_CLOSER, None)
            if callable(fallback):
                await self._call_closer(SYNC_CLOSER, fallback)
            else:
                logger.warning(
                    "Market data stream exposes no teardown method (symbol=%s); "
                    "connection may leak",
                    self._symbol,
                )
            return

        released = False
        for name, closer in closers:
            released = await self._call_closer(name, closer) or released

        if not released:
            logger.warning(
                "Every teardown method failed for the market data stream "
                "(symbol=%s); connection may leak",
                self._symbol,
            )

    async def stop(self) -> None:
        """Stop streaming: clear the active flag and release the connection (R2.4).

        Clearing ``_active`` makes the reconnection loop in :meth:`start` exit;
        :meth:`_release_stream` then tears the stream down (``stop_ws`` +
        ``close``) before the reference is dropped. The final INFO line is the
        operational proof that the socket was handed back, so a follow-up start
        does not hit the provider's connection limit.
        """
        self._active = False

        stream = self._stream
        if stream is None:
            return

        await self._release_stream(stream)

        self._stream = None
        logger.info(
            "Market data stream connection released (symbol=%s)", self._symbol
        )
