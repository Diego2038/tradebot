"""Property-based tests del bot API (Tarea 5, spec 07-bot-api).

Cubre las siete propiedades esenciales del design (secciones "Correctness
Properties" y "Testing Strategy") con Hypothesis (min. 100 iteraciones cada una),
sin red ni Alpaca real. Se ataca la lógica determinista de control/broadcast:

- Transiciones de estado y mapeo de errores del :class:`BotOrchestrator`
  (P1-P4): con streamer/engine/executor/position_manager mockeados
  (``AsyncMock`` para ``streamer.start``/``stop``; ``Mock`` para el resto).
- Fan-out y serialización del :class:`WebSocketHub` (P5-P7): con un
  :class:`EventPublisher` real y clientes WebSocket fake async.

Hypothesis no envuelve bien funciones ``async`` con ``@given``; por eso cada
propiedad async se implementa como una función **sync** decorada con ``@given``
que ejecuta la corrutina con ``asyncio.run`` internamente. Esto mantiene el
determinismo y la rapidez (sin event loop compartido entre ejemplos).

Igual que en ``test_bot_orchestrator.py``, se instala el stub del SDK ``alpaca``
ANTES de importar el orchestrator (que importa el streamer -> factory ->
``alpaca.trading.client``); ni el streamer ni el factory se instancian aquí.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar módulos que lo cargan (idéntico
# patrón que test_bot_orchestrator.py): delegamos en tests.test_factory para
# compartir la clase canónica de APIError, con red de seguridad para
# alpaca.trading.client. Ni streamer ni factory se instancian en esta suite.
# ---------------------------------------------------------------------------


def _install_alpaca_stub() -> None:
    from tests.test_factory import _install_alpaca_stub as _install_spec01_stub

    _install_spec01_stub()

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

from app.api.ws import WebSocketHub, serialize_event  # noqa: E402
from app.services.alpaca_client.errors import CredentialsRequiredError  # noqa: E402
from app.services.bot.orchestrator import BotOrchestrator  # noqa: E402
from app.services.bot.state import BotState  # noqa: E402
from app.services.execution.events import (  # noqa: E402
    EventPublisher,
    EventType,
    OrderEvent,
)
from app.services.strategies.errors import UnknownStrategyError  # noqa: E402
from app.services.strategies.signals import Action, Signal  # noqa: E402

# Modos válidos registrados (Literal["random","predictive"] en el schema).
VALID_MODES = ["random", "predictive"]

# Claves declaradas y secret-free que serialize_event puede emitir (R3.3).
DECLARED_EVENT_KEYS = {
    "event_type",
    "symbol",
    "side",
    "qty",
    "price",
    "order_id",
    "reason",
    "timestamp",
}

# Substrings que delatarían material de credenciales filtrado en un broadcast.
_SECRET_MARKERS = ("api_key", "apikey", "secret", "api_secret", "password", "token")


# ---------------------------------------------------------------------------
# Helpers de construcción (orchestrator con dominio mockeado / fakes async).
# ---------------------------------------------------------------------------


def _make_signal(action: Action = Action.HOLD) -> Signal:
    return Signal(action=action, reason="test", timestamp=datetime.now(timezone.utc))


def _build_orchestrator(
    *,
    active_name: str = "random",
    credential_check=None,
    set_active_side_effect=None,
):
    """Construye un BotOrchestrator con mocks/fakes async de los componentes."""
    streamer = Mock()
    streamer.start = AsyncMock()
    streamer.stop = AsyncMock()
    streamer.subscribe = Mock()

    engine = Mock()
    engine.set_active = Mock(side_effect=set_active_side_effect)
    engine.get_active_name = Mock(return_value=active_name)
    engine.generate = Mock(return_value=_make_signal())

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
    )
    return orch, streamer, engine, executor, position_manager


class _FakeWebSocket:
    """Cliente WebSocket fake async para el hub.

    Registra los payloads recibidos en :attr:`sent`. Si ``fail`` es ``True``,
    ``send_json`` lanza para simular un cliente roto (R3.5).
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("broken client")
        self.sent.append(payload)


def _make_order_event(
    *,
    event_type: EventType,
    symbol: str = "BTC/USD",
    side: str | None = "buy",
    reason: str = "",
) -> OrderEvent:
    return OrderEvent(
        event_type=event_type,
        symbol=symbol,
        side=side,
        qty=Decimal("0.5"),
        price=Decimal("64000.00"),
        order_id="oid-123",
        reason=reason,
    )


# ===========================================================================
# Property 1 (R2.3)
# ===========================================================================


# Feature: 07-bot-api, Property 1: Start without credentials never starts and errors clearly
@settings(max_examples=100, deadline=None)
@given(mode=st.sampled_from(VALID_MODES))
def test_property_1_start_without_credentials_never_starts(mode: str) -> None:
    """Para cualquier modo válido, con credential_check=False: start lanza
    CredentialsRequiredError, streamer.start NO se llamó y el estado sigue
    STOPPED. **Validates: Requirements 2.3**
    """
    orch, streamer, engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: False
    )

    raised = False
    try:
        asyncio.run(orch.start(mode))
    except CredentialsRequiredError:
        raised = True

    assert raised, "start sin credenciales debe lanzar CredentialsRequiredError"
    streamer.start.assert_not_called()
    streamer.subscribe.assert_not_called()
    engine.set_active.assert_not_called()
    assert orch.status().state is BotState.STOPPED


# ===========================================================================
# Property 2 (R2.4)
# ===========================================================================


# Feature: 07-bot-api, Property 2: Invalid mode leaves state unchanged
@settings(max_examples=100, deadline=None)
@given(
    mode=st.text(min_size=1, max_size=20).filter(lambda m: m not in VALID_MODES)
)
def test_property_2_invalid_mode_leaves_state_unchanged(mode: str) -> None:
    """Para cualquier nombre no registrado, con engine.set_active lanzando
    UnknownStrategyError: start propaga el error, el estado sigue STOPPED y
    streamer.start NO se llamó. **Validates: Requirements 2.4**
    """
    orch, streamer, engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: True,
        set_active_side_effect=UnknownStrategyError(f"unknown {mode!r}"),
    )

    raised = False
    try:
        asyncio.run(orch.start(mode))
    except UnknownStrategyError:
        raised = True

    assert raised, "modo inválido debe propagar UnknownStrategyError"
    engine.set_active.assert_called_once_with(mode)
    streamer.start.assert_not_called()
    assert orch.status().state is BotState.STOPPED


# ===========================================================================
# Property 3 (R2.2, R2.8)
# ===========================================================================


# Feature: 07-bot-api, Property 3: Start is idempotent while running
@settings(max_examples=100, deadline=None)
@given(n=st.integers(min_value=1, max_value=10), mode=st.sampled_from(VALID_MODES))
def test_property_3_start_is_idempotent_while_running(n: int, mode: str) -> None:
    """Para cualquier nº N>=1 de starts con credenciales y modo válidos:
    streamer.start se llamó EXACTAMENTE una vez y el estado es RUNNING.
    **Validates: Requirements 2.2, 2.8**
    """
    orch, streamer, engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: True
    )

    async def _run() -> None:
        for _ in range(n):
            await orch.start(mode)

    asyncio.run(_run())

    streamer.start.assert_awaited_once()
    # Un único cableado de pipeline: dos consumidores suscritos una sola vez.
    assert streamer.subscribe.call_count == 2
    engine.set_active.assert_called_once_with(mode)
    assert orch.status().state is BotState.RUNNING


# ===========================================================================
# Property 4 (R2.5, R2.6)
# ===========================================================================


# Feature: 07-bot-api, Property 4: Stop returns to stopped and releases the streamer
@settings(max_examples=100, deadline=None)
@given(mode=st.sampled_from(VALID_MODES))
def test_property_4_stop_returns_to_stopped_and_releases_streamer(mode: str) -> None:
    """Tras arrancar, stop() -> streamer.stop llamado y status().state == STOPPED.
    **Validates: Requirements 2.5, 2.6**
    """
    orch, streamer, _engine, _executor, _pm = _build_orchestrator(
        credential_check=lambda: True
    )

    async def _run():
        await orch.start(mode)
        return await orch.stop()

    status = asyncio.run(_run())

    streamer.stop.assert_awaited_once()
    assert status.state is BotState.STOPPED
    assert orch.status().state is BotState.STOPPED


# ===========================================================================
# Property 5 (R3.2)
# ===========================================================================


# Feature: 07-bot-api, Property 5: Every published event reaches all healthy clients
@settings(max_examples=100, deadline=None)
@given(
    n=st.integers(min_value=0, max_value=10),
    event_type=st.sampled_from(list(EventType)),
)
def test_property_5_every_event_reaches_all_healthy_clients(
    n: int, event_type: EventType
) -> None:
    """Para cualquier conjunto de N clientes sanos y cualquier OrderEvent,
    broadcast entrega el evento serializado a cada cliente exactamente una vez.
    **Validates: Requirements 3.2**
    """
    hub = WebSocketHub(EventPublisher())
    clients = [_FakeWebSocket() for _ in range(n)]
    for client in clients:
        hub._connections.add(client)

    event = _make_order_event(event_type=event_type)
    asyncio.run(hub.broadcast(event))

    expected = serialize_event(event)
    for client in clients:
        assert client.sent == [expected], "cada cliente sano recibe el evento una vez"
    # Ningún cliente sano se descarta.
    assert hub._connections == set(clients)


# ===========================================================================
# Property 6 (R3.4, R3.5)
# ===========================================================================


# Feature: 07-bot-api, Property 6: A failing client is dropped without affecting others
@settings(max_examples=100, deadline=None)
@given(
    flags=st.lists(st.booleans(), min_size=0, max_size=10),
    event_type=st.sampled_from(list(EventType)),
)
def test_property_6_failing_client_dropped_without_affecting_others(
    flags: list[bool], event_type: EventType
) -> None:
    """Para cualquier mezcla de clientes sanos y clientes que lanzan en
    send_json, broadcast entrega a todos los sanos, elimina los que fallan de
    _connections y no lanza. **Validates: Requirements 3.4, 3.5**
    """
    hub = WebSocketHub(EventPublisher())
    # flags[i] == True -> cliente que falla.
    clients = [_FakeWebSocket(fail=fail) for fail in flags]
    for client in clients:
        hub._connections.add(client)

    event = _make_order_event(event_type=event_type)
    expected = serialize_event(event)

    # No debe lanzar aunque haya clientes rotos.
    asyncio.run(hub.broadcast(event))

    healthy = [c for c in clients if not c.fail]
    failing = [c for c in clients if c.fail]

    for client in healthy:
        assert client.sent == [expected], "los clientes sanos reciben el evento"
    # Los clientes que fallan se descartan; los sanos permanecen.
    assert hub._connections == set(healthy)
    for client in failing:
        assert client not in hub._connections


# ===========================================================================
# Property 7 (R3.3)
# ===========================================================================


# Feature: 07-bot-api, Property 7: Broadcast events contain no secrets
@settings(max_examples=100, deadline=None)
@given(
    event_type=st.sampled_from(list(EventType)),
    symbol=st.text(max_size=30),
    side=st.one_of(st.none(), st.text(max_size=10)),
    reason=st.text(max_size=50),
)
def test_property_7_broadcast_events_contain_no_secrets(
    event_type: EventType, symbol: str, side: str | None, reason: str
) -> None:
    """Para cualquier OrderEvent, serialize_event solo tiene las claves
    declaradas y no filtra material de credenciales, aun cuando se inyecte un
    api_key/secret inventado en atributos ajenos del evento.
    **Validates: Requirements 3.3**
    """
    event = _make_order_event(
        event_type=event_type, symbol=symbol, side=side, reason=reason
    )
    # Inyecta material sensible en un atributo NO declarado del evento; la
    # serialización nunca debe recogerlo (usa solo campos declarados). OrderEvent
    # es frozen, así que lo forzamos vía object.__setattr__.
    injected_secret = "SUPER_SECRET_API_KEY_abcd1234"
    object.__setattr__(event, "api_key", injected_secret)
    object.__setattr__(event, "secret", injected_secret)

    payload = serialize_event(event)

    # Solo las claves declaradas y secret-free.
    assert set(payload.keys()) == DECLARED_EVENT_KEYS

    # Ninguna clave del payload es material de credenciales.
    lowered_keys = {str(k).lower() for k in payload}
    assert not (lowered_keys & set(_SECRET_MARKERS))

    # El secreto inyectado no aparece en ningún valor serializado.
    serialized_values = " ".join(str(v) for v in payload.values())
    assert injected_secret not in serialized_values
