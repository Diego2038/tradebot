"""Historical BTC/USD bars service (R1).

``HistoricalDataService.get_bars`` returns normalized BTC/USD bars ordered by
timestamp ascending (R1.1, R1.2). It validates the requested timeframe and date
range purely in-process and raises BEFORE any Alpaca call (R1.4, R1.5), obtains
the authenticated data client exclusively through the ``AlpacaClientFactory``
(R1.7), normalizes each raw bar through the single :class:`Normalizer` choke
point, and paginates internally for large ranges, deduplicating by timestamp and
sorting ascending into a single list (R1.6).

Failure classification reuses spec ``01-alpaca-client``: missing credentials
propagate as :class:`CredentialsRequiredError` (R1.8, raised by the factory
before any network call) and timeout/network failures are surfaced as
:class:`TransientAlpacaError` (R1.9) without interrupting the backend process.
No data for a valid range yields ``[]`` (R1.3).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.services.alpaca_client.errors import (
    CredentialsRequiredError,
    TransientAlpacaError,
)
from app.services.data_feed.errors import (
    InvalidRangeError,
    InvalidTimeframeError,
)
from app.services.data_feed.models import Bar
from app.services.data_feed.normalizer import Normalizer
from app.services.data_feed.timeframes import (
    SUPPORTED_TIMEFRAMES,
    Timeframe,
    to_alpaca_timeframe,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.alpaca_client.factory import AlpacaClientFactory

logger = logging.getLogger(__name__)

# Default asset for this phase (paper-only BTC/USD).
DEFAULT_SYMBOL = "BTC/USD"

# Safety cap on the number of pagination iterations. Alpaca returns at most
# 10,000 bars per page; this bounds the loop so a misbehaving/looping page token
# can never spin forever while still comfortably covering realistic ranges.
_MAX_PAGES = 10_000


class HistoricalDataService:
    """Fetch and normalize historical BTC/USD bars from Alpaca (R1)."""

    def __init__(self, factory: "AlpacaClientFactory") -> None:
        self._factory = factory

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe | str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        """Return normalized BTC/USD bars ordered by timestamp ascending.

        Validation runs BEFORE any Alpaca call:
            - timeframe not in ``SUPPORTED_TIMEFRAMES`` -> ``InvalidTimeframeError`` (R1.4)
            - ``start``/``end`` missing, not ``datetime``, or ``start > end`` ->
              ``InvalidRangeError`` (R1.5)

        Behavior:
            - No data for the range -> ``[]`` (empty list, no error) (R1.3)
            - > 10,000 bars -> paginate internally into a single ordered list with
              no duplicates (R1.6, R1.2)
            - client obtained via ``factory.build_crypto_data_client()`` (R1.7)

        Raises:
            InvalidTimeframeError: unsupported timeframe; Alpaca NOT called (R1.4).
            InvalidRangeError: invalid/missing date range; Alpaca NOT called (R1.5).
            CredentialsRequiredError: no credentials configured; Alpaca NOT called
                (R1.8) — propagated from the factory.
            TransientAlpacaError: timeout (>10s) / network error (R1.9).
        """
        # --- Validation BEFORE touching the factory or SDK (R1.4, R1.5) --------
        self._validate_timeframe(timeframe)
        self._validate_range(start, end)

        # --- Obtain the client exclusively through the factory (R1.7) ----------
        # If no credentials are configured, build_crypto_data_client raises
        # CredentialsRequiredError here, before any Alpaca network call (R1.8).
        client = self._factory.build_crypto_data_client()

        alpaca_timeframe = to_alpaca_timeframe(timeframe)

        # --- Fetch (paginated) and normalize -----------------------------------
        raw_bars = self._fetch_all_pages(
            client=client,
            symbol=symbol,
            alpaca_timeframe=alpaca_timeframe,
            start=start,
            end=end,
        )

        normalized: list[Bar] = []
        for raw in raw_bars:
            bar = Normalizer.from_alpaca_bar(raw)
            if bar is None:
                # Malformed datum: discarded and logged by the Normalizer (R3.3).
                continue
            normalized.append(bar)

        # No data for the range -> empty list, no error (R1.3).
        if not normalized:
            return []

        # Deduplicate by timestamp and sort ascending into one list (R1.6, R1.2).
        deduped: dict[datetime, Bar] = {}
        for bar in normalized:
            deduped[bar.timestamp] = bar
        return sorted(deduped.values(), key=lambda b: b.timestamp)

    # ------------------------------------------------------------------ #
    # Validation helpers (in-process, no Alpaca call)                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_timeframe(timeframe: Timeframe | str) -> None:
        """Raise ``InvalidTimeframeError`` if timeframe is unsupported (R1.4)."""
        value = timeframe.value if isinstance(timeframe, Timeframe) else timeframe
        if value not in SUPPORTED_TIMEFRAMES:
            raise InvalidTimeframeError(
                f"unsupported timeframe: {timeframe!r}; "
                f"supported: {sorted(SUPPORTED_TIMEFRAMES)}"
            )

    @staticmethod
    def _validate_range(start: Any, end: Any) -> None:
        """Raise ``InvalidRangeError`` for a missing/unparseable/invalid range (R1.5)."""
        if start is None or end is None:
            raise InvalidRangeError("start and end are required")
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            raise InvalidRangeError(
                "start and end must be datetime instances"
            )
        if start > end:
            raise InvalidRangeError("start must not be after end")

    # ------------------------------------------------------------------ #
    # Alpaca fetch with internal pagination                              #
    # ------------------------------------------------------------------ #

    def _fetch_all_pages(
        self,
        client: Any,
        symbol: str,
        alpaca_timeframe: Any,
        start: datetime,
        end: datetime,
    ) -> list[Any]:
        """Fetch raw bars for ``symbol``, following pagination until exhausted.

        Alpaca returns at most 10,000 bars per page. This loops using the SDK's
        page token when present, or by advancing ``start`` past the last returned
        bar timestamp, accumulating raw bars until no further page remains
        (R1.6). Timeout/network failures are classified as
        :class:`TransientAlpacaError` (R1.9). Returns the raw bars; normalization,
        dedup and ordering happen in :meth:`get_bars`.
        """
        from alpaca.data.requests import CryptoBarsRequest

        raw_bars: list[Any] = []
        page_token: str | None = None
        # Tracks whether the SDK's token-based pagination is in play. Once a page
        # yields a next-page token, we follow tokens exclusively; a subsequent
        # tokenless page then means "no more pages" (do NOT fall back to
        # start-advancing, which would re-request the same window and loop).
        using_tokens = False
        page_start = start
        pages = 0

        while pages < _MAX_PAGES:
            pages += 1

            request_kwargs: dict[str, Any] = {
                "symbol_or_symbols": symbol,
                "timeframe": alpaca_timeframe,
                "start": page_start,
                "end": end,
            }
            if page_token is not None:
                request_kwargs["page_token"] = page_token

            try:
                request = CryptoBarsRequest(**request_kwargs)
            except TypeError:
                # Older/newer SDKs may not accept ``page_token`` on the request;
                # fall back to a request without it and rely on start-advancing.
                request_kwargs.pop("page_token", None)
                request = CryptoBarsRequest(**request_kwargs)

            try:
                result = client.get_crypto_bars(request)
            except Exception as exc:  # noqa: BLE001 - classify then re-raise
                self._classify_and_raise(exc)

            page_bars = self._extract_bars(result, symbol)
            if not page_bars:
                break
            raw_bars.extend(page_bars)

            # Prefer the SDK's next-page token if the result exposes one.
            next_token = self._extract_next_page_token(result)
            if next_token:
                using_tokens = True
                page_token = next_token
                continue

            # Token-based pagination has finished (tokens were used and this page
            # has no next token) -> done.
            if using_tokens:
                break

            # No token mechanism available: advance past the last bar timestamp.
            # Stop when we cannot advance (single page / no further data) to
            # avoid re-requesting the same window forever.
            last_ts = self._last_timestamp(page_bars)
            if last_ts is None or last_ts <= page_start:
                break
            page_start = last_ts
            page_token = None

        return raw_bars

    @staticmethod
    def _extract_bars(result: Any, symbol: str) -> list[Any]:
        """Pull the raw bar list for ``symbol`` from an Alpaca ``BarSet``/dict.

        Handles both the SDK's ``BarSet`` (``.data`` dict keyed by symbol) and a
        plain dict. When the container is keyed by symbol, the requested symbol's
        list is returned; a flat list is returned as-is.
        """
        if result is None:
            return []

        # SDK BarSet exposes ``.data`` (dict[symbol, list[bar]]).
        data = getattr(result, "data", None)
        if data is None and isinstance(result, dict):
            data = result

        if isinstance(data, dict):
            bars = data.get(symbol)
            if bars is None:
                # Some containers may key differently; if there is a single
                # entry, use it. Otherwise treat as no data.
                if len(data) == 1:
                    bars = next(iter(data.values()))
                else:
                    return []
            return list(bars) if bars else []

        # Result is directly an iterable of bars.
        if isinstance(result, (list, tuple)):
            return list(result)

        return []

    @staticmethod
    def _extract_next_page_token(result: Any) -> str | None:
        """Read a next-page token from the result if the SDK exposes one."""
        for attr in ("next_page_token", "next_token", "page_token"):
            token = getattr(result, attr, None)
            if isinstance(token, str) and token:
                return token
        if isinstance(result, dict):
            for key in ("next_page_token", "next_token", "page_token"):
                token = result.get(key)
                if isinstance(token, str) and token:
                    return token
        return None

    @staticmethod
    def _last_timestamp(bars: list[Any]) -> datetime | None:
        """Return the maximum parseable timestamp among ``bars`` (for advancing)."""
        latest: datetime | None = None
        for raw in bars:
            if isinstance(raw, dict):
                ts = raw.get("timestamp")
            else:
                ts = getattr(raw, "timestamp", None)
            if isinstance(ts, datetime):
                if latest is None or ts > latest:
                    latest = ts
        return latest

    @staticmethod
    def _classify_and_raise(error: Exception) -> None:
        """Classify an Alpaca failure; raise ``TransientAlpacaError`` for timeout/net.

        Timeouts (>10s) and network errors are surfaced as
        :class:`TransientAlpacaError` (R1.9), distinguishable from validation
        errors, without interrupting the backend process. Any other error is
        re-raised unchanged.
        """
        if _is_transient_error(error):
            raise TransientAlpacaError(
                "temporary problem reaching Alpaca, try again"
            ) from error
        raise error


def _is_transient_error(error: Exception) -> bool:
    """Report whether ``error`` is a timeout or network failure (type or name).

    Checks the MRO by class name so we do not couple to ``requests``/``httpx``
    being installed, and also recognizes Python's built-in ``TimeoutError`` and
    ``ConnectionError``. Mirrors the classification used by the factory.
    """
    if isinstance(error, (TimeoutError, ConnectionError)):
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
