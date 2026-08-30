"""Single conversion point from raw Alpaca data to the internal format.

The ``Normalizer`` is the only place where raw Alpaca data (SDK objects or
dicts) is converted into the SDK-independent :class:`Bar` / :class:`Quote`
formats. Every datum — historical or streaming — passes through here before
reaching any consumer, guaranteeing SDK independence and consistent
malformed-data handling (R3.2, R3.3).

When any required field is missing, ``None``, or unparseable, the method logs
the discard (with symbol and reason when available, never secrets) and returns
``None`` so callers can discard-and-log uniformly (R3.3).
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.data_feed.models import Bar, Quote

logger = logging.getLogger(__name__)


def _get_field(raw: Any, name: str) -> Any:
    """Read a field defensively: attribute first, then dict key.

    Returns ``None`` when the field is absent under either access style.
    """
    if isinstance(raw, dict):
        return raw.get(name)
    return getattr(raw, name, None)


def _to_decimal(value: Any) -> Decimal | None:
    """Convert a numeric value to ``Decimal`` preserving precision.

    Accepts ``int``/``float``/``str``/``Decimal``. Floats are routed through
    ``str()`` to avoid binary float imprecision. Returns ``None`` when the value
    is missing or not parseable as a number.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        if isinstance(value, float):
            return Decimal(str(value))
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            return Decimal(stripped)
    except (InvalidOperation, ValueError):
        return None
    return None


def _to_utc_datetime(value: Any) -> datetime | None:
    """Normalize a timestamp to a timezone-aware ``datetime`` in UTC.

    Accepts a ``datetime`` (naive values are assumed to be UTC) or an ISO-8601
    parseable string. Returns ``None`` when the value is missing or unparseable.
    """
    if value is None:
        return None
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        # ``fromisoformat`` in 3.12 handles a trailing "Z".
        try:
            dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Normalizer:
    """Convert raw Alpaca data into the single internal format (R3.2)."""

    @staticmethod
    def from_alpaca_bar(raw: Any) -> Bar | None:
        """Convert a raw Alpaca bar to :class:`Bar`.

        Reads ``timestamp``, ``open``, ``high``, ``low``, ``close`` and
        ``volume`` defensively (attribute or dict key). Numbers are converted to
        ``Decimal`` (floats via ``str()``) and the timestamp to a UTC-aware
        ``datetime``. Returns ``None`` if any required field is missing/``None``/
        unparseable, logging the discard (R3.2, R3.3).
        """
        symbol = _get_field(raw, "symbol")

        timestamp = _to_utc_datetime(_get_field(raw, "timestamp"))
        open_ = _to_decimal(_get_field(raw, "open"))
        high = _to_decimal(_get_field(raw, "high"))
        low = _to_decimal(_get_field(raw, "low"))
        close = _to_decimal(_get_field(raw, "close"))
        volume = _to_decimal(_get_field(raw, "volume"))

        fields = {
            "timestamp": timestamp,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
        missing = [name for name, val in fields.items() if val is None]
        if missing:
            logger.warning(
                "Discarding malformed Alpaca bar (symbol=%s): "
                "missing/unparseable field(s): %s",
                symbol,
                ", ".join(missing),
            )
            return None

        return Bar(
            timestamp=timestamp,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )

    @staticmethod
    def from_alpaca_quote(raw: Any) -> Quote | None:
        """Convert a raw Alpaca quote/trade to :class:`Quote`.

        Reads ``timestamp`` and ``price`` defensively. Returns ``None`` if either
        is missing/``None``/unparseable, logging the discard (R3.2, R3.3).
        """
        symbol = _get_field(raw, "symbol")

        timestamp = _to_utc_datetime(_get_field(raw, "timestamp"))
        price = _to_decimal(_get_field(raw, "price"))

        fields = {"timestamp": timestamp, "price": price}
        missing = [name for name, val in fields.items() if val is None]
        if missing:
            logger.warning(
                "Discarding malformed Alpaca quote (symbol=%s): "
                "missing/unparseable field(s): %s",
                symbol,
                ", ".join(missing),
            )
            return None

        return Quote(timestamp=timestamp, price=price)
