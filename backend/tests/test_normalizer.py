"""Pruebas del ``Normalizer`` (Tarea 2.2).

Cubren la conversión de datos crudos de Alpaca (objetos con atributos o dicts) al
formato interno único ``Bar`` / ``Quote`` (R3.2) y el descarte con log de datos
malformados (R3.3):

- (a) una barra representativa -> ``Bar`` con ``Decimal`` y ``datetime`` tz-aware.
- (b) un quote representativo -> ``Quote`` correcto.
- (c) una barra sin un campo requerido (``close``) -> ``None`` + log de descarte.
- (d) un quote sin ``price`` -> ``None`` + log de descarte.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.services.data_feed.models import Bar, Quote
from app.services.data_feed.normalizer import Normalizer


class _Raw:
    """Objeto simple con atributos, imitando un datum del SDK de Alpaca."""

    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


# ---------------------------------------------------------------------------
# (a) Barra representativa -> Bar correcto (R3.1, R3.2)
# ---------------------------------------------------------------------------


def test_from_alpaca_bar_normalizes_object_to_bar() -> None:
    raw = _Raw(
        symbol="BTC/USD",
        timestamp=datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        open=42000.5,
        high=42500.25,
        low=41800.0,
        close=42300.75,
        volume=12.5,
    )

    bar = Normalizer.from_alpaca_bar(raw)

    assert isinstance(bar, Bar)
    assert bar.timestamp == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert bar.timestamp.tzinfo is not None
    # Los floats se convierten vía str() para preservar precisión monetaria.
    assert bar.open == Decimal("42000.5")
    assert bar.high == Decimal("42500.25")
    assert bar.low == Decimal("41800.0")
    assert bar.close == Decimal("42300.75")
    assert bar.volume == Decimal("12.5")
    assert all(
        isinstance(v, Decimal)
        for v in (bar.open, bar.high, bar.low, bar.close, bar.volume)
    )


def test_from_alpaca_bar_accepts_dict_and_iso_string_timestamp() -> None:
    raw = {
        "symbol": "BTC/USD",
        "timestamp": "2024-01-02T03:04:05Z",
        "open": "42000.50",
        "high": "42500.25",
        "low": "41800.00",
        "close": "42300.75",
        "volume": "12.5",
    }

    bar = Normalizer.from_alpaca_bar(raw)

    assert isinstance(bar, Bar)
    assert bar.timestamp == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert bar.close == Decimal("42300.75")


def test_from_alpaca_bar_assumes_utc_for_naive_timestamp() -> None:
    raw = {
        "timestamp": datetime(2024, 1, 2, 3, 4, 5),  # naive
        "open": 1,
        "high": 2,
        "low": 1,
        "close": 2,
        "volume": 3,
    }

    bar = Normalizer.from_alpaca_bar(raw)

    assert isinstance(bar, Bar)
    assert bar.timestamp.tzinfo is timezone.utc
    assert bar.timestamp == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# (b) Quote representativo -> Quote correcto (R3.1, R3.2)
# ---------------------------------------------------------------------------


def test_from_alpaca_quote_normalizes_to_quote() -> None:
    raw = _Raw(
        symbol="BTC/USD",
        timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        price=43210.99,
    )

    quote = Normalizer.from_alpaca_quote(raw)

    assert isinstance(quote, Quote)
    assert quote.timestamp == datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert quote.timestamp.tzinfo is not None
    assert quote.price == Decimal("43210.99")
    assert isinstance(quote.price, Decimal)


# ---------------------------------------------------------------------------
# (c) Barra sin campo requerido -> None + log de descarte (R3.3)
# ---------------------------------------------------------------------------


def test_from_alpaca_bar_missing_close_returns_none_and_logs(caplog) -> None:
    raw = {
        "symbol": "BTC/USD",
        "timestamp": datetime(2024, 1, 2, tzinfo=timezone.utc),
        "open": 1,
        "high": 2,
        "low": 1,
        # 'close' ausente
        "volume": 3,
    }

    with caplog.at_level(logging.WARNING):
        result = Normalizer.from_alpaca_bar(raw)

    assert result is None
    assert any(
        "close" in record.getMessage() and "Discarding" in record.getMessage()
        for record in caplog.records
    )


def test_from_alpaca_bar_unparseable_number_returns_none() -> None:
    raw = {
        "timestamp": datetime(2024, 1, 2, tzinfo=timezone.utc),
        "open": "not-a-number",
        "high": 2,
        "low": 1,
        "close": 2,
        "volume": 3,
    }

    assert Normalizer.from_alpaca_bar(raw) is None


# ---------------------------------------------------------------------------
# (d) Quote sin price -> None + log de descarte (R3.3)
# ---------------------------------------------------------------------------


def test_from_alpaca_quote_missing_price_returns_none_and_logs(caplog) -> None:
    raw = _Raw(
        symbol="BTC/USD",
        timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        # price ausente -> getattr devuelve None
        price=None,
    )

    with caplog.at_level(logging.WARNING):
        result = Normalizer.from_alpaca_quote(raw)

    assert result is None
    assert any(
        "price" in record.getMessage() and "Discarding" in record.getMessage()
        for record in caplog.records
    )
