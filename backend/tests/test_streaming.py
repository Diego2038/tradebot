"""Pruebas del ``MarketDataStreamer`` (Tarea 5).

Cubren de forma acotada las piezas testeables del streamer sin depender del
bucle async real de Alpaca (el factory y el stream se mockean por completo):

- (a) Backoff dentro de límites: la secuencia de delays tras N fallos sigue
  1, 2, 4, 8, 16, 30, 30, ... y nunca excede 30 (función pura ``_next_backoff``,
  sin dormir de verdad) (R2.3).
- (b) Pub/sub: dos callbacks suscritos reciben ambos un mismo datum normalizado
  publicado vía ``_publish``; ``unsubscribe`` deja de recibir (R2.2).
- (c) ``stop()`` libera la conexión (R2.4): con un stream mockeado, tras ``stop()``
  ``_active`` es False, ``_stream`` es None y se recorrió la secuencia de cierre
  **async** completa (``stop_ws`` para señalizar + ``close`` para cerrar el
  socket) sin tocar el ``stop()`` sincrónico del SDK (que hace deadlock si se
  llama desde el event loop). Se cubren también el último recurso sincrónico
  (dobles sin métodos async) y que un fallo en ``stop_ws`` no impide el
  ``close``.
- (d) ``start()`` reconecta con backoff parcheando el sleep (no espera de verdad)
  y sin terminar el proceso; tras varios fallos se detiene al limpiar ``_active``
  (R2.1, R2.3).
- (e) El bucle normaliza cada update: los válidos se publican, los malformados se
  descartan sin interrumpir (R3.2, R3.3).
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Stub mínimo del SDK alpaca-py ANTES de importar el streamer (que importa el
# factory, que a su vez importa alpaca.trading.client). No hacemos red: el
# factory y el stream se mockean en cada prueba.
# ---------------------------------------------------------------------------


def _install_alpaca_stub() -> None:
    if "alpaca" not in sys.modules:
        alpaca_pkg = types.ModuleType("alpaca")
        alpaca_pkg.__path__ = []
        sys.modules["alpaca"] = alpaca_pkg

    if "alpaca.trading.client" not in sys.modules:
        trading_pkg = types.ModuleType("alpaca.trading")
        trading_pkg.__path__ = []
        trading_client_mod = types.ModuleType("alpaca.trading.client")

        class TradingClient:  # firma mínima compatible
            def __init__(self, api_key=None, secret_key=None, paper=True, **kwargs):
                self._api_key = api_key
                self._secret_key = secret_key
                self._paper = paper

        trading_client_mod.TradingClient = TradingClient
        sys.modules["alpaca.trading"] = trading_pkg
        sys.modules["alpaca.trading.client"] = trading_client_mod


_install_alpaca_stub()

from app.services.data_feed.models import Bar, Quote  # noqa: E402
from app.services.data_feed.streaming import (  # noqa: E402
    INITIAL_BACKOFF,
    MAX_BACKOFF,
    MarketDataStreamer,
    _next_backoff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(price: str = "42000.0") -> Bar:
    return Bar(
        timestamp=datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1.5"),
    )


class _FakeStream:
    """Sustituto de alpaca CryptoDataStream para tests de start/stop.

    ``run_behavior`` controla qué hace ``_run_forever``: puede lanzar (simula
    desconexión) o registrar la llamada. Registra subscribe_* y las llamadas de
    cierre.

    Los métodos de cierre replican el SDK real (alpaca-py ``DataStream``):
    ``stop_ws()`` y ``close()`` son **async** (señalizar y cerrar el socket,
    respectivamente) y ``stop()`` es **sincrónico** (internamente hace
    ``run_coroutine_threadsafe(...).result(timeout=5)``, lo que bloquea el event
    loop si se llama desde dentro de él). Así el test puede afirmar que el
    streamer usa la vía async y NO la sincrónica.
    """

    def __init__(self, run_behavior=None):
        self.subscribed_bars: list = []
        self.subscribed_quotes: list = []
        self.subscribed_trades: list = []
        self.closed = False
        self.stopped = False
        self.stop_ws_called = False
        self._run_behavior = run_behavior

    def subscribe_bars(self, handler, *symbols):
        self.subscribed_bars.append((handler, symbols))

    def subscribe_quotes(self, handler, *symbols):
        self.subscribed_quotes.append((handler, symbols))

    def subscribe_trades(self, handler, *symbols):
        self.subscribed_trades.append((handler, symbols))

    async def _run_forever(self):
        if self._run_behavior is not None:
            self._run_behavior()

    def stop(self):
        # Vía sincrónica del SDK: NO debe usarse desde el event loop.
        self.stopped = True

    async def stop_ws(self):
        self.stop_ws_called = True

    async def close(self):
        self.closed = True


class _SyncOnlyStream:
    """Doble simple que SOLO expone el cierre sincrónico ``stop()``."""

    def __init__(self) -> None:
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FailingStopWsStream(_FakeStream):
    """Fake cuyo ``stop_ws()`` falla, para comprobar que ``close()`` se intenta igual."""

    async def stop_ws(self):
        self.stop_ws_called = True
        raise RuntimeError("stop_ws boom")


def _factory_returning(*streams):
    """Factory mock cuyo build_crypto_data_stream devuelve los streams dados en orden."""
    factory = mock.Mock()
    factory.build_crypto_data_stream.side_effect = list(streams)
    return factory


# ---------------------------------------------------------------------------
# (a) Backoff dentro de límites (R2.3) - función pura, sin dormir
# ---------------------------------------------------------------------------


def test_backoff_schedule_stays_within_bounds() -> None:
    """La secuencia de delays sigue 1,2,4,8,16,30,30,... y nunca excede 30."""
    expected = [1, 2, 4, 8, 16, 30, 30, 30]
    delays: list[int | float] = []
    delay: int | float = INITIAL_BACKOFF
    for _ in range(len(expected)):
        delays.append(delay)
        delay = _next_backoff(delay)

    assert delays == expected
    assert all(d <= MAX_BACKOFF for d in delays)
    assert _next_backoff(MAX_BACKOFF) == MAX_BACKOFF


def test_next_backoff_never_exceeds_cap_from_arbitrary_value() -> None:
    assert _next_backoff(100) == MAX_BACKOFF
    assert _next_backoff(20) == MAX_BACKOFF  # 40 -> cap 30


# ---------------------------------------------------------------------------
# (b) Pub/sub: fan-out y unsubscribe (R2.2)
# ---------------------------------------------------------------------------


def test_publish_fans_out_to_all_subscribers() -> None:
    streamer = MarketDataStreamer(factory=mock.Mock())
    received_a: list = []
    received_b: list = []
    streamer.subscribe(received_a.append)
    streamer.subscribe(received_b.append)

    datum = _make_bar()
    streamer._publish(datum)

    assert received_a == [datum]
    assert received_b == [datum]


def test_unsubscribe_stops_delivery() -> None:
    streamer = MarketDataStreamer(factory=mock.Mock())
    received: list = []
    cb = received.append
    streamer.subscribe(cb)
    streamer._publish(_make_bar("1"))
    streamer.unsubscribe(cb)
    streamer._publish(_make_bar("2"))

    assert len(received) == 1
    assert received[0].close == Decimal("1")


def test_subscribe_is_idempotent() -> None:
    streamer = MarketDataStreamer(factory=mock.Mock())
    received: list = []
    cb = received.append
    streamer.subscribe(cb)
    streamer.subscribe(cb)
    streamer._publish(_make_bar())

    assert len(received) == 1


# ---------------------------------------------------------------------------
# (c) stop() libera la conexión (R2.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_releases_connection_and_clears_active() -> None:
    """Cierre por la vía async completa: ``stop_ws`` + ``close``, nunca ``stop``.

    ``close()`` es el paso que realmente libera el socket (y con él el slot de
    conexión del proveedor). La aserción ``fake.stopped is False`` es el guard de
    regresión: llamar al ``stop()`` sincrónico del SDK desde el event loop lo
    bloquea (deadlock -> TimeoutError) y deja la conexión abierta, que era el bug.
    """
    fake = _FakeStream()
    streamer = MarketDataStreamer(factory=mock.Mock())
    # Simulamos que start() dejó una conexión activa.
    streamer._stream = fake
    streamer._active = True

    await streamer.stop()

    assert streamer._active is False
    assert streamer._stream is None
    # Se señalizó el fin del bucle y se cerró el socket (ambos awaited).
    assert fake.stop_ws_called is True
    assert fake.closed is True
    # El stop() sincrónico NO se usa cuando existen los métodos async.
    assert fake.stopped is False


@pytest.mark.asyncio
async def test_stop_falls_back_to_sync_stop_when_no_async_closers() -> None:
    """Doble sin ``stop_ws``/``close``: ``stop()`` sí se usa como último recurso."""
    fake = _SyncOnlyStream()
    streamer = MarketDataStreamer(factory=mock.Mock())
    streamer._stream = fake
    streamer._active = True

    await streamer.stop()

    assert fake.stopped is True
    assert streamer._active is False
    assert streamer._stream is None


@pytest.mark.asyncio
async def test_stop_ws_failure_does_not_prevent_close() -> None:
    """Un fallo al señalizar no impide cerrar el socket, y stop() no propaga."""
    fake = _FailingStopWsStream()
    streamer = MarketDataStreamer(factory=mock.Mock())
    streamer._stream = fake
    streamer._active = True

    await streamer.stop()  # no debe lanzar

    assert fake.stop_ws_called is True
    # Pese al error anterior se intentó (y logró) el cierre real.
    assert fake.closed is True
    assert fake.stopped is False
    assert streamer._stream is None


@pytest.mark.asyncio
async def test_stop_without_stream_is_noop() -> None:
    streamer = MarketDataStreamer(factory=mock.Mock())
    await streamer.stop()  # no debe lanzar
    assert streamer._active is False


# ---------------------------------------------------------------------------
# (d) start() reconecta con backoff (sleep parcheado) sin terminar el proceso
#     (R2.1, R2.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_reconnects_with_backoff_then_stops() -> None:
    """Tras varias desconexiones el streamer duerme el backoff y reintenta;
    al agotar los streams disponibles limpiamos _active para terminar el bucle."""
    call_count = {"n": 0}

    def _boom():
        raise ConnectionError("dropped")

    streams = [
        _FakeStream(run_behavior=_boom),
        _FakeStream(run_behavior=_boom),
        _FakeStream(run_behavior=_boom),
    ]
    factory = _factory_returning(*streams)

    slept: list[float] = []

    streamer = MarketDataStreamer(factory=factory)

    async def _fake_sleep(delay: float) -> None:
        slept.append(delay)
        call_count["n"] += 1
        # Tras 3 backoffs, detenemos para no reconectar indefinidamente.
        if call_count["n"] >= 3:
            streamer._active = False

    streamer._sleep = _fake_sleep

    await streamer.start()

    # Durmió el backoff creciente sin terminar el proceso por excepción.
    assert slept == [1, 2, 4]
    assert streamer._active is False
    assert factory.build_crypto_data_stream.call_count == 3
    # Se suscribió a BTC/USD en cada intento.
    assert streams[0].subscribed_bars[0][1] == ("BTC/USD",)


@pytest.mark.asyncio
async def test_start_publishes_valid_and_discards_malformed() -> None:
    """El bucle normaliza cada update: publica los válidos y descarta los
    malformados sin interrumpir (R3.2, R3.3)."""
    received: list = []

    valid_bar_raw = {
        "symbol": "BTC/USD",
        "timestamp": datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        "open": 42000.0,
        "high": 42500.0,
        "low": 41000.0,
        "close": 42200.0,
        "volume": 3.2,
    }
    malformed_bar_raw = {"symbol": "BTC/USD", "open": 1}  # faltan campos

    def _feed():
        # El stream "recibe" un update malformado y otro válido antes de terminar.
        streamer._handle_raw(malformed_bar_raw, is_quote=False)
        streamer._handle_raw(valid_bar_raw, is_quote=False)
        streamer._active = False  # terminar limpio tras un ciclo

    fake = _FakeStream(run_behavior=_feed)
    factory = _factory_returning(fake)

    streamer = MarketDataStreamer(factory=factory)
    streamer.subscribe(received.append)

    await streamer.start()

    # Solo el datum válido llegó a los suscriptores; el malformado se descartó.
    assert len(received) == 1
    assert isinstance(received[0], Bar)
    assert received[0].close == Decimal("42200.0")
