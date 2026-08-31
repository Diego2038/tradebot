"""Bot orchestrator: owns the bot lifecycle and the wired pipeline (spec 07, Task 3).

The :class:`BotOrchestrator` is the only stateful piece of the bot API. It holds
the shared domain singletons (streamer, engine, executor, position manager) and
the current :class:`BotState`, and exposes :meth:`start`, :meth:`stop`, and
:meth:`status` (R2).

Pipeline wiring (what "running" means): while running, each live ``Bar``/``Quote``
from the :class:`MarketDataStreamer` drives two independent consumers, both
registered via ``streamer.subscribe(...)``:

- :meth:`_on_market_data` maintains a rolling buffer of recent bars **plus a
  forming (in-progress) bar aggregated from live trades**, calls
  ``engine.generate(bars, quote)`` and forwards the resulting ``Signal`` to
  ``executor.execute_signal(signal)``.
- ``position_manager.on_quote`` receives each live quote for Stop-Loss /
  Take-Profit evaluation.

**Forming-bar aggregation (why it exists).** The live crypto feed delivers mostly
individual trades, normalized as :class:`Quote` (see ``streaming.py``, which
subscribes to trades); official 1-minute :class:`Bar` messages arrive at most
once per minute. Strategies, however, consume *bars*: ``PredictiveStrategy`` is
deliberately deterministic on its input bars and ignores the quote (spec 03,
R3.7), detecting a crossover by comparing the last two SMA positions. If the
orchestrator only appended ``Bar`` objects to the buffer, the bar series would
stay frozen between official bars: every tick would recompute the exact same
indicators and the bot would emit ``HOLD`` forever (``random`` was unaffected
because it ignores bars).

So the orchestrator — not the strategy — is where trades become bars: each quote
updates a **forming bar** for the current minute (OHLC accumulated from the
trades seen so far), and that forming bar is appended as the **last element** of
the series handed to ``engine.generate``. The series therefore advances and its
latest close tracks the current price, so windowed indicators (SMA/RSI) move and
crossovers can fire in real time, without changing the strategy's deterministic
contract over bars. When the minute rolls over, the finished forming bar is
committed to the rolling buffer; when an official ``Bar`` arrives it supersedes
the forming bar (which is discarded) to avoid double-counting the same minute.

Design decisions honoured here (see design.md, Components > Bot orchestrator,
Architecture > "Pipeline wiring", Error Handling, Correctness Properties P1-P4):

- **Idempotent start (R2.8).** Starting while already ``RUNNING`` returns the
  current status without subscribing again or starting a second streamer.
- **Credential check first (R2.3).** A missing credential set surfaces
  :class:`CredentialsRequiredError` and the pipeline does not start (state stays
  ``STOPPED``).
- **Mode set before start (R2.4).** ``engine.set_active(mode)`` runs before any
  streamer wiring; an unregistered mode raises :class:`UnknownStrategyError` and
  leaves the state unchanged (``STOPPED``).
- **Resilient ticks.** :meth:`_on_market_data` wraps its body in a
  try/except that logs and continues, so one bad tick never stops the bot.
- **Paper-only preserved (R2.7).** The orchestrator adds no path to live
  trading; the streamer/executor use the same ``AlpacaClientFactory`` paper
  barrier (spec 01). This class never touches base URLs or a live flag.

Credential check design: the orchestrator accepts an optional injectable
``credential_check: Callable[[], bool] | None``. When provided it is consulted in
:meth:`start`; returning ``False`` means no usable credentials are configured and
:class:`CredentialsRequiredError` is raised before any pipeline wiring (R2.3).
When ``None`` (the default), no explicit pre-check is performed here: credential
availability is then enforced downstream when the executor/streamer build their
Alpaca client via the factory (which raises :class:`CredentialsRequiredError`
itself). A simple injectable callable returning ``bool`` keeps the check
explicit and directly testable.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from decimal import Decimal
from typing import Callable, Deque

from app.services.alpaca_client.errors import CredentialsRequiredError
from app.services.bot.state import BotState, BotStatus
from app.services.data_feed.models import Bar, Quote
from app.services.data_feed.streaming import MarketDataStreamer
from app.services.execution.executor import OrderExecutor
from app.services.execution.positions import PositionManager
from app.services.strategies.registry import StrategyEngine
from app.services.strategies.signals import Action

logger = logging.getLogger(__name__)

__all__ = ["BotOrchestrator"]

#: How many recent bars to keep in the rolling buffer fed to ``engine.generate``.
DEFAULT_BAR_BUFFER = 200

#: Minimum number of buffered bars for windowed strategies to be able to decide.
#: This is the window ``PredictiveStrategy`` needs with its default periods:
#: ``max(long_period=20, rsi_period + 1 = 15) == 20``. Below this, predictive can
#: only emit HOLD ("insufficient bars"), so falling short of it after the warm-up
#: preload is worth a warning.
WARMUP_BARS_MIN = 20


class BotOrchestrator:
    """Owns the bot lifecycle and the wired pipeline (R2).

    Holds the shared singletons and the current :class:`BotState` (initially
    ``STOPPED``). Starting subscribes the market-data consumers and starts the
    streamer; stopping stops and releases it.

    It also owns the bar series fed to the engine: a rolling buffer of closed
    bars plus a forming bar aggregated from live trades (quotes), appended last
    so windowed strategies see a series that advances on every tick. See the
    module docstring for the rationale.
    """

    def __init__(
        self,
        streamer: MarketDataStreamer,
        engine: StrategyEngine,
        executor: OrderExecutor,
        position_manager: PositionManager,
        symbol: str = "BTC/USD",
        *,
        credential_check: Callable[[], bool] | None = None,
        bar_buffer_size: int = DEFAULT_BAR_BUFFER,
        bar_preloader: Callable[[], list[Bar]] | None = None,
    ) -> None:
        self._streamer = streamer
        self._engine = engine
        self._executor = executor
        self._position_manager = position_manager
        self._symbol = symbol
        self._credential_check = credential_check
        self._bar_preloader = bar_preloader
        self._state: BotState = BotState.STOPPED
        # Rolling buffer of the most recent bars fed to engine.generate; the
        # latest quote is tracked so strategies that need it always get one.
        self._bars: Deque[Bar] = deque(maxlen=bar_buffer_size)
        self._last_quote: Quote | None = None
        # Bar currently being aggregated from live trades (quotes) for the
        # in-progress minute. Appended as the last element of the series handed
        # to the engine so windowed indicators follow the current price; see the
        # module docstring ("Forming-bar aggregation").
        self._forming_bar: Bar | None = None
        # Ticks (market-data data evaluated by the pipeline) of the current
        # session. Used for observability: every non-HOLD signal is logged, and
        # HOLDs are summarised at INFO on the first few ticks (immediate proof
        # that the pipeline is alive after startup) and every 10 ticks from then
        # on, so the logs prove liveness without flooding. Reset on
        # :meth:`stop`.
        self._ticks: int = 0
        # Background task running the streamer's (infinite) reconnection loop.
        # The loop is launched with ``asyncio.create_task`` in :meth:`start` so
        # the HTTP handler returns immediately instead of awaiting it forever.
        self._stream_task: asyncio.Task | None = None

    async def start(self, mode: str) -> BotStatus:
        """Start the pipeline in the given mode (R2.2, R2.3, R2.4, R2.8).

        - If already ``RUNNING``, this is idempotent: returns the current status
          without starting a second pipeline (no re-subscribe, no second
          ``streamer.start()``) (R2.8).
        - Verifies credentials via the injected ``credential_check`` (if any);
          ``False`` raises :class:`CredentialsRequiredError` and leaves the state
          ``STOPPED`` (R2.3).
        - Sets the active mode via ``engine.set_active(mode)`` **before** any
          streamer wiring; an unregistered mode raises
          :class:`UnknownStrategyError`, which propagates with the state
          unchanged (``STOPPED``) (R2.4).
        - Best-effort preloads recent historical bars into the rolling buffer
          (if a ``bar_preloader`` was injected) so strategies that need a warm-up
          window (notably ``predictive``, which needs >= 20 bars) have data from
          the first live tick. A failing preload is logged and ignored: the bot
          still starts with an empty buffer.
        - Subscribes :meth:`_on_market_data` (feeds engine + executor) and
          ``position_manager.on_quote`` to the streamer, then launches the
          streamer's (infinite) reconnection loop as a **background task** and
          transitions to ``RUNNING`` immediately (R2.2). Awaiting the loop
          directly would hang the HTTP handler forever, so it is scheduled with
          ``asyncio.create_task`` instead.

        Raises:
            CredentialsRequiredError: If ``credential_check`` reports no usable
                credentials; the pipeline does not start (R2.3).
            UnknownStrategyError: If ``mode`` is not a registered strategy; the
                state is left unchanged (R2.4).
        """
        # Idempotent while running: no second pipeline (R2.8).
        if self._state is BotState.RUNNING:
            logger.info("Bot already running; start(%s) is a no-op (R2.8)", mode)
            return self.status()

        # Credential check before anything else (R2.3). On failure the state stays
        # STOPPED and no streamer wiring/start happens.
        if self._credential_check is not None and not self._credential_check():
            logger.warning("Start refused: no credentials configured (R2.3)")
            raise CredentialsRequiredError(
                "no Alpaca credentials configured; cannot start the bot"
            )

        # Set the active mode BEFORE wiring/starting the streamer (R2.4). An
        # unregistered mode raises UnknownStrategyError here, leaving state
        # STOPPED and the streamer untouched (no task created).
        self._engine.set_active(mode)

        # Best-effort preload of recent historical bars so predictive has enough
        # warm-up data from the first tick. Never blocks the start on failure.
        # Run the (synchronous, network-bound) preloader off the event loop with
        # ``asyncio.to_thread`` so it does not stall the loop while downloading.
        if self._bar_preloader is not None:
            try:
                preloaded = await asyncio.to_thread(self._bar_preloader)
                for bar in preloaded:
                    self._bars.append(bar)
                logger.info(
                    "Preloaded %d historical bars for warm-up (symbol=%s)",
                    len(preloaded),
                    self._symbol,
                )
            except Exception:  # noqa: BLE001 - preload is best-effort, never blocks start
                logger.exception(
                    "Bar preload failed (symbol=%s); starting with empty buffer",
                    self._symbol,
                )

        # Observability: make an insufficient warm-up explicit at start time
        # instead of letting the operator infer it from a stream of
        # "insufficient bars" HOLDs. Runs whether or not a preloader was
        # injected (no preloader => empty buffer => this fires).
        if len(self._bars) < WARMUP_BARS_MIN:
            logger.warning(
                "Only %d bars buffered (< %d needed for windowed strategies); "
                "predictive will emit HOLD until enough live bars accumulate "
                "(symbol=%s)",
                len(self._bars),
                WARMUP_BARS_MIN,
                self._symbol,
            )

        # Wire the two independent consumers (subscribe is idempotent per
        # callback in the streamer, so a re-start does not cause double
        # delivery), then launch the streamer loop as a background task (R2.2).
        self._streamer.subscribe(self._on_market_data)
        self._streamer.subscribe(self._position_manager.on_quote)
        self._stream_task = asyncio.create_task(self._streamer.start())

        self._state = BotState.RUNNING
        logger.info("Bot started in mode=%s (symbol=%s)", mode, self._symbol)
        return self.status()

    async def stop(self) -> BotStatus:
        """Stop the pipeline and release the streamer, transitioning to ``STOPPED`` (R2.5).

        First clears the streamer's active flag and releases its connection via
        ``streamer.stop()`` (which makes the background loop's ``while`` exit),
        then cancels and awaits the background task launched in :meth:`start`
        (if any) so no orphan task is left behind. Cancellation and any residual
        error from the awaited task are swallowed and logged; the task reference
        is reset to ``None``. Robust even if the task already finished.

        The in-progress forming bar is discarded so a new session never inherits
        a half-aggregated minute from the previous one, and the tick counter is
        logged (session total) and reset to 0.
        """
        await self._streamer.stop()

        task = self._stream_task
        if task is not None:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - teardown must not raise
                logger.exception(
                    "Background stream task raised on shutdown (symbol=%s); "
                    "continuing",
                    self._symbol,
                )
            finally:
                self._stream_task = None

        # Clean up per-session aggregation state.
        self._forming_bar = None

        self._state = BotState.STOPPED
        # The tick total closes the session's observability trail: it tells at a
        # glance how many evaluations the pipeline actually ran.
        logger.info(
            "Bot stopped (symbol=%s) after %d ticks", self._symbol, self._ticks
        )
        self._ticks = 0
        return self.status()

    def status(self) -> BotStatus:
        """Return the current :class:`BotState`, active mode, and symbol (R2.6)."""
        return BotStatus(
            state=self._state,
            mode=self._engine.get_active_name(),
            symbol=self._symbol,
        )

    def _update_forming_bar(self, quote: Quote) -> None:
        """Aggregate one live trade (quote) into the forming bar for its minute.

        The quote's minute is ``quote.timestamp`` truncated to the minute. Two
        cases:

        - **Rollover** (no forming bar yet, or its minute differs): the previous
          forming bar is complete, so it is committed to the rolling buffer, and
          a fresh forming bar starts with ``open = high = low = close =
          quote.price`` and ``volume = 0`` (trade sizes are not carried by
          :class:`Quote`).
        - **Same minute**: ``high``/``low`` extend to the running extremes and
          ``close`` becomes the latest price; ``open``, ``timestamp`` and
          ``volume`` are preserved.

        :class:`Bar` is a frozen dataclass, so updates build a new instance.
        """
        minute = quote.timestamp.replace(second=0, microsecond=0)
        forming = self._forming_bar

        if forming is None or forming.timestamp != minute:
            # Minute rolled over: the previous forming bar is now closed.
            if forming is not None:
                self._bars.append(forming)
            self._forming_bar = Bar(
                timestamp=minute,
                open=quote.price,
                high=quote.price,
                low=quote.price,
                close=quote.price,
                volume=Decimal("0"),
            )
            return

        self._forming_bar = Bar(
            timestamp=forming.timestamp,
            open=forming.open,
            high=max(forming.high, quote.price),
            low=min(forming.low, quote.price),
            close=quote.price,
            volume=forming.volume,
        )

    def _on_market_data(self, datum: Bar | Quote) -> None:
        """Handle one live market-data datum: drive engine + executor (pipeline).

        The streamer delivers either a :class:`Bar` or a :class:`Quote`; the type
        is distinguished with ``isinstance``:

        - A :class:`Bar` is appended to the rolling buffer and the forming bar is
          discarded: the official bar supersedes the trades aggregated for that
          minute, so keeping both would double-count it.
        - A :class:`Quote` becomes the current quote **and** is aggregated into
          the forming bar (:meth:`_update_forming_bar`).

        On every datum the engine receives ``buffer + forming bar`` (the forming
        bar last, when present) so the series advances tick by tick and windowed
        strategies react to the current price; ``engine.generate(bars, quote)``
        produces a ``Signal`` that is passed to
        ``executor.execute_signal(signal)``. The whole body is wrapped in a
        try/except that logs and continues so a single bad tick never stops the
        bot (Error Handling: per-tick resilience).

        Note: ``position_manager.on_quote`` is subscribed to the streamer
        independently (in :meth:`start`), so quotes reach it directly; this
        handler focuses on the engine/executor path.
        """
        try:
            if isinstance(datum, Bar):
                self._bars.append(datum)
                # The official bar for this minute wins over the aggregated one.
                self._forming_bar = None
            elif isinstance(datum, Quote):
                self._last_quote = datum
                self._update_forming_bar(datum)

            logger.debug("Market data tick: %s", type(datum).__name__)

            bars = list(self._bars)
            if self._forming_bar is not None:
                bars.append(self._forming_bar)

            signal = self._engine.generate(bars, self._last_quote)

            # Observability: every actionable signal is logged at INFO; HOLDs go
            # to DEBUG always plus an INFO heartbeat, so the logs distinguish
            # "no data arriving" from "data arrived, decided HOLD". The first
            # few ticks always emit the heartbeat to confirm right away that the
            # pipeline is alive after startup (the crypto feed delivers roughly
            # one tick per minute, so waiting for the 10th would mean ~10
            # minutes of silence); afterwards it drops to one every 10 ticks to
            # avoid flooding when the flow of trades is heavy.
            self._ticks += 1
            last_close = bars[-1].close if bars else None
            if signal.action is not Action.HOLD:
                logger.info(
                    "Signal %s: %s | bars=%d last_close=%s",
                    signal.action.value,
                    signal.reason,
                    len(bars),
                    last_close,
                )
            else:
                logger.debug(
                    "Tick %d: HOLD (%s) | bars=%d last_close=%s",
                    self._ticks,
                    signal.reason,
                    len(bars),
                    last_close,
                )
                if self._ticks <= 3 or self._ticks % 10 == 0:
                    logger.info(
                        "Tick %d: HOLD (%s) | bars=%d last_close=%s",
                        self._ticks,
                        signal.reason,
                        len(bars),
                        last_close,
                    )

            self._executor.execute_signal(signal)
        except Exception:  # noqa: BLE001 - one bad tick must never stop the bot
            logger.exception(
                "Error handling market data tick (symbol=%s); continuing",
                self._symbol,
            )
