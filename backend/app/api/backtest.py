"""REST router for the backtest engine (spec 05-backtest-engine).

Exposes ``POST /backtest`` as a thin REST surface over :class:`BacktestEngine`.
The handler wires the historical-data service per request (same pattern as the
market-data router: repository -> factory -> service), fetches the ordered bars,
resolves the strategy by name through the shared spec-03 registry (R3.3), replays
them through the engine, and maps the domain :class:`BacktestResult` to the
serializable :class:`BacktestResultOut`.

Two interpretability affordances live here (both additive, neither touches the
engine's accounting model):

- The body accepts an optional ``qty`` (position size per simulated trade). When
  omitted the engine's own default (``0.001`` BTC) applies; that default is only
  ~0.08% of the simulated ``STARTING_EQUITY``, which makes the percentage metrics
  microscopic. ``qty`` is validated with ``gt=0`` in the schema, so a non-positive
  value is rejected with ``422`` at the edge (like an out-of-range ``mode``) rather
  than raising a new domain error.
- The response carries the derived absolute figures ``starting_equity``,
  ``net_profit`` and ``final_equity`` alongside the four domain metrics, so the
  result can be read at a glance.

The router is deliberately thin: validation and failure classification live in the
services and in the global exception handlers registered in ``app/main.py``, which
translate each cause to a distinguishable HTTP status + stable ``error_code``:

    - ``InvalidTimeframeError``    -> 400 ``invalid_timeframe`` (from data-feed)
    - ``InvalidRangeError``        -> 400 ``invalid_range`` (from data-feed; NOTE the
                                      historical service validates the range BEFORE
                                      the engine, so a ``start > end`` request maps
                                      to ``invalid_range`` here, not
                                      ``invalid_date_range``)
    - ``CredentialsRequiredError`` -> 409 ``no_credentials`` (from data-feed/factory)
    - ``TransientAlpacaError``     -> 502 ``transient_error`` (from alpaca client)
    - ``UnknownStrategyError``     -> 400 ``invalid_mode`` (from strategy registry)
    - ``InvalidDateRangeError``    -> 400 ``invalid_date_range`` (from engine)
    - ``InvalidActionError``       -> 400 ``invalid_action`` (from engine)

None of these are caught here; they propagate to the app-level handlers so error
mapping stays in a single place (``main.py``).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.backtest import (
    BacktestResultOut,
    BacktestRunRequest,
    SimulatedTradeOut,
)
from app.services.alpaca_client.factory import AlpacaClientFactory
from app.services.alpaca_client.repository import CredentialRepository
from app.services.backtest.constants import STARTING_EQUITY
from app.services.backtest.engine import BacktestEngine
from app.services.backtest.models import BacktestRequest, BacktestResult
from app.services.data_feed.historical import HistoricalDataService
from app.services.strategies.registry import build_default_engine

router = APIRouter(prefix="/backtest", tags=["backtest"])


def _build_historical_service(db: Session, settings: Settings) -> HistoricalDataService:
    """Wire repository + factory + historical service for a single request.

    Same wiring pattern as the market-data router.
    """
    repository = CredentialRepository(db)
    factory = AlpacaClientFactory(repository, settings)
    return HistoricalDataService(factory)


def _to_result_out(result: BacktestResult, bars_evaluated: int) -> BacktestResultOut:
    """Map the domain :class:`BacktestResult` to the serializable output schema.

    Also derives the absolute figures for interpretability. ``net_profit`` sums the
    ``realized_profit`` of the exit trades only -- those are the round-trip closes,
    the ONLY trades that move simulated equity, so the sum is coherent with
    ``trade_count``. Entry trades (and a SELL recorded while flat) carry
    ``realized_profit=None`` and contribute nothing, which is why ``len(trades)`` can
    exceed ``trade_count`` without affecting the money figures.
    """
    net_profit = sum(
        (
            trade.realized_profit
            for trade in result.trades
            if trade.realized_profit is not None
        ),
        Decimal("0"),
    )
    return BacktestResultOut(
        total_return=result.total_return,
        trade_count=result.trade_count,
        win_rate=result.win_rate,
        max_drawdown=result.max_drawdown,
        starting_equity=STARTING_EQUITY,
        net_profit=net_profit,
        final_equity=STARTING_EQUITY + net_profit,
        trades=[
            SimulatedTradeOut(
                side=trade.side,
                qty=trade.qty,
                price=trade.price,
                timestamp=trade.timestamp,
                reason=trade.reason,
                realized_profit=trade.realized_profit,
            )
            for trade in result.trades
        ],
        bars_evaluated=bars_evaluated,
    )


@router.post("", response_model=BacktestResultOut)
def run_backtest(
    body: BacktestRunRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BacktestResultOut:
    """Fetch historical bars and replay them through the backtest engine.

    Flow:
      1. Wire the historical service and fetch the ordered bars. Timeframe/range
         validation and credential/transient failures are classified in the
         service and mapped by the global handlers (``invalid_timeframe``,
         ``invalid_range``, ``no_credentials``, ``transient_error``) — not caught
         here.
      2. Build the engine over the shared spec-03 registry (``random`` /
         ``predictive`` registered), resolving the strategy by name exactly as the
         live pipeline does (R3.3). The optional ``qty`` in the body overrides the
         engine's default position size; when absent the engine default (0.001 BTC)
         applies. A non-positive ``qty`` never gets here -- the schema rejects it
         with ``422``.
      3. Replay. An unregistered mode surfaces ``UnknownStrategyError`` (``400
         invalid_mode``); a bad date range surfaces ``InvalidDateRangeError``
         (``400 invalid_date_range``); an out-of-range strategy action surfaces
         ``InvalidActionError`` (``400 invalid_action``). All propagate to the
         app-level handlers.
      4. Map the result to :class:`BacktestResultOut`, reporting ``bars_evaluated``
         plus the derived absolute figures (``starting_equity``, ``net_profit``,
         ``final_equity``) for transparency and interpretability.
    """
    service = _build_historical_service(db, settings)
    bars = service.get_bars(body.symbol, body.timeframe, body.start, body.end)

    # Respect the requested position size; fall back to the engine's own default so
    # the default stays owned by the domain, not duplicated here.
    engine = (
        BacktestEngine(build_default_engine())
        if body.qty is None
        else BacktestEngine(build_default_engine(), qty=body.qty)
    )
    bt_request = BacktestRequest(
        strategy_name=body.mode,
        symbol=body.symbol,
        timeframe=body.timeframe,
        start=body.start,
        end=body.end,
        seed=body.seed,
    )
    result = engine.run(bt_request, bars)
    return _to_result_out(result, bars_evaluated=len(bars))
