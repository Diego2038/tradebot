"""Pruebas basadas en propiedades (Hypothesis) del Risk Manager (Tarea 5).

Spec ``06-risk-manager``. Ejercitan la lógica pura/determinista del gate de riesgo
(``RiskManager.evaluate`` y los helpers de reglas) sobre cantidades, límites,
porcentajes, equity y fechas UTC generados por Hypothesis. Esta spec NO toca Alpaca
ni red: importa SOLO ``app.services.execution.risk`` para los tipos del port (puro)
y ``app.services.risk.*`` (dominio). El ``EquityProvider`` se sustituye por un stub
que devuelve ``Decimal | None``.

Cada test lleva un comentario "Feature: 06-risk-manager, Property N: ...".
Todas las propiedades corren con >= 100 iteraciones (@settings(max_examples=100)).

Cobertura (6 propiedades del design):
- P1: qty <= 0 -> approved=False con REASON_INVALID_QTY, sin comparar contra el máximo.
- P2: frontera de lote (qty > effective_allowed_max -> bloqueo; dentro -> no bloquea).
- P3: orden dentro de todos los límites -> approved=True.
- P4: frontera de pérdida diaria con reset por día UTC.
- P5: evaluate determinista y total (no lanza; dos llamadas iguales; no muta estado).
- P6: RiskManager satisface el RiskPort de spec 04 (isinstance runtime_checkable).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.execution.risk import ProposedOrder, RiskDecision, RiskPort
from app.services.risk import RiskManager
from app.services.risk.rules import (
    REASON_DAILY_LOSS,
    REASON_INVALID_QTY,
    REASON_MAX_LOT,
    effective_allowed_max,
)


# ---------------------------------------------------------------------------
# Ajustes y helpers comunes
# ---------------------------------------------------------------------------

_PBT_SETTINGS = settings(max_examples=100, deadline=None)


class _StubEquityProvider:
    """EquityProvider mínimo para tests: devuelve un ``Decimal | None`` fijo."""

    def __init__(self, equity: Decimal | None) -> None:
        self._equity = equity

    def get_equity(self) -> Decimal | None:
        return self._equity


# Decimales positivos "amigables" (enteros/decimales finitos, sin NaN/inf) para
# límites y cantidades. Usamos st.integers().map(Decimal) y decimales acotados
# para evitar problemas de precisión y mantener rapidez y determinismo.
_POS_DECIMALS = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

# Cantidades <= 0 (cero y negativas).
_NON_POSITIVE_DECIMALS = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("0"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

# Porcentaje en (0, 100].
_PCT_DECIMALS = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)


def _order(qty: Decimal) -> ProposedOrder:
    return ProposedOrder(symbol="BTC/USD", side="buy", qty=qty)


# ---------------------------------------------------------------------------
# Property 1: Invalid quantity is rejected as invalid
# ---------------------------------------------------------------------------
# Feature: 06-risk-manager, Property 1: For any RiskManager configuration and any
# ProposedOrder whose qty <= 0, evaluate returns approved=False with the
# invalid-quantity reason, and does not compare qty against Effective_Allowed_Max.
# Validates: Requirements 2.6
@_PBT_SETTINGS
@given(
    qty=_NON_POSITIVE_DECIMALS,
    daily_loss_limit=_POS_DECIMALS,
    max_qty=_POS_DECIMALS,
)
def test_property_1_invalid_quantity_rejected(
    qty: Decimal, daily_loss_limit: Decimal, max_qty: Decimal
) -> None:
    rm = RiskManager(daily_loss_limit=daily_loss_limit, max_qty=max_qty)
    decision = rm.evaluate(_order(qty))

    assert decision.approved is False
    assert decision.reason == REASON_INVALID_QTY


# ---------------------------------------------------------------------------
# Property 2: Lot-size boundary
# ---------------------------------------------------------------------------
# Feature: 06-risk-manager, Property 2: For any valid max_qty, optional max_equity_pct
# in (0, 100], positive equity and positive qty: when qty > Effective_Allowed_Max the
# evaluate returns approved=False with the max-lot reason; when 0 < qty <=
# Effective_Allowed_Max the lot rule does not block (and with no daily loss and equity
# available -> approved=True).
# Validates: Requirements 2.2, 2.4, 2.5
@_PBT_SETTINGS
@given(
    qty=_POS_DECIMALS,
    max_qty=_POS_DECIMALS,
    use_pct=st.booleans(),
    max_equity_pct=_PCT_DECIMALS,
    equity=_POS_DECIMALS,
    daily_loss_limit=_POS_DECIMALS,
)
def test_property_2_lot_size_boundary(
    qty: Decimal,
    max_qty: Decimal,
    use_pct: bool,
    max_equity_pct: Decimal,
    equity: Decimal,
    daily_loss_limit: Decimal,
) -> None:
    pct = max_equity_pct if use_pct else None
    provider = _StubEquityProvider(equity) if use_pct else None
    rm = RiskManager(
        daily_loss_limit=daily_loss_limit,
        max_qty=max_qty,
        max_equity_pct=pct,
        equity_provider=provider,
    )

    allowed_max = effective_allowed_max(max_qty, pct, equity if use_pct else None)
    # Con equity positivo y pct en rango, allowed_max nunca es None.
    assert allowed_max is not None

    decision = rm.evaluate(_order(qty))

    if qty > allowed_max:
        assert decision.approved is False
        assert decision.reason == REASON_MAX_LOT
    else:
        # La regla de lote no bloquea; sin pérdida diaria acumulada y equity
        # disponible, la orden queda aprobada.
        assert decision.approved is True
        assert decision.reason == ""


# ---------------------------------------------------------------------------
# Property 3: An order within all limits is approved
# ---------------------------------------------------------------------------
# Feature: 06-risk-manager, Property 3: For any RiskManager with a positive
# qty <= Effective_Allowed_Max, available positive equity when max_equity_pct is set,
# and a current UTC-day accumulated loss below Daily_Loss_Limit, evaluate returns
# approved=True.
# Validates: Requirements 1.5, 2.4, 3.3
@_PBT_SETTINGS
@given(
    max_qty=_POS_DECIMALS,
    use_pct=st.booleans(),
    max_equity_pct=_PCT_DECIMALS,
    equity=_POS_DECIMALS,
    daily_loss_limit=_POS_DECIMALS,
    frac=st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("1"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
    profit=_POS_DECIMALS,
)
def test_property_3_within_all_limits_approved(
    max_qty: Decimal,
    use_pct: bool,
    max_equity_pct: Decimal,
    equity: Decimal,
    daily_loss_limit: Decimal,
    frac: Decimal,
    profit: Decimal,
) -> None:
    pct = max_equity_pct if use_pct else None
    provider = _StubEquityProvider(equity) if use_pct else None
    rm = RiskManager(
        daily_loss_limit=daily_loss_limit,
        max_qty=max_qty,
        max_equity_pct=pct,
        equity_provider=provider,
    )

    allowed_max = effective_allowed_max(max_qty, pct, equity if use_pct else None)
    assert allowed_max is not None
    # qty positiva y dentro del máximo permitido (fracción de allowed_max).
    qty = allowed_max * frac
    if qty <= 0:
        qty = allowed_max  # borde inferior de la fracción: usa el máximo permitido.

    # Sin pérdidas registradas (o registrando ganancias) la pérdida acumulada es 0,
    # por debajo del límite positivo.
    rm.record_realized_pnl(profit)  # ganancia (positivo) -> pérdida acumulada = 0

    decision = rm.evaluate(_order(qty))

    assert decision.approved is True
    assert decision.reason == ""


# ---------------------------------------------------------------------------
# Property 4: Daily-loss boundary with UTC-day reset
# ---------------------------------------------------------------------------
# Feature: 06-risk-manager, Property 4: For any positive Daily_Loss_Limit and any
# sequence of realized-P&L reports, an opening order is blocked with the daily-loss
# reason exactly when the current UTC day's accumulated loss >= Daily_Loss_Limit and
# not by this rule when < limit; and P&L reported on one UTC day starts from zero when
# evaluated/recorded on a later UTC day (reset).
# Validates: Requirements 1.4, 1.5, 1.6
@_PBT_SETTINGS
@given(
    daily_loss_limit=_POS_DECIMALS,
    loss=_POS_DECIMALS,
    max_qty=_POS_DECIMALS,
)
def test_property_4_daily_loss_boundary_and_utc_reset(
    daily_loss_limit: Decimal, loss: Decimal, max_qty: Decimal
) -> None:
    # qty válida y dentro del máximo, para aislar la regla de pérdida diaria.
    qty = max_qty

    # --- Frontera de pérdida diaria en el día actual ---
    rm = RiskManager(daily_loss_limit=daily_loss_limit, max_qty=max_qty)
    # Registrar una pérdida (amount negativo) hoy.
    rm.record_realized_pnl(-loss)
    decision = rm.evaluate(_order(qty))

    if loss >= daily_loss_limit:
        assert decision.approved is False
        assert decision.reason == REASON_DAILY_LOSS
    else:
        # Por debajo del límite, la regla de pérdida diaria no bloquea; la orden
        # (qty válida y dentro del lote) queda aprobada.
        assert decision.approved is True
        assert decision.reason == ""

    # --- Reset por cambio de día UTC ---
    # Pérdida grande (>= límite) reportada en un día UTC (día 1).
    rm2 = RiskManager(daily_loss_limit=daily_loss_limit, max_qty=max_qty)
    day1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    day2 = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
    rm2.record_realized_pnl(-(daily_loss_limit + loss), at=day1)
    # Un record posterior en el día 2 resetea la pérdida acumulada antes de aplicar.
    # Registramos una ganancia trivial en día 2 -> pérdida acumulada vuelve a 0.
    rm2.record_realized_pnl(Decimal("0"), at=day2)

    # La pérdida acumulada del día 2 es 0 (reset), por debajo del límite positivo.
    assert rm2._accumulated_loss == Decimal(0)


# ---------------------------------------------------------------------------
# Property 5: evaluate is deterministic and never raises on a violation
# ---------------------------------------------------------------------------
# Feature: 06-risk-manager, Property 5: For any RiskManager state and any
# ProposedOrder (including invalid quantities), evaluate never raises and returns a
# RiskDecision, and two consecutive calls with the same state and same order return
# equal RiskDecisions (state is not mutated by evaluate).
# Validates: Requirements 3.5, 3.6
@_PBT_SETTINGS
@given(
    daily_loss_limit=_POS_DECIMALS,
    max_qty=_POS_DECIMALS,
    use_pct=st.booleans(),
    max_equity_pct=_PCT_DECIMALS,
    equity=st.one_of(st.none(), _POS_DECIMALS, _NON_POSITIVE_DECIMALS),
    qty=st.one_of(_POS_DECIMALS, _NON_POSITIVE_DECIMALS),
    pnls=st.lists(
        st.decimals(
            min_value=Decimal("-100000"),
            max_value=Decimal("100000"),
            allow_nan=False,
            allow_infinity=False,
            places=2,
        ),
        max_size=8,
    ),
)
def test_property_5_deterministic_and_total(
    daily_loss_limit: Decimal,
    max_qty: Decimal,
    use_pct: bool,
    max_equity_pct: Decimal,
    equity: Decimal | None,
    qty: Decimal,
    pnls: list[Decimal],
) -> None:
    pct = max_equity_pct if use_pct else None
    provider = _StubEquityProvider(equity) if use_pct else None
    rm = RiskManager(
        daily_loss_limit=daily_loss_limit,
        max_qty=max_qty,
        max_equity_pct=pct,
        equity_provider=provider,
    )

    # Estado previo arbitrario.
    for amount in pnls:
        rm.record_realized_pnl(amount)

    state_before = rm._accumulated_loss
    day_before = rm._current_utc_day

    order = _order(qty)
    # No lanza y devuelve RiskDecision.
    decision1 = rm.evaluate(order)
    decision2 = rm.evaluate(order)

    assert isinstance(decision1, RiskDecision)
    assert isinstance(decision2, RiskDecision)
    # Dos llamadas consecutivas con el mismo estado/orden -> decisiones iguales.
    assert decision1 == decision2
    # evaluate no muta el estado de pérdida acumulada del día.
    assert rm._accumulated_loss == state_before
    assert rm._current_utc_day == day_before


# ---------------------------------------------------------------------------
# Property 6: RiskManager satisfies the spec-04 RiskPort
# ---------------------------------------------------------------------------
# Feature: 06-risk-manager, Property 6: For any validly constructed RiskManager,
# isinstance(instance, RiskPort) is True against the runtime_checkable RiskPort
# Protocol imported from app.services.execution.risk.
# Validates: Requirements 3.1
@_PBT_SETTINGS
@given(
    daily_loss_limit=_POS_DECIMALS,
    max_qty=_POS_DECIMALS,
    use_pct=st.booleans(),
    max_equity_pct=_PCT_DECIMALS,
)
def test_property_6_satisfies_risk_port(
    daily_loss_limit: Decimal,
    max_qty: Decimal,
    use_pct: bool,
    max_equity_pct: Decimal,
) -> None:
    rm = RiskManager(
        daily_loss_limit=daily_loss_limit,
        max_qty=max_qty,
        max_equity_pct=max_equity_pct if use_pct else None,
    )
    assert isinstance(rm, RiskPort)
