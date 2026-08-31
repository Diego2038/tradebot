"""Bot orchestrator: owns the bot lifecycle and the wired pipeline (spec 07, Task 3).

The :class:`BotOrchestrator` is the only stateful piece of the bot API. It holds
the shared domain singletons (streamer, engine, executor, position manager) and
the current :class:`BotState`, and exposes :meth:`start`, :meth:`stop`, and
:meth:`status` (R2).

Pipeline wiring (what "running" means): while running, each live ``Bar``/``Quote``
from the :class:`MarketDataStreamer` drives two independent consumers, both
registered via ``streamer.subscribe(...)``:

- :meth:`_on_market_data` maintains a rolling buffer of recent bars, calls
  ``engine.generate(bars, quote)`` and forwards the resulting ``Signal`` to
  ``executor.execute_signal(signal)``.
- ``position_manager.on_quote`` receives each live quote for Stop-Loss /
  Take-Profit evaluation.

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

import logging
from collections import deque
from typing import Callable, Deque

from app.services.alpaca_client.errors import CredentialsRequiredError
from app.services.bot.state import BotState, BotStatus
from app.services.data_feed.models import Bar, Quote
from app.services.data_feed.streaming import MarketDataStreamer
from app.services.execution.executor import OrderExecutor
from app.services.execution.positions import PositionManager
from app.services.strategies.registry import StrategyEngine

logger = logging.getLogger(__name__)

__all__ = ["BotOrchestrator"]

#: How many recent bars to keep in the rolling buffer fed to ``engine.generate``.
DEFAULT_BAR_BUFFER = 200


class BotOrchestrator:
    """Owns the bot lifecycle and the wired pipeline (R2).

    Holds the shared singletons and the current :class:`BotState` (initially
    ``STOPPED``). Starting subscribes the market-data consumers and starts the
    streamer; stopping stops and releases it.
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
    ) -> None:
        self._streamer = streamer
        self._engine = engine
        self._executor = executor
        self._position_manager = position_manager
        self._symbol = symbol
        self._credential_check = credential_check
        self._state: BotState = BotState.STOPPED
        # Rolling buffer of the most recent bars fed to engine.generate; the
        # latest quote is tracked so strategies that need it always get one.
        self._bars: Deque[Bar] = deque(maxlen=bar_buffer_size)
        self._last_quote: Quote | None = None

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
        - Subscribes :meth:`_on_market_data` (feeds engine + executor) and
          ``position_manager.on_quote`` to the streamer, then starts the
          streamer, transitioning to ``RUNNING`` (R2.2).

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
        # STOPPED and the streamer untouched.
        self._engine.set_active(mode)

        # Wire the two independent consumers, then start the streamer (R2.2).
        self._streamer.subscribe(self._on_market_data)
        self._streamer.subscribe(self._position_manager.on_quote)
        await self._streamer.start()

        self._state = BotState.RUNNING
        logger.info("Bot started in mode=%s (symbol=%s)", mode, self._symbol)
        return self.status()

    async def stop(self) -> BotStatus:
        """Stop the pipeline and release the streamer, transitioning to ``STOPPED`` (R2.5)."""
        await self._streamer.stop()
        self._state = BotState.STOPPED
        logger.info("Bot stopped (symbol=%s)", self._symbol)
        return self.status()

    def status(self) -> BotStatus:
        """Return the current :class:`BotState`, active mode, and symbol (R2.6)."""
        return BotStatus(
            state=self._state,
            mode=self._engine.get_active_name(),
            symbol=self._symbol,
        )

    def _on_market_data(self, datum: Bar | Quote) -> None:
        """Handle one live market-data datum: drive engine + executor (pipeline).

        The streamer delivers either a :class:`Bar` or a :class:`Quote`; the type
        is distinguished with ``isinstance``:

        - A :class:`Bar` is appended to the rolling buffer.
        - A :class:`Quote` becomes the current quote.

        On every datum, ``engine.generate(bars, quote)`` produces a ``Signal``
        that is passed to ``executor.execute_signal(signal)``. The whole body is
        wrapped in a try/except that logs and continues so a single bad tick
        never stops the bot (Error Handling: per-tick resilience).

        Note: ``position_manager.on_quote`` is subscribed to the streamer
        independently (in :meth:`start`), so quotes reach it directly; this
        handler focuses on the engine/executor path.
        """
        try:
            if isinstance(datum, Bar):
                self._bars.append(datum)
            elif isinstance(datum, Quote):
                self._last_quote = datum

            signal = self._engine.generate(list(self._bars), self._last_quote)
            self._executor.execute_signal(signal)
        except Exception:  # noqa: BLE001 - one bad tick must never stop the bot
            logger.exception(
                "Error handling market data tick (symbol=%s); continuing",
                self._symbol,
            )
