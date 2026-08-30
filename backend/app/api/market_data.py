"""Optional historical-bars HTTP router (Task 6, data-feed spec).

Exposes ``GET /market-data/bars`` as a convenience REST surface over
:class:`HistoricalDataService`. The handler is thin: it wires the repository,
factory and service per request (same pattern as the credentials router) and
delegates to ``get_bars``. Domain errors bubble up to the ``exception handlers``
registered in ``app/main.py``, which translate each cause to a distinguishable
HTTP status + stable ``error_code`` (see the Error Handling table in design.md):

    - ``InvalidTimeframeError`` -> 400 ``invalid_timeframe`` (R1.4)
    - ``InvalidRangeError``     -> 400 ``invalid_range`` (R1.5)
    - ``CredentialsRequiredError`` -> 409 ``no_credentials`` (R1.8)
    - ``TransientAlpacaError``  -> 502 ``transient_error`` (R1.9)

The internal domain format stays the ``Bar`` dataclass; each ``Bar`` is mapped
to the Pydantic :class:`BarOut` mirror for serialization (R3.1).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.market_data import BarOut
from app.services.alpaca_client.factory import AlpacaClientFactory
from app.services.alpaca_client.repository import CredentialRepository
from app.services.data_feed.historical import HistoricalDataService
from app.services.data_feed.models import Bar

router = APIRouter(prefix="/market-data", tags=["market-data"])


def _build_historical_service(db: Session, settings: Settings) -> HistoricalDataService:
    """Wire repository + factory + historical service for a single request."""
    repository = CredentialRepository(db)
    factory = AlpacaClientFactory(repository, settings)
    return HistoricalDataService(factory)


def _to_bar_out(bar: Bar) -> BarOut:
    """Map an internal :class:`Bar` dataclass to the serializable :class:`BarOut`."""
    return BarOut(
        timestamp=bar.timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )


@router.get("/bars", response_model=list[BarOut])
def get_bars(
    timeframe: str = Query(...),
    start: datetime = Query(...),
    end: datetime = Query(...),
    symbol: str = Query("BTC/USD"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[BarOut]:
    """Fetch historical BTC/USD bars ordered ascending (R1.1, R1.2).

    Validation and failure classification live in the service and the global
    exception handlers; this handler only wires dependencies and maps the
    resulting :class:`Bar` list to :class:`BarOut`.
    """
    service = _build_historical_service(db, settings)
    bars = service.get_bars(symbol, timeframe, start, end)
    return [_to_bar_out(bar) for bar in bars]
