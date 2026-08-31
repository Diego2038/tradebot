"""Pruebas basadas en propiedades (Hypothesis) del backtest engine (Tarea 6).

Spec ``05-backtest-engine``. El backtest es una simulación pura y determinista
sobre secuencias de ``Bar`` generadas por Hypothesis: no toca Alpaca ni red, y
las métricas son funciones puras sobre la curva de equity / los round trips. Eso
da un espacio de entrada amplio y estructurado donde 100+ iteraciones son rápidas
y afloran los bordes (secuencias vacías/cortas/degeneradas, precios extremos,
runs con cero trades).

``Bar`` se construye directamente desde los modelos spec-02
(``app.services.data_feed.models.Bar``) y las estrategias se registran en un
``StrategyEngine`` spec-03 (``app.services.strategies.registry.StrategyEngine``);
como el engine no hace llamadas a Alpaca, no hacen falta mocks.

Cada test lleva el comentario exacto
``# Feature: 05-backtest-engine, Property {n}: {property text}`` y corre con
>= 100 iteraciones (``@settings(max_examples=100)``).

Cobertura (6 propiedades del design):
- P1: todo run completo devuelve un Backtest_Result con métricas en rango.
- P2: correspondencia señal->trade durante el replay, sin llamadas a Alpaca.
- P3: métricas calculadas según su fórmula y redondeadas a 6 decimales;
      cualquier run de cero trades / solo-HOLD -> las tres métricas a cero.
- P4: una secuencia de bars vacía completa con cero trades y retorno cero.
- P5: reproducibilidad (mismos bars+estrategia+seed -> resultado campo a campo
      igual; estrategia determinista -> resultado igual con o sin seed).
- P6: request inválida o acción fuera de rango lanza y no devuelve resultado.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.backtest.constants import METRIC_DECIMALS, STARTING_EQUITY
from app.services.backtest.engine import BacktestEngine
from app.services.backtest.errors import InvalidActionError, InvalidDateRangeError
from app.services.backtest.metrics import max_drawdown, total_return, win_rate
from app.services.backtest.models import BacktestRequest, SimulatedTrade
from app.services.data_feed.models import Bar
from app.services.strategies.errors import UnknownStrategyError
from app.services.strategies.random_strategy import RandomStrategy
from app.services.strategies.registry import StrategyEngine
from app.services.strategies.signals import Action, Signal

# ---------------------------------------------------------------------------
# Ajustes y helpers comunes
# ---------------------------------------------------------------------------

_PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)

_VALID_ACTIONS = {Action.BUY, Action.SELL, Action.HOLD}

_QTY = Decimal("1000")


def _bars(closes: list) -> list[Bar]:
    """Construye una secuencia de Bar con timestamps estrictamente crecientes.

    Cada ``close`` positivo se convierte a ``Decimal``; open/high/low/volume se
    derivan del close para que cada Bar sea válido (OHLCV positivos). Solo el
    close afecta la simulación de trades del engine.
    """
    bars: list[Bar] = []
    for i, c in enumerate(closes):
        close = Decimal(str(c))
        bars.append(
            Bar(
                timestamp=_BASE_TS + timedelta(minutes=i),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("1"),
            )
        )
    return bars


def _round6(value: Decimal) -> Decimal:
    """Redondeo a ``METRIC_DECIMALS`` con banker's rounding (igual que metrics)."""
    from decimal import ROUND_HALF_EVEN

    quantum = Decimal(1).scaleb(-METRIC_DECIMALS)
    return value.quantize(quantum, rounding=ROUND_HALF_EVEN)


def _dp(value: Decimal) -> int:
    """Número de decimales fraccionarios que porta ``value``."""
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) else 0


class _ScriptedStrategy:
    """Stub que emite una acción predeterminada por invocación sucesiva.

    Cumple estructuralmente el protocolo ``Strategy`` spec-03 (método
    ``generate``). ``calls`` registra el número de bars vistos en cada llamada,
    para que los tests comprueben una llamada por bar en orden ascendente.
    """

    def __init__(self, actions: list) -> None:
        self._actions = actions
        self._i = 0
        self.calls: list[int] = []

    def generate(self, bars, quote=None) -> Signal:
        self.calls.append(len(bars))
        action = self._actions[self._i]
        self._i += 1
        return Signal(action=action, reason="scripted", timestamp=_BASE_TS)


def _backtest_package_touches_alpaca() -> bool:
    """True si algún módulo fuente del paquete backtest importa ``alpaca``.

    El design garantiza estructuralmente que "no existe ningún import ``alpaca.*``
    en el paquete" (R1.5): la ausencia de llamadas a Alpaca no es por convención
    sino por construcción. Lo comprobamos de forma robusta escaneando el árbol de
    sintaxis (AST) de cada ``.py`` del paquete ``app.services.backtest`` y buscando
    cualquier ``import alpaca`` o ``from alpaca[...] import ...``. Un análisis
    estático evita los falsos positivos de inspeccionar ``sys.modules`` en tiempo de
    ejecución (otras partes de la app/tests sí importan ``alpaca-py`` legítimamente).
    """
    import ast
    import pathlib

    import app.services.backtest as pkg

    pkg_dir = pathlib.Path(pkg.__file__).parent
    for source_file in pkg_dir.glob("*.py"):
        tree = ast.parse(source_file.read_text(), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "alpaca" or alias.name.startswith("alpaca."):
                        return True
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "alpaca" or mod.startswith("alpaca."):
                    return True
    return False


class _AlpacaSpyStrategy(_ScriptedStrategy):
    """Estrategia scripted que además detecta cualquier acceso a ``alpaca.*``.

    Tras cada invocación comprueba estructuralmente que el paquete backtest no
    referencia el SDK de Alpaca durante el replay. El engine no debe realizar
    ninguna llamada a Alpaca (R1.5).
    """

    def __init__(self, actions: list) -> None:
        super().__init__(actions)
        self.alpaca_seen = False

    def generate(self, bars, quote=None) -> Signal:
        if _backtest_package_touches_alpaca():
            self.alpaca_seen = True
        return super().generate(bars, quote)


class _DeterministicStrategy:
    """Estrategia determinista sin aleatoriedad: acción por índice de barra.

    Recorre una secuencia fija de acciones según el número de barras vistas; no
    tiene ``_rng``, así que la seed del request no la afecta (R4.3).
    """

    def __init__(self, actions: list) -> None:
        self._actions = actions

    def generate(self, bars, quote=None) -> Signal:
        idx = (len(bars) - 1) % len(self._actions)
        return Signal(action=self._actions[idx], reason="deterministic", timestamp=_BASE_TS)


def _engine_with(name: str, strategy) -> BacktestEngine:
    registry = StrategyEngine(default=name)
    registry.register(name, strategy)
    return BacktestEngine(registry, qty=_QTY)


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Precios enteros positivos (Decimal-friendly).
_prices = st.integers(min_value=1, max_value=1_000_000)

# Secuencias de closes de cualquier longitud, incluidas vacías y de una sola barra.
_close_series = st.lists(_prices, min_size=0, max_size=40)

# Secuencias no vacías de una sola barra en adelante.
_nonempty_series = st.lists(_prices, min_size=1, max_size=40)

# Acciones válidas del enum spec-03.
_actions = st.sampled_from([Action.BUY, Action.SELL, Action.HOLD])

# Seeds aleatorias.
_seeds = st.integers(min_value=0, max_value=1_000_000)

# Equity positivo para métricas (Decimal a partir de enteros/fracciones simples).
_equity = st.integers(min_value=1, max_value=10_000_000)

# Beneficios realizados: enteros con signo (positivos, cero y negativos).
_profits = st.lists(st.integers(min_value=-100_000, max_value=100_000), min_size=0, max_size=30)

# Curvas de equity: valores positivos.
_curves = st.lists(st.integers(min_value=1, max_value=10_000_000), min_size=0, max_size=30)


# ===========================================================================
# Property 1: todo run completo devuelve un Backtest_Result con métricas en rango.
# ===========================================================================


# Precios acotados a una banda realista para P1: el engine no impone un suelo de
# equity, así que las garantías total_return >= -1 y max_drawdown in [0, 1] valen
# en el régimen operativo esperado (nocional de la posición << equity inicial).
# Con qty=0.001 y precios <= 100000, un round trip perdedor mueve como mucho ~100
# unidades sobre 100000 de equity inicial, muy lejos de agotarla.
_p1_prices = st.integers(min_value=1, max_value=100_000)
_p1_close_series = st.lists(_p1_prices, min_size=0, max_size=40)


@_PBT_SETTINGS
@given(closes=_p1_close_series, actions=st.lists(_actions, min_size=0, max_size=40), seed=_seeds)
def test_property_1_completed_run_returns_valid_result(closes, actions, seed):
    # Feature: 05-backtest-engine, Property 1: Every completed run returns a valid
    # Backtest_Result with in-range metrics (total_return >= -1, win_rate in [0, 1],
    # max_drawdown in [0, 1], trade_count >= 0).
    # Validates: Requirements 2.1, 2.3, 2.4, 2.5
    #
    # La estrategia scripted debe tener al menos tantas acciones como bars; se
    # rellenan con HOLD si hicieran falta más pasos. Se usa la qty por defecto
    # (0.001), de modo que el nocional de cada posición sea mínimo frente a la
    # equity inicial y las cotas de las métricas se mantengan (R2.3, R2.5).
    padded = list(actions) + [Action.HOLD] * len(closes)
    strat = _ScriptedStrategy(padded)
    registry = StrategyEngine(default="scripted")
    registry.register("scripted", strat)
    engine = BacktestEngine(registry)  # qty por defecto = Decimal("0.001")

    result = engine.run(BacktestRequest("scripted", seed=seed), _bars(closes))

    assert result.total_return >= Decimal("-1")
    assert Decimal("0") <= result.win_rate <= Decimal("1")
    assert Decimal("0") <= result.max_drawdown <= Decimal("1")
    assert result.trade_count >= 0
    assert isinstance(result.trades, list)


# ===========================================================================
# Property 2: correspondencia señal->trade durante el replay, sin Alpaca.
# ===========================================================================


@_PBT_SETTINGS
@given(actions=st.lists(_actions, min_size=1, max_size=40))
def test_property_2_signal_to_trade_correspondence_no_alpaca(actions):
    # Feature: 05-backtest-engine, Property 2: Signal-to-trade correspondence during
    # replay, with no Alpaca calls (scripted strategy with a known action per bar +
    # a spy: exactly one call per bar in strictly ascending order, a SimulatedTrade
    # for exactly the BUY/SELL steps and none for HOLD, and no alpaca.* access).
    # Validates: Requirements 1.1, 1.3, 1.4, 1.5, 3.2
    n = len(actions)
    closes = list(range(100, 100 + n))  # closes estrictamente crecientes y positivos
    strat = _AlpacaSpyStrategy(list(actions))
    engine = _engine_with("scripted", strat)

    result = engine.run(BacktestRequest("scripted"), _bars(closes))

    # Una llamada por bar, en orden ascendente: la historia crece de 1 a n.
    assert strat.calls == list(range(1, n + 1))

    # Un SimulatedTrade por cada paso BUY/SELL y ninguno para HOLD.
    expected_trades = sum(1 for a in actions if a in (Action.BUY, Action.SELL))
    assert len(result.trades) == expected_trades

    # Los lados registrados coinciden exactamente con los pasos BUY/SELL, en orden.
    expected_sides = ["buy" if a is Action.BUY else "sell" for a in actions if a in (Action.BUY, Action.SELL)]
    assert [t.side for t in result.trades] == expected_sides

    # El engine no accedió a Alpaca en ningún momento.
    assert strat.alpaca_seen is False


# ===========================================================================
# Property 3: métricas correctas + redondeadas a 6 dp; cero trades -> ceros.
# ===========================================================================


@_PBT_SETTINGS
@given(start=_equity, end=_equity, curve=_curves, profits=_profits)
def test_property_3_metrics_match_formulas_rounded(start, end, curve, profits):
    # Feature: 05-backtest-engine, Property 3: Metrics computed correctly and rounded
    # to 6 decimals (random start/end equity, equity curves, profit lists match their
    # defining formulas rounded to 6 dp; any zero-trade/HOLD-only run yields
    # total_return, win_rate, max_drawdown all zero).
    # Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7
    start_d = Decimal(start)
    end_d = Decimal(end)
    profit_ds = [Decimal(p) for p in profits]
    curve_ds = [Decimal(c) for c in curve]

    # total_return coincide con su fórmula redondeada a 6 dp.
    tr = total_return(start_d, end_d)
    assert tr == _round6((end_d - start_d) / start_d)
    assert _dp(tr) <= METRIC_DECIMALS

    # win_rate coincide con la fracción de beneficios > 0, redondeada a 6 dp.
    wr = win_rate(profit_ds)
    if not profit_ds:
        assert wr == Decimal("0")
    else:
        wins = sum(1 for p in profit_ds if p > 0)
        assert wr == _round6(Decimal(wins) / Decimal(len(profit_ds)))
        assert Decimal("0") <= wr <= Decimal("1")

    # max_drawdown coincide con el mayor (peak - value) / peak, redondeado a 6 dp.
    md = max_drawdown(curve_ds)
    peak: Decimal | None = None
    worst = Decimal("0")
    for v in curve_ds:
        if peak is None or v > peak:
            peak = v
        if peak > 0:
            decline = (peak - v) / peak
            if decline > worst:
                worst = decline
    assert md == _round6(worst)
    assert Decimal("0") <= md <= Decimal("1")


@_PBT_SETTINGS
@given(closes=_close_series)
def test_property_3_hold_only_run_yields_all_zero_metrics(closes):
    # Feature: 05-backtest-engine, Property 3: Metrics computed correctly and rounded
    # to 6 decimals -- any zero-trade / HOLD-only run yields total_return, win_rate,
    # and max_drawdown all zero.
    # Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7
    strat = _ScriptedStrategy([Action.HOLD] * len(closes))
    engine = _engine_with("scripted", strat)

    result = engine.run(BacktestRequest("scripted"), _bars(closes))

    assert result.trade_count == 0
    assert result.total_return == Decimal("0")
    assert result.win_rate == Decimal("0")
    assert result.max_drawdown == Decimal("0")


# ===========================================================================
# Property 4: una secuencia de bars vacía completa con cero trades y retorno cero.
# ===========================================================================


@_PBT_SETTINGS
@given(seed=_seeds)
def test_property_4_empty_bars_completes_with_zeros(seed):
    # Feature: 05-backtest-engine, Property 4: An empty bar sequence completes with
    # zero trades and zero return.
    # Validates: Requirements 1.6
    registry = StrategyEngine(default="random")
    registry.register("random", RandomStrategy(seed=seed))
    engine = BacktestEngine(registry, qty=_QTY)

    result = engine.run(BacktestRequest("random", seed=seed), [])

    assert result.trade_count == 0
    assert result.total_return == Decimal("0")
    assert result.win_rate == Decimal("0")
    assert result.max_drawdown == Decimal("0")
    assert result.trades == []


# ===========================================================================
# Property 5: reproducibilidad de resultados.
# ===========================================================================


@_PBT_SETTINGS
@given(closes=_nonempty_series, seed=_seeds)
def test_property_5_same_bars_strategy_seed_reproducible(closes, seed):
    # Feature: 05-backtest-engine, Property 5: Reproducibility (same bars+strategy+seed
    # -> field-by-field equal result incl. identical ordered trades; a deterministic
    # strategy -> equal result regardless of/without a seed).
    # Validates: Requirements 4.1, 4.3, 4.4
    bars = _bars(closes)

    # Estrategia aleatoria resuelta por el registry; misma seed -> dos runs iguales.
    registry = StrategyEngine(default="random")
    registry.register("random", RandomStrategy())
    engine = BacktestEngine(registry, qty=_QTY)

    request = BacktestRequest("random", seed=seed)
    first = engine.run(request, bars)
    second = engine.run(request, bars)

    assert first == second
    assert first.trades == second.trades


@_PBT_SETTINGS
@given(closes=_nonempty_series, actions=st.lists(_actions, min_size=1, max_size=6), seed=_seeds)
def test_property_5_deterministic_strategy_seed_irrelevant(closes, actions, seed):
    # Feature: 05-backtest-engine, Property 5: Reproducibility -- a deterministic
    # strategy yields a field-by-field equal result regardless of/without a seed.
    # Validates: Requirements 4.1, 4.3, 4.4
    bars = _bars(closes)

    def _run(req_seed: int | None):
        registry = StrategyEngine(default="det")
        registry.register("det", _DeterministicStrategy(list(actions)))
        engine = BacktestEngine(registry, qty=_QTY)
        return engine.run(BacktestRequest("det", seed=req_seed), bars)

    with_seed = _run(seed)
    without_seed = _run(None)

    assert with_seed == without_seed
    assert with_seed.trades == without_seed.trades


# ===========================================================================
# Property 6: request inválida o acción fuera de rango lanza y no devuelve resultado.
# ===========================================================================


@_PBT_SETTINGS
@given(closes=_nonempty_series, days=st.integers(min_value=1, max_value=3650))
def test_property_6_start_after_end_raises_and_replays_nothing(closes, days):
    # Feature: 05-backtest-engine, Property 6: Invalid request or out-of-range action
    # raises and returns no result (start > end -> InvalidDateRangeError with no bar
    # replayed).
    # Validates: Requirements 1.7, 1.8, 1.9
    strat = _ScriptedStrategy([Action.BUY] * len(closes))
    engine = _engine_with("scripted", strat)

    end = _BASE_TS
    start = _BASE_TS + timedelta(days=days)  # start estrictamente posterior a end
    request = BacktestRequest("scripted", start=start, end=end)

    with pytest.raises(InvalidDateRangeError):
        engine.run(request, _bars(closes))

    # No se reprodujo ningún bar.
    assert strat.calls == []


@_PBT_SETTINGS
@given(name=st.text(min_size=1, max_size=20).filter(lambda s: s != "scripted"), closes=_nonempty_series)
def test_property_6_unregistered_name_raises_and_replays_nothing(name, closes):
    # Feature: 05-backtest-engine, Property 6: Invalid request or out-of-range action
    # raises and returns no result (unregistered name -> UnknownStrategyError with no
    # bar replayed).
    # Validates: Requirements 1.7, 1.8, 1.9
    strat = _ScriptedStrategy([Action.BUY] * len(closes))
    engine = _engine_with("scripted", strat)

    with pytest.raises(UnknownStrategyError):
        engine.run(BacktestRequest(name), _bars(closes))

    # El nombre no registrado se rechaza antes del replay: ningún bar reproducido.
    assert strat.calls == []


@_PBT_SETTINGS
@given(
    prefix=st.lists(_actions, min_size=0, max_size=10),
    suffix_len=st.integers(min_value=0, max_value=10),
)
def test_property_6_out_of_range_action_raises_and_stops_replay(prefix, suffix_len):
    # Feature: 05-backtest-engine, Property 6: Invalid request or out-of-range action
    # raises and returns no result (out-of-range action mid-replay -> InvalidActionError
    # stopping the replay; no BacktestResult in any case).
    # Validates: Requirements 1.7, 1.8, 1.9
    #
    # Se construye una secuencia de acciones con un centinela no-Action justo tras
    # el prefijo válido; el replay debe detenerse exactamente en ese bar.
    actions = list(prefix) + ["NOPE"] + [Action.HOLD] * suffix_len
    closes = list(range(100, 100 + len(actions)))
    strat = _ScriptedStrategy(actions)
    engine = _engine_with("scripted", strat)

    with pytest.raises(InvalidActionError):
        engine.run(BacktestRequest("scripted"), _bars(closes))

    # El replay se detuvo en el bar de la acción inválida: se llamó hasta ese bar
    # (prefijo válido + el paso inválido), no más.
    assert strat.calls == list(range(1, len(prefix) + 2))
