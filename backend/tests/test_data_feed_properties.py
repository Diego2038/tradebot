"""Pruebas basadas en propiedades (Hypothesis) del data feed (Tarea 7).

Spec ``02-data-feed``. Ejercitan la lógica pura/determinista de la feature
(validación, normalización, orden, paginación, descarte de datos malformados y
esquema de backoff) con el SDK de Alpaca completamente stubbeado y SIN red.

Cada test lleva un comentario "Feature: 02-data-feed, Property N: ...".
Todas las propiedades corren con >= 100 iteraciones (@settings(max_examples=100))
y suprimen el health check de fixtures function-scoped cuando aplica.

Patrón de stub del SDK y del factory copiado de tests/test_historical.py:
- ``alpaca.trading.client`` (``TradingClient`` mínimo; el factory lo importa a
  nivel módulo al importar el streamer).
- ``alpaca.common.exceptions`` (``APIError``; el factory lo importa perezosamente
  al clasificar errores — se instala aquí para no depender del orden de colección).
- ``alpaca.data.requests`` (``CryptoBarsRequest``, import perezoso del servicio).
- ``alpaca.data.timeframe`` (``TimeFrame`` / ``TimeFrameUnit``).
El factory se mockea con ``unittest.mock.Mock`` exponiendo
``build_crypto_data_client``; el cliente stub expone
``get_crypto_bars(request)`` devolviendo un objeto con ``.data = {symbol: [...]}``.

NOTA de higiene de stubs: este archivo NO instala ``alpaca.data.historical`` ni
``alpaca.data.live`` a propósito. Otros tests (``test_factory_data.py``) hacen
``isinstance(..., _FakeCryptoHistoricalDataClient/_FakeCryptoDataStream)`` contra
SUS propias clases y son sensibles a quién registra primero ese submódulo. Como
aquí el factory siempre se mockea, no necesitamos esos clientes y dejamos que sea
``test_factory_data.py`` quien los registre, evitando contaminación entre tests.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar el servicio/streamer.
# ---------------------------------------------------------------------------


class _FakeAPIError(Exception):
    """Sustituto de alpaca.common.exceptions.APIError con status HTTP."""

    def __init__(self, message: str = "api error", status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class _StubCryptoDataClient:
    """Cliente de datos histórico simulado (NO registrado en sys.modules).

    Se usa localmente como valor de retorno de ``build_crypto_data_client`` (que
    siempre se mockea); no toca ``alpaca.data.historical`` para no contaminar
    ``test_factory_data.py``.
    """

    def get_crypto_bars(self, request):  # pragma: no cover - sobreescrito en tests
        raise NotImplementedError


class _FakeCryptoBarsRequest:
    """Sustituto de alpaca.data.requests.CryptoBarsRequest.

    Acepta los kwargs que usa el servicio (incluido ``page_token``) y los guarda.
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
    """Instala paquetes stub de alpaca en sys.modules de forma idempotente.

    Higiene de orden de colección: delegamos primero en el instalador de
    ``tests/test_factory.py`` para que su ``_FakeAPIError`` sea la clase canónica
    registrada en ``alpaca.common.exceptions`` (ese test construye sus errores
    con su propia clase local y el factory clasifica por ``isinstance`` contra la
    clase registrada). Así, independientemente de quién colecte primero, ambos
    ficheros comparten el mismo ``APIError`` y no se contaminan.
    """
    # Registra alpaca + trading.client + common.exceptions con la clase canónica
    # (idempotente: si test_factory ya corrió, no hace nada).
    from tests.test_factory import _install_alpaca_stub as _install_spec01_stub

    _install_spec01_stub()

    # Red de seguridad: si por cualquier motivo el paquete de excepciones no
    # quedó registrado, lo instalamos con nuestra propia clase.
    if "alpaca.common.exceptions" not in sys.modules:
        common_pkg = types.ModuleType("alpaca.common")
        common_pkg.__path__ = []
        exceptions_mod = types.ModuleType("alpaca.common.exceptions")
        exceptions_mod.APIError = _FakeAPIError
        sys.modules["alpaca.common"] = common_pkg
        sys.modules["alpaca.common.exceptions"] = exceptions_mod

    if "alpaca.data" not in sys.modules:
        data_pkg = types.ModuleType("alpaca.data")
        data_pkg.__path__ = []
        sys.modules["alpaca.data"] = data_pkg

    if "alpaca.data.requests" not in sys.modules:
        requests_mod = types.ModuleType("alpaca.data.requests")
        requests_mod.CryptoBarsRequest = _FakeCryptoBarsRequest
        sys.modules["alpaca.data.requests"] = requests_mod

    if "alpaca.data.timeframe" not in sys.modules:
        timeframe_mod = types.ModuleType("alpaca.data.timeframe")
        timeframe_mod.TimeFrame = _FakeTimeFrame
        timeframe_mod.TimeFrameUnit = _FakeTimeFrameUnit
        sys.modules["alpaca.data.timeframe"] = timeframe_mod


_install_alpaca_stub()

from app.services.data_feed.errors import (  # noqa: E402
    InvalidRangeError,
    InvalidTimeframeError,
)
from app.services.data_feed.historical import HistoricalDataService  # noqa: E402
from app.services.data_feed.models import Bar  # noqa: E402
from app.services.data_feed.normalizer import Normalizer  # noqa: E402
from app.services.data_feed.streaming import (  # noqa: E402
    INITIAL_BACKOFF,
    MAX_BACKOFF,
    _next_backoff,
)
from app.services.data_feed.timeframes import SUPPORTED_TIMEFRAMES  # noqa: E402


# ---------------------------------------------------------------------------
# Constantes / helpers comunes
# ---------------------------------------------------------------------------

SYMBOL = "BTC/USD"
_EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)

_PBT_SETTINGS = settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Ajustes para P5: incluye el camino >10000 barras, que puede tardar más que el
# deadline por defecto de Hypothesis (200ms) al normalizar/deduplicar miles de
# barras. Desactivamos el deadline (no medimos latencia aquí, sino corrección).
_PBT_SETTINGS_NO_DEADLINE = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Un timeframe soportado cualquiera basta para P1/P2/P5 (la validación es la
# misma para todos); tomamos uno estable.
_A_SUPPORTED_TF = "1Min"

# Nombres de los campos obligatorios de cada formato normalizado.
_BAR_REQUIRED_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")
_QUOTE_REQUIRED_FIELDS = ("timestamp", "price")


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


def _ts_from_minute(minute_offset: int) -> datetime:
    """Timestamp determinista desplazado ``minute_offset`` minutos desde la época."""
    return _EPOCH + timedelta(minutes=minute_offset)


def _make_factory(client=None, side_effect=None):
    """Factory mockeado con ``build_crypto_data_client`` como espía."""
    factory = mock.Mock()
    if side_effect is not None:
        factory.build_crypto_data_client.side_effect = side_effect
    else:
        factory.build_crypto_data_client.return_value = client
    return factory


def _client_returning(bars_by_symbol_or_barset):
    """Cliente stub cuyo ``get_crypto_bars`` devuelve el BarSet dado (una página)."""
    client = _StubCryptoDataClient()
    if isinstance(bars_by_symbol_or_barset, _FakeBarSet):
        result = bars_by_symbol_or_barset
    else:
        result = _FakeBarSet(bars_by_symbol_or_barset)
    client.get_crypto_bars = mock.Mock(return_value=result)
    return client


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Precios/volúmenes deterministas y sencillos de normalizar a Decimal.
_prices = st.integers(min_value=1, max_value=1_000_000)
_volumes = st.integers(min_value=0, max_value=1_000_000)
# Offsets de minuto únicos por lista -> timestamps distintos.
_minute_offsets = st.lists(
    st.integers(min_value=0, max_value=100_000),
    unique=True,
    max_size=40,
)


def _raw_bar_from_offset(offset: int) -> _RawBar:
    base = (offset % 100) + 1
    return _RawBar(
        timestamp=_ts_from_minute(offset),
        open_=float(base),
        high=float(base + 1),
        low=float(base - 0.5),
        close=float(base + 0.25),
        volume=float(base * 10),
    )


# ===========================================================================
# Property 1: la salida de get_bars son todo Bar (campos exactos) y ascendente.
# ===========================================================================


@_PBT_SETTINGS
@given(offsets=_minute_offsets)
def test_property_1_output_all_bars_and_sorted_ascending(offsets):
    # Feature: 02-data-feed, Property 1: Returned bars are normalized and
    # ascending -- para cualquier conjunto de barras crudas (en orden aleatorio)
    # con timeframe y rango válidos, cada elemento de get_bars es un Bar con
    # exactamente (timestamp, open, high, low, close, volume) y la lista queda
    # ordenada por timestamp ascendente.
    # Validates: Requirements 1.1, 1.2, 3.1, 3.2
    raw = [_raw_bar_from_offset(o) for o in offsets]
    # Desordenar de forma determinista (invertir) para no depender del orden de
    # entrada; get_bars debe ordenar siempre.
    raw = list(reversed(raw))

    client = _client_returning({SYMBOL: raw})
    factory = _make_factory(client=client)
    service = HistoricalDataService(factory)

    start = _EPOCH
    end = _ts_from_minute(200_000)
    bars = service.get_bars(SYMBOL, _A_SUPPORTED_TF, start, end)

    # Todos son Bar con exactamente los campos del formato.
    assert all(isinstance(b, Bar) for b in bars)
    for b in bars:
        assert set(vars(b).keys()) == set(_BAR_REQUIRED_FIELDS)

    # Ordenada ascendente por timestamp.
    timestamps = [b.timestamp for b in bars]
    assert timestamps == sorted(timestamps)

    # Sin pérdida de datos: hay tantos bars como timestamps únicos de entrada.
    assert len(bars) == len(offsets)


# ===========================================================================
# Property 2: rango válido sin datos -> [] y no lanza.
# ===========================================================================


@_PBT_SETTINGS
@given(
    start_offset=st.integers(min_value=0, max_value=10_000),
    span=st.integers(min_value=0, max_value=10_000),
    empty=st.sampled_from([{SYMBOL: []}, {}]),
)
def test_property_2_valid_range_no_data_returns_empty_list(start_offset, span, empty):
    # Feature: 02-data-feed, Property 2: A range with no data yields an empty
    # list -- para cualquier rango válido en el que el cliente mockeado no
    # devuelve barras, get_bars devuelve [] y no lanza error.
    # Validates: Requirements 1.3
    client = _client_returning(empty)
    factory = _make_factory(client=client)
    service = HistoricalDataService(factory)

    start = _ts_from_minute(start_offset)
    end = _ts_from_minute(start_offset + span)

    result = service.get_bars(SYMBOL, _A_SUPPORTED_TF, start, end)
    assert result == []


# ===========================================================================
# Property 3: timeframe/rango inválido -> error correcto y factory NUNCA llamado.
# ===========================================================================


# Timeframes fuera del set soportado (excluye por construcción los válidos).
_unsupported_timeframes = st.text(min_size=1, max_size=12).filter(
    lambda s: s not in SUPPORTED_TIMEFRAMES
)


@_PBT_SETTINGS
@given(tf=_unsupported_timeframes)
def test_property_3_invalid_timeframe_raises_without_calling_alpaca(tf):
    # Feature: 02-data-feed, Property 3: Invalid timeframe fails without calling
    # Alpaca -- para cualquier timeframe fuera del set soportado, get_bars lanza
    # InvalidTimeframeError y build_crypto_data_client NUNCA se invoca.
    # Validates: Requirements 1.4, 1.5, 1.7
    factory = _make_factory(client=mock.Mock())
    service = HistoricalDataService(factory)

    with pytest.raises(InvalidTimeframeError):
        service.get_bars(SYMBOL, tf, _EPOCH, _ts_from_minute(10))

    factory.build_crypto_data_client.assert_not_called()


@_PBT_SETTINGS
@given(
    start_offset=st.integers(min_value=1, max_value=10_000),
    delta=st.integers(min_value=1, max_value=10_000),
)
def test_property_3_invalid_range_start_after_end_raises_without_calling_alpaca(
    start_offset, delta
):
    # Feature: 02-data-feed, Property 3: Invalid range fails without calling
    # Alpaca -- para cualquier rango donde start > end, get_bars lanza
    # InvalidRangeError y build_crypto_data_client NUNCA se invoca.
    # Validates: Requirements 1.4, 1.5, 1.7
    factory = _make_factory(client=mock.Mock())
    service = HistoricalDataService(factory)

    start = _ts_from_minute(start_offset + delta)
    end = _ts_from_minute(start_offset)  # start estrictamente posterior a end

    with pytest.raises(InvalidRangeError):
        service.get_bars(SYMBOL, _A_SUPPORTED_TF, start, end)

    factory.build_crypto_data_client.assert_not_called()


@_PBT_SETTINGS
@given(missing=st.sampled_from(["start", "end", "both"]))
def test_property_3_missing_date_raises_without_calling_alpaca(missing):
    # Feature: 02-data-feed, Property 3: Missing date fails without calling
    # Alpaca -- una fecha ausente (None) produce InvalidRangeError sin invocar
    # el factory.
    # Validates: Requirements 1.4, 1.5, 1.7
    factory = _make_factory(client=mock.Mock())
    service = HistoricalDataService(factory)

    start = None if missing in ("start", "both") else _EPOCH
    end = None if missing in ("end", "both") else _ts_from_minute(10)

    with pytest.raises(InvalidRangeError):
        service.get_bars(SYMBOL, _A_SUPPORTED_TF, start, end)

    factory.build_crypto_data_client.assert_not_called()


# ===========================================================================
# Property 4: datum al que le falta un campo requerido -> Normalizer devuelve None.
# ===========================================================================


def _complete_bar_dict(seed: int) -> dict:
    return {
        "symbol": SYMBOL,
        "timestamp": _ts_from_minute(seed),
        "open": float(seed + 1),
        "high": float(seed + 2),
        "low": float(seed),
        "close": float(seed + 1),
        "volume": float(seed * 2),
    }


def _complete_quote_dict(seed: int) -> dict:
    return {
        "symbol": SYMBOL,
        "timestamp": _ts_from_minute(seed),
        "price": float(seed + 1),
    }


@_PBT_SETTINGS
@given(
    seed=st.integers(min_value=0, max_value=10_000),
    drop=st.sampled_from(_BAR_REQUIRED_FIELDS),
)
def test_property_4_bar_missing_required_field_returns_none(seed, drop):
    # Feature: 02-data-feed, Property 4: Malformed data is discarded and never
    # delivered -- para una barra cruda a la que le falta al menos un campo
    # requerido, Normalizer.from_alpaca_bar devuelve None (nada se entrega).
    # Validates: Requirements 3.2, 3.3
    raw = _complete_bar_dict(seed)
    del raw[drop]  # eliminar un campo requerido al azar

    assert Normalizer.from_alpaca_bar(raw) is None


@_PBT_SETTINGS
@given(
    seed=st.integers(min_value=0, max_value=10_000),
    drop=st.sampled_from(_QUOTE_REQUIRED_FIELDS),
)
def test_property_4_quote_missing_required_field_returns_none(seed, drop):
    # Feature: 02-data-feed, Property 4: Malformed data is discarded and never
    # delivered -- para un quote crudo al que le falta un campo requerido,
    # Normalizer.from_alpaca_quote devuelve None.
    # Validates: Requirements 3.2, 3.3
    raw = _complete_quote_dict(seed)
    del raw[drop]

    assert Normalizer.from_alpaca_quote(raw) is None


@_PBT_SETTINGS
@given(seed=st.integers(min_value=0, max_value=10_000))
def test_property_4_complete_bar_is_delivered(seed):
    # Feature: 02-data-feed, Property 4 (complemento): una barra completa SÍ se
    # normaliza a Bar -- garantiza que el None de arriba se debe al campo
    # faltante y no a un rechazo indiscriminado.
    # Validates: Requirements 3.2, 3.3
    assert isinstance(Normalizer.from_alpaca_bar(_complete_bar_dict(seed)), Bar)


# ===========================================================================
# Property 5: paginación multi-página -> una sola lista ascendente sin duplicados.
# ===========================================================================


# Tamaños de página >= 1: la paginación por token del servicio se detiene en la
# primera página vacía, así que para ejercitar el encadenamiento cada página
# intermedia debe traer barras. Incluimos un tamaño grande (>10000) en un caso
# para cubrir explícitamente el camino ">10000 barras" (R1.6) sin materializar
# decenas de miles de objetos por defecto.
@_PBT_SETTINGS_NO_DEADLINE
@given(
    page_sizes=st.lists(
        st.integers(min_value=1, max_value=40),
        min_size=1,
        max_size=6,
    ),
    overlap=st.integers(min_value=0, max_value=10),
    big_last_page=st.booleans(),
)
def test_property_5_pagination_single_ordered_list_no_duplicates(
    page_sizes, overlap, big_last_page
):
    # Feature: 02-data-feed, Property 5: Pagination produces one ordered list
    # with no duplicates -- para cualquier secuencia multi-página de barras
    # crudas (incluido el camino >10000), el resultado ensamblado contiene cada
    # timestamp a lo sumo una vez y queda ordenado ascendente, con independencia
    # de los límites de página. Las páginas se encadenan por next_page_token y
    # pueden solaparse (timestamps repetidos entre páginas contiguas).
    # Validates: Requirements 1.6, 1.2
    if big_last_page:
        # Camino >10000: la última página aporta > 10000 barras contiguas.
        page_sizes = page_sizes + [10_001]

    pages: list[_FakeBarSet] = []
    all_offsets: set[int] = set()

    n_pages = len(page_sizes)
    cursor = 0
    for i, size in enumerate(page_sizes):
        # Cada página cubre offsets [cursor, cursor+size); el solape hace que la
        # siguiente empiece antes, generando timestamps repetidos entre páginas.
        offsets = list(range(cursor, cursor + size))
        raw = [_raw_bar_from_offset(o) for o in offsets]
        all_offsets.update(offsets)

        # Solo la última página carece de next_page_token (fin de la paginación).
        token = f"tok-{i + 1}" if i < n_pages - 1 else None
        pages.append(_FakeBarSet({SYMBOL: raw}, next_page_token=token))

        # Avanzar el cursor dejando un solape controlado con la próxima página,
        # pero siempre avanzando al menos 1 para no reusar el mismo rango entero.
        cursor = cursor + max(size - overlap, 1)

    # Servimos las páginas en orden y, para cualquier llamada extra (p. ej. una
    # única página sin token, donde el servicio intenta avanzar por timestamp),
    # devolvemos un BarSet vacío para que la paginación termine limpiamente.
    _served = {"i": 0}

    def _serve(_request):
        idx = _served["i"]
        _served["i"] += 1
        if idx < len(pages):
            return pages[idx]
        return _FakeBarSet({SYMBOL: []}, next_page_token=None)

    client = _StubCryptoDataClient()
    client.get_crypto_bars = mock.Mock(side_effect=_serve)
    factory = _make_factory(client=client)
    service = HistoricalDataService(factory)

    bars = service.get_bars(SYMBOL, _A_SUPPORTED_TF, _EPOCH, _ts_from_minute(1_000_000))

    timestamps = [b.timestamp for b in bars]
    # Ordenada ascendente.
    assert timestamps == sorted(timestamps)
    # Sin duplicados por timestamp.
    assert len(timestamps) == len(set(timestamps))
    # Cubre exactamente el conjunto de timestamps únicos vistos en todas las
    # páginas (dedup a través de fronteras de página).
    expected = {_ts_from_minute(o) for o in all_offsets}
    assert set(timestamps) == expected
    # Se consumieron TODAS las páginas encadenadas por token.
    assert client.get_crypto_bars.call_count >= n_pages


# ===========================================================================
# Property 6: la secuencia de backoff sigue 1,2,4,...,cap 30 y nunca excede 30.
# ===========================================================================


@_PBT_SETTINGS
@given(n_failures=st.integers(min_value=1, max_value=50))
def test_property_6_backoff_schedule_within_bounds(n_failures):
    # Feature: 02-data-feed, Property 6: Reconnection backoff stays within
    # bounds -- para cualquier número N de fallos consecutivos, la secuencia de
    # delays producida por _next_backoff arranca en 1 y dobla (1,2,4,8,16,30...),
    # nunca excede el cap de 30 y es monótona no decreciente (la función es pura,
    # sin dormir).
    # Validates: Requirements 2.3
    delays: list[int | float] = []
    delay: int | float = INITIAL_BACKOFF
    for _ in range(n_failures):
        delays.append(delay)
        delay = _next_backoff(delay)

    # Arranca en el backoff inicial (1s).
    assert delays[0] == INITIAL_BACKOFF
    # Nunca excede el cap.
    assert all(d <= MAX_BACKOFF for d in delays)
    # Monótona no decreciente.
    assert all(delays[i] <= delays[i + 1] for i in range(len(delays) - 1))
    # Sigue el esquema de doblar hasta topar en el cap.
    for i in range(len(delays) - 1):
        assert delays[i + 1] == min(delays[i] * 2, MAX_BACKOFF)
    # Una vez alcanzado el cap, permanece en el cap indefinidamente.
    assert _next_backoff(MAX_BACKOFF) == MAX_BACKOFF
