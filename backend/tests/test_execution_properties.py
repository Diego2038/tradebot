"""Pruebas basadas en propiedades (Hypothesis) de la capa de ejecución (Tarea 7).

Spec ``04-order-execution``. Ejercitan la lógica determinista de la feature sobre
señales, precios y niveles SL/TP generados por Hypothesis. Ni el SDK de Alpaca ni
la red están disponibles: se stubbea el paquete ``alpaca`` vía ``sys.modules`` ANTES
de importar los módulos bajo prueba (mismo patrón que ``test_execution_executor.py``
y ``test_execution_positions.py``), reutilizando/rellenando los stubs existentes con
comprobaciones ``hasattr`` para no pisar los de otros módulos de test (el orden de
colección de pytest es arbitrario). El ``AlpacaClientFactory`` se falsea/mockea, el
``RiskPort`` se falsea y el ``EventPublisher`` es real (in-memory).

Cada test lleva un comentario "Feature: 04-order-execution, Property N: ...".
Todas las propiedades corren con >= 100 iteraciones (@settings(max_examples=100)).

Cobertura (7 propiedades del design):
- P1: BUY/SELL aprobado -> evaluate ANTES de submit, exactamente UN submit_order con
      side/symbol/qty correctos, y el resultado registra id/status/symbol/qty/side.
- P2: HOLD -> submit_order nunca se llama y devuelve None.
- P3: señal rechazada por riesgo -> no submit + exactamente un RISK_BLOCK con reason.
- P4: make_client_order_id determinista + reintentos idempotentes (mismo id, <=3
      intentos, a lo sumo una orden lógica registrada).
- P5: SL/TP cierran con el evento correcto; sin niveles no cierra.
- P6: un suscriptor que falla no interrumpe publish ni la ejecución.
- P7: ningún OrderEvent emitido contiene material de credenciales.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar los módulos que lo cargan.
#
# Rellenamos SOLO lo que falte (hasattr checks) para reutilizar los stubs que
# otros módulos de test puedan haber instalado ya, y así no romper sus asserts
# de ``isinstance`` contra SUS propias clases por orden de colección.
# ---------------------------------------------------------------------------


class _FakeAPIError(Exception):
    """Sustituto de alpaca.common.exceptions.APIError con status HTTP."""

    def __init__(self, message: str = "api error", status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class _FakeMarketOrderRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeOrderSide:
    BUY = "OrderSide.BUY"
    SELL = "OrderSide.SELL"


class _FakeTimeInForce:
    GTC = "TimeInForce.GTC"


class _FakeTradingClient:
    def __init__(self, api_key=None, secret_key=None, paper=True, **kwargs):
        self._paper = paper

    def submit_order(self, order_data):  # pragma: no cover - se mockea por test
        raise NotImplementedError


def _install_alpaca_stub() -> None:
    alpaca_pkg = sys.modules.get("alpaca") or types.ModuleType("alpaca")
    alpaca_pkg.__path__ = []
    trading_pkg = sys.modules.get("alpaca.trading") or types.ModuleType(
        "alpaca.trading"
    )
    trading_pkg.__path__ = []

    client_mod = sys.modules.get("alpaca.trading.client") or types.ModuleType(
        "alpaca.trading.client"
    )
    if not hasattr(client_mod, "TradingClient"):
        client_mod.TradingClient = _FakeTradingClient

    requests_mod = sys.modules.get("alpaca.trading.requests") or types.ModuleType(
        "alpaca.trading.requests"
    )
    if not hasattr(requests_mod, "MarketOrderRequest"):
        requests_mod.MarketOrderRequest = _FakeMarketOrderRequest

    enums_mod = sys.modules.get("alpaca.trading.enums") or types.ModuleType(
        "alpaca.trading.enums"
    )
    if not hasattr(enums_mod, "OrderSide"):
        enums_mod.OrderSide = _FakeOrderSide
    if not hasattr(enums_mod, "TimeInForce"):
        enums_mod.TimeInForce = _FakeTimeInForce

    common_pkg = sys.modules.get("alpaca.common") or types.ModuleType("alpaca.common")
    common_pkg.__path__ = []
    exceptions_mod = sys.modules.get("alpaca.common.exceptions") or types.ModuleType(
        "alpaca.common.exceptions"
    )
    if not hasattr(exceptions_mod, "APIError"):
        exceptions_mod.APIError = _FakeAPIError

    sys.modules["alpaca"] = alpaca_pkg
    sys.modules["alpaca.trading"] = trading_pkg
    sys.modules["alpaca.trading.client"] = client_mod
    sys.modules["alpaca.trading.requests"] = requests_mod
    sys.modules["alpaca.trading.enums"] = enums_mod
    sys.modules["alpaca.common"] = common_pkg
    sys.modules["alpaca.common.exceptions"] = exceptions_mod


_install_alpaca_stub()

from app.services.data_feed.models import Quote  # noqa: E402
from app.services.execution.errors import InvalidLevelError  # noqa: E402
from app.services.execution.events import (  # noqa: E402
    EventPublisher,
    EventType,
    OrderEvent,
)
from app.services.execution.executor import OrderExecutor  # noqa: E402
from app.services.execution.orders import make_client_order_id  # noqa: E402
from app.services.execution.positions import PositionManager  # noqa: E402
from app.services.execution.risk import RiskDecision  # noqa: E402
from app.services.strategies.signals import Action, Signal  # noqa: E402

# OrderSide resuelto desde el mismo módulo que usa `orders` (puede haberlo
# instalado otro módulo de test antes): así las aserciones de side comparan
# contra la clase realmente instalada.
from alpaca.trading.enums import OrderSide as _OrderSide  # noqa: E402


# ---------------------------------------------------------------------------
# Ajustes comunes de Hypothesis
# ---------------------------------------------------------------------------

_PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,  # solo medimos corrección; la construcción de fakes puede variar
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Dobles de prueba
# ---------------------------------------------------------------------------


class _FakeRisk:
    """RiskPort falso que aprueba/rechaza y registra el orden de llamadas."""

    def __init__(self, approved: bool, reason: str = ""):
        self._decision = RiskDecision(approved=approved, reason=reason)
        self.calls: list = []

    def evaluate(self, proposed_order):
        self.calls.append(proposed_order)
        return self._decision


class _FakeOrder:
    """Orden devuelta por submit_order con id/status/precio."""

    def __init__(self, order_id="ord-1", status="filled", filled_avg_price="42000"):
        self.id = order_id
        self.status = status
        self.filled_avg_price = filled_avg_price


class _RecordingClient:
    """Cliente que registra cada request pasado a submit_order.

    ``side_effect`` es una lista de resultados por llamada: un ``Exception`` se
    lanza; cualquier otro valor se devuelve. Si se agotan los elementos, sigue
    lanzando/​devolviendo el último para no romper por índice.
    """

    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.requests: list = []

    def submit_order(self, order_data):
        self.requests.append(order_data)
        idx = min(len(self.requests) - 1, len(self._side_effects) - 1)
        effect = self._side_effects[idx]
        if isinstance(effect, Exception):
            raise effect
        return effect


def _make_factory(client):
    factory = mock.Mock()
    factory.build_trading_client.return_value = client
    return factory


def _collect_publisher():
    publisher = EventPublisher()
    events: list = []
    publisher.subscribe(events.append)
    return publisher, events


def _signal(action: Action, reason: str = "test", ts: datetime | None = None) -> Signal:
    return Signal(action=action, reason=reason, timestamp=ts or _BASE_TS)


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Acciones que envían orden (BUY/SELL) y el side esperado.
_buy_sell = st.sampled_from([Action.BUY, Action.SELL])

# Símbolos y cantidades del executor (pequeño espacio determinista y realista).
_symbols = st.sampled_from(["BTC/USD", "ETH/USD", "SOL/USD"])
_qtys = st.sampled_from(
    [Decimal("0.001"), Decimal("0.01"), Decimal("0.5"), Decimal("1"), Decimal("2.5")]
)

# Texto arbitrario (razones, ids, etc.).
_text = st.text(min_size=0, max_size=40)

# Timestamps distintos para variar el attempt_key.
_timestamps = st.integers(min_value=0, max_value=1_000_000).map(
    lambda m: _BASE_TS + timedelta(minutes=m)
)

# Precios enteros positivos para niveles y quotes.
_prices = st.integers(min_value=2, max_value=1_000_000)


def _side_of(action: Action) -> str:
    return "buy" if action is Action.BUY else "sell"


# ===========================================================================
# Property 1: BUY/SELL aprobado envía exactamente UNA orden y la registra.
# ===========================================================================


@_PBT_SETTINGS
@given(
    action=_buy_sell,
    symbol=_symbols,
    qty=_qtys,
    status=st.sampled_from(["filled", "accepted", "new", "partially_filled"]),
    ts=_timestamps,
)
def test_property_1_approved_submits_exactly_one_and_records(
    action, symbol, qty, status, ts
):
    # Feature: 04-order-execution, Property 1: Approved BUY/SELL submits exactly
    # one order and records it -- para cualquier señal BUY/SELL aprobada,
    # execute_signal consulta RiskPort.evaluate ANTES de enviar, hace exactamente
    # un submit_order con side/symbol/qty correctos, y el resultado registra
    # id/status/symbol/qty/side.
    # Validates: Requirements 1.1, 1.2, 1.3, 5.1, 5.2
    client = _RecordingClient([_FakeOrder(order_id="ord-1", status=status)])
    factory = _make_factory(client)
    risk = _FakeRisk(approved=True)
    publisher, events = _collect_publisher()

    executor = OrderExecutor(factory, risk, publisher, symbol=symbol, qty=qty)
    result = executor.execute_signal(_signal(action, ts=ts))

    side = _side_of(action)

    # evaluate se consultó exactamente una vez, ANTES de cualquier submit.
    assert len(risk.calls) == 1
    proposed = risk.calls[0]
    assert proposed.side == side
    assert proposed.symbol == symbol
    assert proposed.qty == qty

    # Exactamente UN submit_order con la request correcta.
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request.symbol == symbol
    assert request.qty == float(qty)
    assert request.side == (_OrderSide.BUY if action is Action.BUY else _OrderSide.SELL)

    # El resultado/registro lleva id/status/symbol/qty/side.
    assert result is not None
    assert result.event_type in (EventType.SUBMITTED, EventType.FILLED)
    assert result.symbol == symbol
    assert result.qty == qty
    assert result.side == side
    assert result.order_id == "ord-1"
    # El estado quedó recogido en algún evento publicado (SUBMITTED lleva status).
    submitted = [e for e in events if e.event_type == EventType.SUBMITTED]
    assert submitted and status in submitted[0].reason


# ===========================================================================
# Property 2: HOLD nunca envía.
# ===========================================================================


@_PBT_SETTINGS
@given(symbol=_symbols, qty=_qtys, reason=_text, ts=_timestamps)
def test_property_2_hold_never_submits(symbol, qty, reason, ts):
    # Feature: 04-order-execution, Property 2: HOLD never submits an order -- para
    # cualquier señal HOLD, submit_order nunca se llama, no se construye el cliente
    # ni se consulta al riesgo, y execute_signal devuelve None.
    # Validates: Requirements 1.4
    client = mock.Mock()
    factory = _make_factory(client)
    risk = _FakeRisk(approved=True)
    publisher, events = _collect_publisher()

    executor = OrderExecutor(factory, risk, publisher, symbol=symbol, qty=qty)
    result = executor.execute_signal(_signal(Action.HOLD, reason=reason, ts=ts))

    assert result is None
    client.submit_order.assert_not_called()
    factory.build_trading_client.assert_not_called()
    assert risk.calls == []
    assert events == []


# ===========================================================================
# Property 3: señal rechazada por riesgo -> no envía y emite RISK_BLOCK.
# ===========================================================================


@_PBT_SETTINGS
@given(action=_buy_sell, symbol=_symbols, qty=_qtys, reason=_text, ts=_timestamps)
def test_property_3_risk_rejection_blocks_and_emits_risk_block(
    action, symbol, qty, reason, ts
):
    # Feature: 04-order-execution, Property 3: A risk-rejected signal never submits
    # and emits RISK_BLOCK -- para cualquier señal BUY/SELL que el RiskPort rechaza
    # con un reason arbitrario, execute_signal no envía ninguna orden (ni construye
    # el cliente) y publica exactamente un RISK_BLOCK con ese reason.
    # Validates: Requirements 1.5, 5.1, 5.3
    client = mock.Mock()
    factory = _make_factory(client)
    risk = _FakeRisk(approved=False, reason=reason)
    publisher, events = _collect_publisher()

    executor = OrderExecutor(factory, risk, publisher, symbol=symbol, qty=qty)
    result = executor.execute_signal(_signal(action, ts=ts))

    # Riesgo consultado, pero ninguna orden enviada.
    assert len(risk.calls) == 1
    client.submit_order.assert_not_called()
    factory.build_trading_client.assert_not_called()

    # Exactamente un RISK_BLOCK con el reason del rechazo.
    risk_blocks = [e for e in events if e.event_type == EventType.RISK_BLOCK]
    assert len(risk_blocks) == 1
    assert risk_blocks[0].reason == reason
    assert result is not None
    assert result.event_type == EventType.RISK_BLOCK
    assert result.reason == reason


# ===========================================================================
# Property 4: id determinista + reintentos idempotentes sin 2ª orden.
# ===========================================================================


@_PBT_SETTINGS
@given(
    symbol_a=_symbols,
    side_a=st.sampled_from(["buy", "sell"]),
    key_a=_text,
    symbol_b=_symbols,
    side_b=st.sampled_from(["buy", "sell"]),
    key_b=_text,
)
def test_property_4_client_order_id_is_deterministic(
    symbol_a, side_a, key_a, symbol_b, side_b, key_b
):
    # Feature: 04-order-execution, Property 4: Deterministic id and idempotent
    # retries create no duplicate order (parte determinismo) -- make_client_order_id
    # es una función pura: misma entrada -> mismo id; y entradas distintas producen
    # ids distintos.
    # Validates: Requirements 3.1, 3.2
    id_a1 = make_client_order_id(symbol_a, side_a, key_a)
    id_a2 = make_client_order_id(symbol_a, side_a, key_a)
    assert id_a1 == id_a2  # determinista

    if (symbol_a, side_a, key_a) != (symbol_b, side_b, key_b):
        assert id_a1 != make_client_order_id(symbol_b, side_b, key_b)


@_PBT_SETTINGS
@given(
    action=_buy_sell,
    symbol=_symbols,
    qty=_qtys,
    ts=_timestamps,
    n_failures=st.integers(min_value=0, max_value=5),
)
def test_property_4_transient_retries_reuse_same_id_and_record_at_most_one(
    action, symbol, qty, ts, n_failures
):
    # Feature: 04-order-execution, Property 4: Deterministic id and idempotent
    # retries create no duplicate order (parte reintentos) -- ante N fallos
    # transitorios (TimeoutError) seguidos de éxito o de nada, el executor reintenta
    # con el MISMO client_order_id, hace a lo sumo MAX_ATTEMPTS (3) intentos, y
    # registra a lo sumo UNA orden lógica (un solo evento terminal SUBMITTED/FILLED).
    # Validates: Requirements 3.1, 3.2, 3.4, 3.5
    max_attempts = OrderExecutor.MAX_ATTEMPTS
    # Los primeros n_failures intentos fallan; el resto (si queda) tiene éxito.
    effects: list = [TimeoutError("network timeout") for _ in range(n_failures)]
    effects.append(_FakeOrder(order_id="ord-retry", status="accepted"))
    client = _RecordingClient(effects)
    factory = _make_factory(client)
    risk = _FakeRisk(approved=True)
    publisher, events = _collect_publisher()

    executor = OrderExecutor(factory, risk, publisher, symbol=symbol, qty=qty)
    result = executor.execute_signal(_signal(action, ts=ts))

    side = _side_of(action)
    attempt_key = _signal(action, ts=ts).timestamp.isoformat() + "|" + action.value
    expected_id = make_client_order_id(symbol, side, attempt_key)

    # A lo sumo 3 intentos.
    assert 1 <= len(client.requests) <= max_attempts
    # Todos los intentos reutilizan EXACTAMENTE el mismo client_order_id.
    for req in client.requests:
        assert req.client_order_id == expected_id

    # A lo sumo una orden lógica registrada: como máximo un evento terminal
    # SUBMITTED/FILLED (0 si se agotaron los reintentos -> ERROR).
    terminal = [
        e for e in events if e.event_type in (EventType.SUBMITTED, EventType.FILLED)
    ]
    assert len(terminal) <= 1

    if n_failures < max_attempts:
        # Hubo un intento con éxito dentro del límite -> exactamente una orden.
        assert len(terminal) == 1
        assert result is not None
        assert result.order_id == "ord-retry"
    else:
        # Reintentos agotados sin confirmar -> ninguna orden, evento ERROR.
        assert terminal == []
        assert result is not None
        assert result.event_type == EventType.ERROR


# ===========================================================================
# Property 5: SL/TP cierran con el evento correcto; sin niveles no cierra.
# ===========================================================================


class _CloseClient:
    def __init__(self) -> None:
        self.closed: list[str] = []

    def close_position(self, symbol: str) -> None:
        self.closed.append(symbol)


def _quote(price) -> Quote:
    return Quote(timestamp=_BASE_TS, price=Decimal(price))


@_PBT_SETTINGS
@given(
    entry=_prices,
    sl_gap=st.integers(min_value=1, max_value=1_000),
    tp_gap=st.integers(min_value=1, max_value=1_000),
    hit=st.sampled_from(["sl", "tp"]),
    beyond=st.integers(min_value=0, max_value=1_000),
    qty=_qtys,
)
def test_property_5_levels_close_with_correct_event(
    entry, sl_gap, tp_gap, hit, beyond, qty
):
    # Feature: 04-order-execution, Property 5: SL/TP thresholds close the position
    # with the correct event -- con sl < entry < tp, un precio <= SL emite
    # STOP_LOSS_CLOSE y un precio >= TP emite TAKE_PROFIT_CLOSE, cerrando la posición.
    # Validates: Requirements 2.3, 2.4, 2.5, 2.6
    stop_loss = Decimal(entry - sl_gap)  # < entry (entry >= 2, sl_gap>=1 -> puede ser 1)
    take_profit = Decimal(entry + tp_gap)  # > entry

    client = _CloseClient()
    factory = _make_factory(client)
    publisher, events = _collect_publisher()
    manager = PositionManager(factory=factory, publisher=publisher)
    manager.open_position(
        "BTC/USD",
        "buy",
        qty,
        entry_price=Decimal(entry),
        stop_loss=stop_loss,
        take_profit=take_profit,
    )

    if hit == "sl":
        price = stop_loss - Decimal(beyond)  # <= SL
        expected = EventType.STOP_LOSS_CLOSE
    else:
        price = take_profit + Decimal(beyond)  # >= TP
        expected = EventType.TAKE_PROFIT_CLOSE

    manager.on_quote(_quote(price))

    assert manager.position is None  # posición cerrada
    assert client.closed == ["BTC/USD"]
    assert len(events) == 1
    assert events[0].event_type == expected
    assert events[0].price == price


@_PBT_SETTINGS
@given(entry=_prices, price=_prices, qty=_qtys)
def test_property_5_no_levels_never_closes(entry, price, qty):
    # Feature: 04-order-execution, Property 5: no levels means no close -- una
    # posición abierta sin SL ni TP no dispara ningún cierre para ningún precio.
    # Validates: Requirements 2.6
    client = _CloseClient()
    factory = _make_factory(client)
    publisher, events = _collect_publisher()
    manager = PositionManager(factory=factory, publisher=publisher)
    manager.open_position("BTC/USD", "buy", qty, entry_price=Decimal(entry))

    manager.on_quote(_quote(price))

    assert manager.position is not None  # sigue abierta
    assert client.closed == []
    assert events == []


# ===========================================================================
# Property 6: un suscriptor que falla no interrumpe la ejecución.
# ===========================================================================


@_PBT_SETTINGS
@given(
    n_good_before=st.integers(min_value=0, max_value=4),
    n_bad=st.integers(min_value=1, max_value=3),
    n_good_after=st.integers(min_value=0, max_value=4),
    action=_buy_sell,
)
def test_property_6_failing_subscriber_does_not_interrupt(
    n_good_before, n_bad, n_good_after, action
):
    # Feature: 04-order-execution, Property 6: A failing subscriber never interrupts
    # execution -- con >=1 suscriptor que lanza, publish entrega el evento a los
    # demás suscriptores y retorna normalmente, de modo que la ejecución del
    # executor continúa (se produce el evento terminal esperado).
    # Validates: Requirements 4.3
    publisher = EventPublisher()

    received_before = [[] for _ in range(n_good_before)]
    received_after = [[] for _ in range(n_good_after)]

    # Buenos suscriptores antes.
    for bucket in received_before:
        publisher.subscribe(bucket.append)

    # Suscriptores que fallan.
    def _raiser(_event):
        raise RuntimeError("subscriber boom")

    for _ in range(n_bad):
        publisher.subscribe(_raiser)

    # Buenos suscriptores después (registrados tras los que fallan).
    for bucket in received_after:
        publisher.subscribe(bucket.append)

    client = _RecordingClient([_FakeOrder(order_id="ord-6", status="accepted")])
    factory = _make_factory(client)
    risk = _FakeRisk(approved=True)

    executor = OrderExecutor(factory, risk, publisher)
    result = executor.execute_signal(_signal(action))

    # La ejecución completó pese a los suscriptores que lanzan.
    assert result is not None
    assert result.event_type in (EventType.SUBMITTED, EventType.FILLED)
    assert len(client.requests) == 1

    # Todos los suscriptores sanos (antes y después del que falla) recibieron
    # el/los evento(s): al menos el SUBMITTED.
    for bucket in received_before + received_after:
        assert len(bucket) >= 1


@_PBT_SETTINGS
@given(
    n_bad=st.integers(min_value=1, max_value=5),
    n_good=st.integers(min_value=1, max_value=5),
)
def test_property_6_publish_returns_and_delivers_to_others(n_bad, n_good):
    # Feature: 04-order-execution, Property 6: A failing subscriber never interrupts
    # execution -- publish, con cualquier mezcla de suscriptores que fallan y
    # suscriptores sanos, retorna normalmente y entrega el evento a todos los sanos.
    # Validates: Requirements 4.3
    publisher = EventPublisher()

    def _raiser(_event):
        raise ValueError("boom")

    good_buckets = [[] for _ in range(n_good)]
    # Intercalamos malos y buenos para no depender del orden.
    for i in range(max(n_bad, n_good)):
        if i < n_bad:
            publisher.subscribe(_raiser)
        if i < n_good:
            publisher.subscribe(good_buckets[i].append)

    event = OrderEvent(event_type=EventType.SUBMITTED, symbol="BTC/USD", side="buy")
    # No debe lanzar.
    publisher.publish(event)

    for bucket in good_buckets:
        assert bucket == [event]


# ===========================================================================
# Property 7: ningún evento contiene secretos.
# ===========================================================================

# Materiales de credenciales reconocibles que NUNCA deben aparecer en un evento.
_API_KEY = "AKSECRETKEY1234567890"
_API_SECRET = "shhh-super-secret-value-0987654321"


def _event_repr(event: OrderEvent) -> str:
    """Representación exhaustiva del evento: repr + todos sus campos como texto."""
    parts = [repr(event)]
    for value in vars(event).values():
        parts.append(str(value))
    return " ".join(parts)


@_PBT_SETTINGS
@given(
    action=st.sampled_from([Action.BUY, Action.SELL, Action.HOLD]),
    approved=st.booleans(),
    reject_reason=_text,
    symbol=_symbols,
    qty=_qtys,
    ts=_timestamps,
    outcome=st.sampled_from(["ok", "reject", "transient"]),
)
def test_property_7_no_event_contains_secrets(
    action, approved, reject_reason, symbol, qty, ts, outcome
):
    # Feature: 04-order-execution, Property 7: No emitted event contains secrets or
    # credentials -- para cualquier OrderEvent producido por la capa de ejecución
    # (éxito, RISK_BLOCK, REJECTED o ERROR), ninguno de sus campos contiene el
    # material de credenciales (api_key / api_secret) usado para construir el
    # factory/cliente.
    # Validates: Requirements 4.2
    # El cliente y el factory "conocen" el secreto, pero la capa jamás debe
    # filtrarlo a un evento.
    if outcome == "ok":
        result_effect = _FakeOrder(order_id="ord-7", status="filled")
        client = _RecordingClient([result_effect])
    elif outcome == "reject":
        client = _RecordingClient(
            [_FakeAPIError("rejected: insufficient buying power", status_code=422)]
        )
    else:  # transient -> se agota en ERROR
        client = _RecordingClient([TimeoutError("network down")])

    # Guardamos el secreto en el propio cliente/factory para simular que el
    # material existe en la capa de infraestructura.
    client.api_key = _API_KEY  # type: ignore[attr-defined]
    client.api_secret = _API_SECRET  # type: ignore[attr-defined]
    factory = _make_factory(client)
    factory.api_key = _API_KEY
    factory.api_secret = _API_SECRET

    risk = _FakeRisk(approved=approved, reason=reject_reason)
    publisher, events = _collect_publisher()

    executor = OrderExecutor(factory, risk, publisher)
    result = executor.execute_signal(_signal(action, ts=ts))

    # Reunimos todos los eventos producidos (publicados + el devuelto).
    produced = list(events)
    if isinstance(result, OrderEvent):
        produced.append(result)

    for event in produced:
        blob = _event_repr(event)
        assert _API_KEY not in blob
        assert _API_SECRET not in blob
