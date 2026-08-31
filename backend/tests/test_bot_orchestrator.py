"""Pruebas del BotOrchestrator (Tarea 3, spec 07-bot-api).

Cubren de forma acotada el ciclo de vida del bot con fakes/mocks async de los
componentes de dominio (streamer/engine/executor/position_manager), sin red ni
Alpaca real. Casos (referenciados a los criterios de aceptación):

- (a) start sin credenciales -> CredentialsRequiredError; streamer.start NO se
  llamó; estado sigue STOPPED (R2.3).
- (b) start con modo inválido -> propaga UnknownStrategyError; estado sigue
  STOPPED; streamer.start NO llamado (R2.4).
- (c) start válido -> engine.set_active(mode), streamer.subscribe y
  streamer.start llamados una vez, estado RUNNING (R2.2).
- (d) start idempotente -> dos start seguidos: streamer.start una sola vez,
  sigue RUNNING (R2.8).
- (e) stop -> streamer.stop llamado, estado STOPPED (R2.5).
- (f) status -> devuelve state/mode/symbol (mode desde engine.get_active_name)
  (R2.6).
- (g) _on_market_data -> un Quote llega a position_manager.on_quote; un Bar
  alimenta engine.generate + executor.execute_signal; una excepción en generate
  se captura y no propaga (resiliencia por tick).
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar módulos que lo cargan de forma no
# perezosa. El orchestrator importa `MarketDataStreamer`, que a su vez importa
# `AlpacaClientFactory` (`from alpaca.trading.client import TradingClient`).
# Mismo patrón que en test_execution_positions.py; el streamer/factory nunca se
# instancian aquí (se usan mocks), así que el stub solo evita el ImportError.
# ---------------------------------------------------------------------------


def _install_alpaca_stub() -> None:
    """Instala paquetes stub de ``alpaca`` de forma idempotente y no contaminante.

    Higiene de orden de colección: delegamos en el instalador de
    ``tests/test_factory.py`` para que su ``_FakeAPIError`` sea la clase canónica
    registrada en ``alpaca.common.exceptions`` (el factory clasifica por
    ``isinstance`` contra la clase registrada). Así, sin importar quién colecte
    primero, todas las suites comparten el mismo ``APIError`` y no se contaminan.
    El orchestrator solo necesita evitar el ``ImportError`` de
    ``alpaca.trading.client`` (import no perezoso del factory vía streamer);
    aquí ni el streamer ni el factory se instancian (se usan mocks).
    """
    from tests.test_factory import _install_alpaca_stub as _install_spec01_stub

    _install_spec01_stub()

    # Red de seguridad: garantiza el submódulo mínimo que carga el factory.
    if "alpaca.trading.client" not in sys.modules:
        alpaca_pkg = sys.modules.get("alpaca") or types.ModuleType("alpaca")
        alpaca_pkg.__path__ = []
        trading_pkg = sys.modules.get("alpaca.trading") or types.ModuleType(
            "alpaca.trading"
        )
        trading_pkg.__path__ = []
        client_mod = types.ModuleType("alpaca.trading.client")

        class _StubTradingClient:  # pragma: no cover - nunca se instancia aquí
            def __init__(self, *args, **kwargs):
                pass

        client_mod.TradingClient = _StubTradingClient
        sys.modules["alpaca"] = alpaca_pkg
        sys.modules["alpaca.trading"] = trading_pkg
        sys.modules["alpaca.trading.client"] = client_mod


_install_alpaca_stub()

from app.services.alpaca_client.errors import CredentialsRequiredError  # noqa: E402
from app.services.bot.orchestrator import BotOrchestrator  # noqa: E402
from app.services.bot.state import BotState  # noqa: E402
from app.services.data_feed.models import Bar, Quote  # noqa: E402
from app.services.strategies.errors import UnknownStrategyError  # noqa: E402
from app.services.strategies.signals import Action, Signal  # noqa: E402


def _make_signal(action: Action = Action.HOLD) -> Signal:
    return Signal(action=action, reason="test", timestamp=datetime.now(timezone.utc))


def _make_quote(price: str = "64000.00") -> Quote:
    return Quote(timestamp=datetime.now(timezone.utc), price=Decimal(price))


def _make_bar() -> Bar:
    now = datetime.now(timezone.utc)
    return Bar(
        timestamp=now,
        open=Decimal("64000"),
        high=Decimal("64100"),
        low=Decimal("63900"),
        close=Decimal("64050"),
        volume=Decimal("1.5"),
    )


def _build_orchestrator(
    *,
    active_name: str = "random",
    credential_check=None,
    set_active_side_effect=None,
    generate_side_effect=None,
    bar_preloader=None,
):
    """Construye un BotOrchestrator con mocks/fakes de todos los componentes."""
    streamer = Mock()
    streamer.start = AsyncMock()
    streamer.stop = AsyncMock()
    streamer.subscribe = Mock()

    engine = Mock()
    engine.set_active = Mock(side_effect=set_active_side_effect)
    engine.get_active_name = Mock(return_value=active_name)
    engine.generate = Mock(
        side_effect=generate_side_effect,
        return_value=_make_signal(),
    )

    executor = Mock()
    executor.execute_signal = Mock()

    position_manager = Mock()
    position_manager.on_quote = Mock()

    orch = BotOrchestrator(
        streamer=streamer,
        engine=engine,
        executor=executor,
        position_manager=position_manager,
        symbol="BTC/USD",
        credential_check=credential_check,
        bar_preloader=bar_preloader,
    )
    return orch, streamer, engine, executor, position_manager


# -- (a) start sin credenciales (R2.3) --------------------------------------


@pytest.mark.asyncio
async def test_start_without_credentials_raises_and_does_not_start() -> None:
    """(a) credential_check False -> CredentialsRequiredError; no start; STOPPED (R2.3)."""
    orch, streamer, engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: False
    )

    with pytest.raises(CredentialsRequiredError):
        await orch.start("random")

    streamer.start.assert_not_called()
    streamer.subscribe.assert_not_called()
    engine.set_active.assert_not_called()
    assert orch.status().state is BotState.STOPPED


# -- (b) start con modo inválido (R2.4) -------------------------------------


@pytest.mark.asyncio
async def test_start_with_invalid_mode_propagates_and_state_unchanged() -> None:
    """(b) set_active lanza UnknownStrategyError -> propaga; STOPPED; no start (R2.4)."""
    orch, streamer, engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: True,
        set_active_side_effect=UnknownStrategyError("unknown 'bogus'"),
    )

    with pytest.raises(UnknownStrategyError):
        await orch.start("bogus")

    engine.set_active.assert_called_once_with("bogus")
    streamer.start.assert_not_called()
    assert orch.status().state is BotState.STOPPED


# -- (c) start válido (R2.2) ------------------------------------------------


@pytest.mark.asyncio
async def test_valid_start_sets_mode_subscribes_and_starts_streamer() -> None:
    """(c) start válido -> set_active, subscribe, tarea de fondo, RUNNING (R2.2).

    Con el nuevo contrato, el bucle infinito del streamer se lanza como tarea de
    fondo (``asyncio.create_task``) para que ``start()`` responda de inmediato en
    lugar de colgarse. Verificamos que: el estado es RUNNING, se suscribieron los
    dos consumidores, se creó una tarea de fondo, y ``streamer.start`` se ejecutó
    (dándole una oportunidad de correr con ``asyncio.sleep(0)``). Cerramos la
    tarea al final con ``stop()`` para no dejar tareas colgadas.
    """
    orch, streamer, engine, _executor, position_manager = _build_orchestrator(
        credential_check=lambda: True
    )

    status = await orch.start("random")

    engine.set_active.assert_called_once_with("random")
    # Se creó una tarea de fondo para el bucle del streamer.
    assert orch._stream_task is not None
    # Se suscriben los dos consumidores: on_market_data y position_manager.on_quote.
    assert streamer.subscribe.call_count == 2
    subscribed = {call.args[0] for call in streamer.subscribe.call_args_list}
    assert orch._on_market_data in subscribed
    assert position_manager.on_quote in subscribed
    assert status.state is BotState.RUNNING
    assert orch.status().state is BotState.RUNNING

    # La corrutina agendada por create_task tiene ahora oportunidad de ejecutarse.
    await asyncio.sleep(0)
    streamer.start.assert_awaited_once()

    # Limpieza: cancela/cierra la tarea de fondo para no dejarla colgada.
    await orch.stop()


# -- (d) start idempotente (R2.8) -------------------------------------------


@pytest.mark.asyncio
async def test_start_is_idempotent_while_running() -> None:
    """(d) dos start seguidos -> streamer.start una sola vez; sigue RUNNING (R2.8)."""
    orch, streamer, engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: True
    )

    first = await orch.start("random")
    task_after_first = orch._stream_task
    second = await orch.start("random")

    # El segundo start es no-op: misma tarea, sin re-suscribir ni re-set_active.
    assert orch._stream_task is task_after_first
    assert orch._stream_task is not None
    assert streamer.subscribe.call_count == 2
    engine.set_active.assert_called_once_with("random")
    assert first.state is BotState.RUNNING
    assert second.state is BotState.RUNNING
    assert orch.status().state is BotState.RUNNING

    # create_task agendó la corrutina una sola vez.
    await asyncio.sleep(0)
    streamer.start.assert_awaited_once()

    # Limpieza.
    await orch.stop()


# -- (e) stop (R2.5) --------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_stops_streamer_and_transitions_to_stopped() -> None:
    """(e) stop -> streamer.stop llamado; estado STOPPED (R2.5)."""
    orch, streamer, _engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: True
    )
    await orch.start("random")
    assert orch._stream_task is not None

    status = await orch.stop()

    streamer.stop.assert_awaited_once()
    assert status.state is BotState.STOPPED
    assert orch.status().state is BotState.STOPPED
    # La tarea de fondo quedó cancelada/cerrada y la referencia reseteada.
    assert orch._stream_task is None


# -- (f) status (R2.6) ------------------------------------------------------


@pytest.mark.asyncio
async def test_status_reports_state_mode_and_symbol() -> None:
    """(f) status -> state/mode/symbol; mode desde engine.get_active_name (R2.6)."""
    orch, _streamer, engine, _executor, _pm = _build_orchestrator(
        active_name="predictive", credential_check=lambda: True
    )

    status = orch.status()

    assert status.state is BotState.STOPPED
    assert status.mode == "predictive"
    assert status.symbol == "BTC/USD"
    engine.get_active_name.assert_called()


# -- (g) _on_market_data (pipeline + resiliencia) ---------------------------


def test_on_market_data_bar_feeds_engine_and_executor() -> None:
    """(g) un Bar alimenta engine.generate + executor.execute_signal."""
    orch, _streamer, engine, executor, _pm = _build_orchestrator()
    signal = _make_signal(Action.BUY)
    engine.generate = Mock(return_value=signal)

    bar = _make_bar()
    orch._on_market_data(bar)

    engine.generate.assert_called_once()
    # El buffer rolling incluye la barra recibida.
    bars_arg = engine.generate.call_args.args[0]
    assert bar in bars_arg
    executor.execute_signal.assert_called_once_with(signal)


def test_on_market_data_quote_updates_current_quote_for_engine() -> None:
    """(g) un Quote se usa como quote actual pasado a engine.generate."""
    orch, _streamer, engine, _executor, _pm = _build_orchestrator()

    quote = _make_quote()
    orch._on_market_data(quote)

    engine.generate.assert_called_once()
    quote_arg = engine.generate.call_args.args[1]
    assert quote_arg is quote


def test_on_market_data_swallows_exceptions_and_does_not_propagate() -> None:
    """(g) una excepción en generate se captura y no propaga (resiliencia por tick)."""
    orch, _streamer, engine, executor, _pm = _build_orchestrator(
        generate_side_effect=RuntimeError("boom")
    )

    # No debe lanzar aunque engine.generate falle.
    orch._on_market_data(_make_bar())

    # El executor no se llamó porque generate falló, pero el bot no se detuvo.
    executor.execute_signal.assert_not_called()
    assert orch.status().state is BotState.STOPPED


# -- (h) start con preloader que devuelve barras -----------------------------


@pytest.mark.asyncio
async def test_start_preloads_bars_into_buffer() -> None:
    """(h) start con bar_preloader -> las barras quedan en el buffer al arrancar.

    Sembrar el buffer con barras históricas es lo que permite a `predictive`
    disponer de la ventana de warm-up (>= 20 barras) desde el primer tick.
    """
    preloaded = [_make_bar() for _ in range(25)]
    orch, _streamer, _engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: True,
        bar_preloader=lambda: preloaded,
    )

    await orch.start("predictive")

    assert list(orch._bars) == preloaded
    assert orch.status().state is BotState.RUNNING

    await orch.stop()


# -- (i) start con preloader que falla (best-effort) -------------------------


@pytest.mark.asyncio
async def test_start_survives_failing_preloader() -> None:
    """(i) si el preloader lanza, start NO falla y el bot queda RUNNING (buffer vacío)."""

    def _boom() -> list[Bar]:
        raise RuntimeError("preload boom")

    orch, _streamer, _engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: True,
        bar_preloader=_boom,
    )

    status = await orch.start("predictive")

    # La precarga es best-effort: falla en silencio, el bot arranca igual.
    assert status.state is BotState.RUNNING
    assert len(orch._bars) == 0

    await orch.stop()
