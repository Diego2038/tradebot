"""Pruebas basadas en propiedades (Hypothesis) del strategy engine (Tarea 7).

Spec ``03-strategy-engine``. Ejercitan la lógica pura/determinista de la feature
(estrategias, indicadores y registro) sobre secuencias de ``Bar`` y series de
precios generadas por Hypothesis. Esta spec NO toca Alpaca ni red: ``Bar``/``Quote``
son dataclasses puras de ``data_feed.models`` y se importan directamente, sin
arrastrar el SDK.

Cada test lleva un comentario "Feature: 03-strategy-engine, Property N: ...".
Todas las propiedades corren con >= 100 iteraciones (@settings(max_examples=100)).

Cobertura (6 propiedades del design):
- P1: toda estrategia (random y predictive) devuelve SIEMPRE una Signal válida.
- P2: RandomStrategy con misma seed -> misma secuencia de acciones.
- P3: datos vacíos/insuficientes -> HOLD, sin error.
- P4: indicadores puros con propiedades conocidas (determinismo, SMA de constante,
      RSI en [0, 100]).
- P5: un cruce SMA construido fuerza la acción esperada (arriba -> BUY, abajo -> SELL).
- P6: nombre no registrado -> UnknownStrategyError y active mode sin cambios.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.data_feed.models import Bar, Quote
from app.services.strategies.indicators import rsi, sma
from app.services.strategies.predictive_strategy import PredictiveStrategy
from app.services.strategies.random_strategy import RandomStrategy
from app.services.strategies.registry import StrategyEngine, build_default_engine
from app.services.strategies.errors import UnknownStrategyError
from app.services.strategies.signals import Action, Signal


# ---------------------------------------------------------------------------
# Ajustes y helpers comunes
# ---------------------------------------------------------------------------

_PBT_SETTINGS = settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# P5 construye series y ejecuta la estrategia; desactivamos el deadline para no
# medir latencia (solo corrección) y evitar flakes por variaciones de tiempo.
_PBT_SETTINGS_NO_DEADLINE = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)

_VALID_ACTIONS = {Action.BUY, Action.SELL, Action.HOLD}


def _bars(closes) -> list[Bar]:
    """Construye Bars con timestamps crecientes y un ``close`` dado.

    open/high/low/volume se derivan del close para que cada Bar sea válido; solo
    el close importa para las estrategias predictivas.
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


def _assert_valid_signal(sig: Signal) -> None:
    """Toda Signal válida: action en el enum, reason no vacío, timestamp presente."""
    assert isinstance(sig, Signal)
    assert sig.action in _VALID_ACTIONS
    assert isinstance(sig.reason, str) and sig.reason.strip() != ""
    assert sig.timestamp is not None


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Precios enteros positivos, deterministas y fáciles de convertir a Decimal.
_prices = st.integers(min_value=1, max_value=1_000_000)

# Series de closes de cualquier longitud, INCLUIDAS vacías y cortas (min_size=0).
_close_series = st.lists(_prices, min_size=0, max_size=40)

# Series no vacías para los indicadores puros.
_nonempty_series = st.lists(_prices, min_size=1, max_size=40)


# ===========================================================================
# Property 1: toda estrategia devuelve SIEMPRE una Signal válida.
# ===========================================================================


@_PBT_SETTINGS
@given(closes=_close_series, seed=st.integers(min_value=0, max_value=1_000_000))
def test_property_1_random_always_returns_valid_signal(closes, seed):
    # Feature: 03-strategy-engine, Property 1: Every strategy always returns a
    # valid Signal -- para cualquier secuencia de Bar (incluida vacía o corta),
    # RandomStrategy.generate devuelve una Signal cuyo action está en
    # {BUY, SELL, HOLD}, con reason no vacío y timestamp presente.
    # Validates: Requirements 1.1, 1.2, 1.5, 2.1, 2.3
    strat = RandomStrategy(seed=seed)
    sig = strat.generate(_bars(closes))
    _assert_valid_signal(sig)


@_PBT_SETTINGS
@given(closes=_close_series)
def test_property_1_predictive_always_returns_valid_signal(closes):
    # Feature: 03-strategy-engine, Property 1: Every strategy always returns a
    # valid Signal -- para cualquier secuencia de Bar (incluida vacía o corta),
    # PredictiveStrategy.generate devuelve una Signal válida sin lanzar error.
    # Se usan periodos pequeños para que también las series cortas activen la
    # rama con datos suficientes en algunos casos.
    # Validates: Requirements 1.1, 1.2, 1.5, 2.1, 2.3
    strat = PredictiveStrategy(
        short_period=2, long_period=3, rsi_period=2, rsi_oversold=30, rsi_overbought=70
    )
    sig = strat.generate(_bars(closes))
    _assert_valid_signal(sig)


@_PBT_SETTINGS
@given(closes=_close_series, price=_prices)
def test_property_1_random_with_only_quote_returns_valid_signal(closes, price):
    # Feature: 03-strategy-engine, Property 1: Every strategy always returns a
    # valid Signal -- incluso cuando bars está vacío pero hay un Quote, la Signal
    # sigue siendo válida (action en el enum, reason no vacío, timestamp).
    # Validates: Requirements 1.1, 1.2, 1.5, 2.1, 2.3
    strat = RandomStrategy(seed=123)
    quote = Quote(timestamp=_BASE_TS, price=Decimal(price))
    sig = strat.generate(_bars(closes), quote)
    _assert_valid_signal(sig)


# ===========================================================================
# Property 2: RandomStrategy con misma seed -> misma secuencia de acciones.
# ===========================================================================


@_PBT_SETTINGS
@given(
    seed=st.integers(min_value=0, max_value=1_000_000),
    n=st.integers(min_value=1, max_value=50),
)
def test_property_2_seeded_random_is_reproducible(seed, n):
    # Feature: 03-strategy-engine, Property 2: Seeded random is reproducible --
    # dos instancias independientes RandomStrategy(seed) con la misma seed y la
    # misma secuencia de N invocaciones producen exactamente la misma secuencia
    # de acciones. Se usan bars no vacíos para forzar la rama aleatoria (no HOLD
    # por falta de datos).
    # Validates: Requirements 2.5
    bars = _bars([10, 11, 12])  # datos suficientes para no caer en el HOLD trivial

    a = RandomStrategy(seed=seed)
    b = RandomStrategy(seed=seed)

    actions_a = [a.generate(bars).action for _ in range(n)]
    actions_b = [b.generate(bars).action for _ in range(n)]

    assert actions_a == actions_b


# ===========================================================================
# Property 3: datos vacíos o insuficientes -> HOLD, sin error.
# ===========================================================================


@_PBT_SETTINGS
@given(seed=st.integers(min_value=0, max_value=1_000_000))
def test_property_3_random_no_data_yields_hold(seed):
    # Feature: 03-strategy-engine, Property 3: Empty or insufficient data yields
    # HOLD -- RandomStrategy sin bars y sin quote devuelve HOLD y no lanza error.
    # Validates: Requirements 1.6, 3.6
    strat = RandomStrategy(seed=seed)
    sig = strat.generate([], None)
    assert sig.action is Action.HOLD
    _assert_valid_signal(sig)


@_PBT_SETTINGS
@given(short=st.integers(min_value=2, max_value=8), extra=st.integers(min_value=1, max_value=20))
def test_property_3_predictive_insufficient_bars_yields_hold(short, extra):
    # Feature: 03-strategy-engine, Property 3: Empty or insufficient data yields
    # HOLD -- para PredictiveStrategy, cualquier longitud por debajo de la ventana
    # requerida (max(long_period, rsi_period + 1)) devuelve HOLD sin lanzar.
    # Generamos periodos válidos y una longitud estrictamente menor a la ventana.
    # Validates: Requirements 1.6, 3.6
    long = short + extra  # asegura short < long
    strat = PredictiveStrategy(
        short_period=short,
        long_period=long,
        rsi_period=2,
        rsi_oversold=30,
        rsi_overbought=70,
    )
    required = max(long, 2 + 1)
    # Longitud por debajo de la ventana requerida (incluye 0).
    n_bars = required - 1
    closes = list(range(1, n_bars + 1))
    sig = strat.generate(_bars(closes))
    assert sig.action is Action.HOLD
    _assert_valid_signal(sig)


# ===========================================================================
# Property 4: indicadores puros con propiedades conocidas.
# ===========================================================================


@_PBT_SETTINGS
@given(values=_nonempty_series, period=st.integers(min_value=1, max_value=40))
def test_property_4_sma_is_deterministic(values, period):
    # Feature: 03-strategy-engine, Property 4: Indicators are pure with known
    # properties -- sma es determinista: misma entrada -> misma salida.
    # Validates: Requirements 3.1, 3.7
    series = [Decimal(v) for v in values]
    assert sma(series, period) == sma(series, period)


@_PBT_SETTINGS
@given(
    constant=_prices,
    length=st.integers(min_value=1, max_value=40),
    period=st.integers(min_value=1, max_value=40),
)
def test_property_4_sma_of_constant_equals_constant(constant, length, period):
    # Feature: 03-strategy-engine, Property 4: Indicators are pure with known
    # properties -- la SMA de una serie constante es esa misma constante en cada
    # posición de ventana (cuando hay datos suficientes).
    # Validates: Requirements 3.1, 3.7
    c = Decimal(constant)
    series = [c] * length
    result = sma(series, period)
    if length >= period:
        assert all(v == c for v in result)
    else:
        assert result == []


@_PBT_SETTINGS
@given(values=_nonempty_series, period=st.integers(min_value=1, max_value=40))
def test_property_4_rsi_is_deterministic_and_bounded(values, period):
    # Feature: 03-strategy-engine, Property 4: Indicators are pure with known
    # properties -- rsi es determinista (misma entrada -> misma salida) y todo
    # valor de rsi cae en el rango cerrado [0, 100].
    # Validates: Requirements 3.1, 3.7
    series = [Decimal(v) for v in values]
    first = rsi(series, period)
    second = rsi(series, period)
    assert first == second
    for v in first:
        assert Decimal(0) <= v <= Decimal(100)


# ===========================================================================
# Property 5: un cruce SMA construido fuerza la acción esperada.
# ===========================================================================


@_PBT_SETTINGS_NO_DEADLINE
@given(up=st.booleans(), jump=st.integers(min_value=4, max_value=1000))
def test_property_5_constructed_sma_crossover_forces_action(up, jump):
    # Feature: 03-strategy-engine, Property 5: A constructed SMA crossover forces
    # the expected action -- con periodos pequeños (short=2, long=3) construimos
    # una serie con prefijo plano, un retroceso en la penúltima barra y un salto
    # final fuerte (magnitud controlada por Hypothesis) para forzar un cruce
    # ESTRICTO en la última posición: hacia arriba -> BUY, hacia abajo -> SELL.
    # El último close usa 2*jump para que short_last cruce estrictamente a long_last
    # (evita el caso short_last == long_last que no dispara cruce).
    #
    # Con base=100, jump=j (arriba): closes = [100, 100, 100, 100 - j, 100 + 2j]:
    #   short(2): [100, 100, 100 - j/2, 100 + j/2]
    #             -> prev = 100 - j/2, last = 100 + j/2
    #   long(3):  [100, 100 - j/3, 100 + j/3]
    #             -> prev = 100 - j/3, last = 100 + j/3
    #   short_prev (100 - j/2) <= long_prev (100 - j/3) y
    #   short_last (100 + j/2) >  long_last (100 + j/3) -> BUY.
    # El caso abajo es el espejo exacto -> SELL.
    # Validates: Requirements 3.2, 3.3
    base = 100
    strat = PredictiveStrategy(
        short_period=2, long_period=3, rsi_period=2, rsi_oversold=30, rsi_overbought=70
    )

    if up:
        closes = [base, base, base, base - jump, base + 2 * jump]
        expected = Action.BUY
    else:
        closes = [base, base, base, base + jump, base - 2 * jump]
        expected = Action.SELL

    sig = strat.generate(_bars(closes))
    assert sig.action is expected
    assert "SMA" in sig.reason


# ===========================================================================
# Property 6: nombre no registrado -> UnknownStrategyError, active mode intacto.
# ===========================================================================

_REGISTERED_NAMES = {"random", "predictive"}

# Nombres arbitrarios que NO coinciden con los registrados por build_default_engine.
_unregistered_names = st.text(min_size=1, max_size=20).filter(
    lambda s: s not in _REGISTERED_NAMES
)


@_PBT_SETTINGS
@given(name=_unregistered_names)
def test_property_6_unregistered_name_raises_and_leaves_active_unchanged(name):
    # Feature: 03-strategy-engine, Property 6: Unregistered name raises and leaves
    # the active mode unchanged -- para cualquier nombre no registrado, set_active
    # lanza UnknownStrategyError y get_active_name() devuelve el mismo valor que
    # antes de la llamada.
    # Validates: Requirements 1.4, 4.4
    engine = build_default_engine()
    before = engine.get_active_name()

    with pytest.raises(UnknownStrategyError):
        engine.set_active(name)

    assert engine.get_active_name() == before


@_PBT_SETTINGS
@given(
    default=st.sampled_from(sorted(_REGISTERED_NAMES)),
    name=_unregistered_names,
)
def test_property_6_unregistered_name_on_custom_engine(default, name):
    # Feature: 03-strategy-engine, Property 6: Unregistered name raises and leaves
    # the active mode unchanged -- misma garantía sobre un StrategyEngine con
    # cualquier default registrado: un nombre desconocido no cambia el modo activo.
    # Validates: Requirements 1.4, 4.4
    engine = StrategyEngine(default=default)
    engine.register("random", RandomStrategy(seed=0))
    engine.register(
        "predictive", PredictiveStrategy(short_period=2, long_period=3, rsi_period=2)
    )
    before = engine.get_active_name()

    with pytest.raises(UnknownStrategyError):
        engine.set_active(name)

    assert engine.get_active_name() == before
