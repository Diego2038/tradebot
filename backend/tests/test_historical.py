"""Pruebas de ``HistoricalDataService.get_bars`` (Tarea 4).

El SDK de Alpaca se stubbea por completo vía ``sys.modules`` ANTES de importar
el servicio, para no depender de la firma real ni realizar red. Se stubbean:

- ``alpaca.trading.client`` (``TradingClient`` mínimo; el factory lo importa a
  nivel módulo).
- ``alpaca.data.historical`` (``CryptoHistoricalDataClient``).
- ``alpaca.data.requests`` (``CryptoBarsRequest``, import perezoso del servicio).
- ``alpaca.data.timeframe`` (``TimeFrame`` / ``TimeFrameUnit``, usados por
  ``to_alpaca_timeframe``).

El factory se mockea con ``unittest.mock.Mock`` exponiendo
``build_crypto_data_client``. El servicio obtiene el cliente vía ese método y
pide las barras con ``client.get_crypto_bars(request)``; en las pruebas el
cliente stub devuelve un objeto con atributo ``.data`` (``dict[symbol, list]``)
—coincidiendo con el ``BarSet`` de alpaca-py— o una lista vacía para "sin datos".

Casos:
- (a) timeframe inválido -> ``InvalidTimeframeError`` y el factory NUNCA se llama.
- (b) rango inválido (start > end) -> ``InvalidRangeError`` y el factory NUNCA se llama.
- (c) sin credenciales: ``build_crypto_data_client`` lanza
  ``CredentialsRequiredError`` -> ``get_bars`` lo propaga.
- (d) barras crudas desordenadas -> ``list[Bar]`` ordenada asc y normalizada; y
  caso sin datos -> ``[]``.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar el servicio.
# ---------------------------------------------------------------------------


class _FakeCryptoHistoricalDataClient:
    """Sustituto de alpaca.data.historical.CryptoHistoricalDataClient."""

    def __init__(self, api_key=None, secret_key=None, *args, **kwargs):
        self.api_key = api_key
        self.secret_key = secret_key

    def get_crypto_bars(self, request):  # pragma: no cover - sobreescrito en tests
        raise NotImplementedError


class _FakeCryptoBarsRequest:
    """Sustituto de alpaca.data.requests.CryptoBarsRequest.

    Acepta los kwargs que usa el servicio y los guarda para inspección.
    """

    def __init__(
        self,
        symbol_or_symbols=None,
        timeframe=None,
        start=None,
        end=None,
        page_token=None,
        **kwargs,
    ):
        self.symbol_or_symbols = symbol_or_symbols
        self.timeframe = timeframe
        self.start = start
        self.end = end
        self.page_token = page_token
        self.kwargs = kwargs


class _FakeTimeFrameUnit:
    Minute = "Min"
    Hour = "Hour"
    Day = "Day"


class _FakeTimeFrame:
    def __init__(self, amount, unit):
        self.amount = amount
        self.unit = unit


def _install_alpaca_stub() -> None:
    """Instala paquetes stub de alpaca en sys.modules de forma idempotente."""
    if "alpaca" not in sys.modules:
        alpaca_pkg = types.ModuleType("alpaca")
        alpaca_pkg.__path__ = []
        sys.modules["alpaca"] = alpaca_pkg

    # --- alpaca.trading.client (mínimo; el factory lo importa a nivel módulo) --
    if "alpaca.trading.client" not in sys.modules:
        trading_pkg = types.ModuleType("alpaca.trading")
        trading_pkg.__path__ = []
        trading_client_mod = types.ModuleType("alpaca.trading.client")

        class TradingClient:
            def __init__(self, api_key=None, secret_key=None, paper=True, **kwargs):
                self._api_key = api_key
                self._secret_key = secret_key
                self._paper = paper

            def get_account(self):  # pragma: no cover - no se usa aquí
                raise NotImplementedError

        trading_client_mod.TradingClient = TradingClient
        sys.modules["alpaca.trading"] = trading_pkg
        sys.modules["alpaca.trading.client"] = trading_client_mod

    # --- alpaca.data (paquete) ---
    if "alpaca.data" not in sys.modules:
        data_pkg = types.ModuleType("alpaca.data")
        data_pkg.__path__ = []
        sys.modules["alpaca.data"] = data_pkg

    # --- alpaca.data.historical.CryptoHistoricalDataClient ---
    if "alpaca.data.historical" not in sys.modules:
        historical_mod = types.ModuleType("alpaca.data.historical")
        historical_mod.CryptoHistoricalDataClient = _FakeCryptoHistoricalDataClient
        sys.modules["alpaca.data.historical"] = historical_mod

    # --- alpaca.data.requests.CryptoBarsRequest ---
    if "alpaca.data.requests" not in sys.modules:
        requests_mod = types.ModuleType("alpaca.data.requests")
        requests_mod.CryptoBarsRequest = _FakeCryptoBarsRequest
        sys.modules["alpaca.data.requests"] = requests_mod

    # --- alpaca.data.timeframe.TimeFrame / TimeFrameUnit ---
    if "alpaca.data.timeframe" not in sys.modules:
        timeframe_mod = types.ModuleType("alpaca.data.timeframe")
        timeframe_mod.TimeFrame = _FakeTimeFrame
        timeframe_mod.TimeFrameUnit = _FakeTimeFrameUnit
        sys.modules["alpaca.data.timeframe"] = timeframe_mod


_install_alpaca_stub()

from app.services.alpaca_client.errors import (  # noqa: E402
    CredentialsRequiredError,
    TransientAlpacaError,
)
from app.services.data_feed.errors import (  # noqa: E402
    InvalidRangeError,
    InvalidTimeframeError,
)
from app.services.data_feed.historical import HistoricalDataService  # noqa: E402
from app.services.data_feed.models import Bar  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SYMBOL = "BTC/USD"


class _RawBar:
    """Barra cruda tipo SDK (objeto con atributos)."""

    def __init__(self, timestamp, open_, high, low, close, volume):
        self.symbol = SYMBOL
        self.timestamp = timestamp
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


class _FakeBarSet:
    """Sustituto del ``BarSet`` de alpaca-py: expone ``.data`` (dict por símbolo)."""

    def __init__(self, bars_by_symbol, next_page_token=None):
        self.data = bars_by_symbol
        self.next_page_token = next_page_token


def _ts(day: int) -> datetime:
    return datetime(2024, 1, day, tzinfo=timezone.utc)


def _make_factory(client=None, side_effect=None):
    """Factory mockeado con ``build_crypto_data_client`` como espía."""
    factory = mock.Mock()
    if side_effect is not None:
        factory.build_crypto_data_client.side_effect = side_effect
    else:
        factory.build_crypto_data_client.return_value = client
    return factory


# ---------------------------------------------------------------------------
# (a) timeframe inválido -> InvalidTimeframeError, factory NUNCA llamado (R1.4)
# ---------------------------------------------------------------------------


def test_invalid_timeframe_raises_without_calling_alpaca():
    factory = _make_factory(client=mock.Mock())
    service = HistoricalDataService(factory)

    with pytest.raises(InvalidTimeframeError):
        service.get_bars(SYMBOL, "7Min", _ts(1), _ts(2))

    factory.build_crypto_data_client.assert_not_called()


# ---------------------------------------------------------------------------
# (b) rango inválido (start > end) -> InvalidRangeError, factory NUNCA llamado (R1.5)
# ---------------------------------------------------------------------------


def test_invalid_range_start_after_end_raises_without_calling_alpaca():
    factory = _make_factory(client=mock.Mock())
    service = HistoricalDataService(factory)

    with pytest.raises(InvalidRangeError):
        service.get_bars(SYMBOL, "1Min", _ts(5), _ts(2))

    factory.build_crypto_data_client.assert_not_called()


def test_invalid_range_missing_date_raises_without_calling_alpaca():
    factory = _make_factory(client=mock.Mock())
    service = HistoricalDataService(factory)

    with pytest.raises(InvalidRangeError):
        service.get_bars(SYMBOL, "1Min", None, _ts(2))

    factory.build_crypto_data_client.assert_not_called()


# ---------------------------------------------------------------------------
# (c) sin credenciales -> propaga CredentialsRequiredError (R1.8)
# ---------------------------------------------------------------------------


def test_no_credentials_propagates_credentials_required_error():
    factory = _make_factory(side_effect=CredentialsRequiredError("no credentials"))
    service = HistoricalDataService(factory)

    with pytest.raises(CredentialsRequiredError):
        service.get_bars(SYMBOL, "1Min", _ts(1), _ts(2))

    factory.build_crypto_data_client.assert_called_once()


# ---------------------------------------------------------------------------
# (d) barras desordenadas -> lista ordenada y normalizada (R1.1, R1.2);
#     sin datos -> [] (R1.3)
# ---------------------------------------------------------------------------


def test_returns_sorted_normalized_bars():
    # Barras crudas fuera de orden (día 3, 1, 2).
    raw = [
        _RawBar(_ts(3), 3.0, 3.5, 2.9, 3.2, 30.0),
        _RawBar(_ts(1), 1.0, 1.5, 0.9, 1.2, 10.0),
        _RawBar(_ts(2), 2.0, 2.5, 1.9, 2.2, 20.0),
    ]
    client = _FakeCryptoHistoricalDataClient()
    client.get_crypto_bars = mock.Mock(
        return_value=_FakeBarSet({SYMBOL: raw})
    )
    factory = _make_factory(client=client)
    service = HistoricalDataService(factory)

    bars = service.get_bars(SYMBOL, "1Min", _ts(1), _ts(4))

    assert all(isinstance(b, Bar) for b in bars)
    # Ordenadas ascendente por timestamp.
    assert [b.timestamp for b in bars] == [_ts(1), _ts(2), _ts(3)]
    # Normalizadas a Decimal.
    assert bars[0].open == Decimal("1.0")
    assert bars[2].close == Decimal("3.2")
    assert all(isinstance(b.close, Decimal) for b in bars)


def test_empty_range_returns_empty_list():
    client = _FakeCryptoHistoricalDataClient()
    client.get_crypto_bars = mock.Mock(return_value=_FakeBarSet({SYMBOL: []}))
    factory = _make_factory(client=client)
    service = HistoricalDataService(factory)

    result = service.get_bars(SYMBOL, "1Min", _ts(1), _ts(2))

    assert result == []


def test_no_symbol_key_returns_empty_list():
    # BarSet vacío (sin la clave del símbolo) -> [] sin error (R1.3).
    client = _FakeCryptoHistoricalDataClient()
    client.get_crypto_bars = mock.Mock(return_value=_FakeBarSet({}))
    factory = _make_factory(client=client)
    service = HistoricalDataService(factory)

    assert service.get_bars(SYMBOL, "1Min", _ts(1), _ts(2)) == []


# ---------------------------------------------------------------------------
# Paginación por token -> una sola lista ordenada sin duplicados (R1.6, R1.2)
# ---------------------------------------------------------------------------


def test_pagination_dedups_and_orders():
    page1 = _FakeBarSet(
        {SYMBOL: [_RawBar(_ts(1), 1, 1, 1, 1, 1), _RawBar(_ts(2), 2, 2, 2, 2, 2)]},
        next_page_token="tok-2",
    )
    page2 = _FakeBarSet(
        {
            SYMBOL: [
                _RawBar(_ts(2), 2, 2, 2, 2, 2),  # duplicado por timestamp
                _RawBar(_ts(3), 3, 3, 3, 3, 3),
            ]
        },
        next_page_token=None,
    )
    client = _FakeCryptoHistoricalDataClient()
    client.get_crypto_bars = mock.Mock(side_effect=[page1, page2])
    factory = _make_factory(client=client)
    service = HistoricalDataService(factory)

    bars = service.get_bars(SYMBOL, "1Min", _ts(1), _ts(4))

    assert [b.timestamp for b in bars] == [_ts(1), _ts(2), _ts(3)]
    assert client.get_crypto_bars.call_count == 2


# ---------------------------------------------------------------------------
# Fallo transitorio -> TransientAlpacaError (R1.9)
# ---------------------------------------------------------------------------


def test_transient_failure_raises_transient_alpaca_error():
    client = _FakeCryptoHistoricalDataClient()
    client.get_crypto_bars = mock.Mock(side_effect=TimeoutError("read timed out"))
    factory = _make_factory(client=client)
    service = HistoricalDataService(factory)

    with pytest.raises(TransientAlpacaError):
        service.get_bars(SYMBOL, "1Min", _ts(1), _ts(2))
