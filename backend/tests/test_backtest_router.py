"""Pruebas del router REST del backtest engine (spec 05-backtest-engine).

Ejercen ``POST /backtest`` con el ``TestClient`` de FastAPI. El SDK de Alpaca se
stubbea vía ``sys.modules`` ANTES de importar ``app.main`` (igual que en
``test_market_data_router.py`` / ``test_bot_router.py``: solo
``alpaca.trading.client``) para no depender del paquete real ni realizar llamadas
de red. La BD es una SQLite en memoria (``StaticPool``) que sobreescribe la
dependency ``get_db``. En cada caso se mockea ``HistoricalDataService.get_bars``
para no tocar la red y controlar el comportamiento.

Se verifica que:
- El camino feliz serializa el ``BacktestResult`` como ``BacktestResultOut`` con
  ``bars_evaluated == len(bars)`` y reproducibilidad con ``seed`` fija.
- Los ``error_code`` sean distinguibles por causa: modo inválido -> 422 (rechazado
  por el Literal), ``invalid_timeframe`` (400), ``invalid_range`` (400, IMPORTANTE:
  el data-feed valida el rango ANTES que el engine, así que ``start > end`` produce
  ``InvalidRangeError`` -> ``invalid_range``, NO ``invalid_date_range``) y
  ``no_credentials`` (409).
"""
from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest
from cryptography.fernet import Fernet

# El engine de ``app.db.session`` se crea a nivel de módulo a partir de
# ``DATABASE_URL``. La imagen de test slim no trae el driver de PostgreSQL, así
# que forzamos SQLite ANTES de que se importe la cadena de servicios (app.main).
os.environ.setdefault("DATABASE_URL", "sqlite://")


# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar app.main. Igual que en los otros
# tests de routers: registramos SOLO ``alpaca.trading.client`` (que ``factory``
# importa a nivel de módulo). ``get_bars`` se mockea, así que ni el cliente de
# datos ni la red se llegan a tocar.
# ---------------------------------------------------------------------------


def _install_alpaca_stub() -> None:
    if "alpaca.trading.client" in sys.modules:
        return

    trading_client_mod = types.ModuleType("alpaca.trading.client")

    class TradingClient:  # firma mínima compatible
        def __init__(self, api_key=None, secret_key=None, paper=True, **kwargs):
            self._api_key = api_key
            self._secret_key = secret_key
            self._paper = paper

        def get_account(self):  # pragma: no cover - no se usa aquí
            raise NotImplementedError

    trading_client_mod.TradingClient = TradingClient
    sys.modules["alpaca.trading.client"] = trading_client_mod


_install_alpaca_stub()

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.services.alpaca_client.errors import CredentialsRequiredError  # noqa: E402
from app.services.data_feed.errors import InvalidTimeframeError  # noqa: E402
from app.services.data_feed.historical import HistoricalDataService  # noqa: E402
from app.services.data_feed.models import Bar  # noqa: E402

import app.db.models  # noqa: E402,F401 - registra el modelo en Base.metadata
import app.main as main_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    """Clave Fernet válida y config paper; resetea el cache de settings."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("ALPACA_PAPER_ONLY", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    """TestClient con una BD SQLite en memoria sobreescribiendo get_db."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    main_mod.app.dependency_overrides[get_db] = _override_get_db
    with TestClient(main_mod.app) as test_client:
        yield test_client
    main_mod.app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


# Rango válido reutilizable (ISO 8601) para el body.
_VALID_START = "2024-01-01T00:00:00+00:00"
_VALID_END = "2024-01-02T00:00:00+00:00"


def _body(**overrides) -> dict:
    body = {
        "mode": "random",
        "start": _VALID_START,
        "end": _VALID_END,
    }
    body.update(overrides)
    return body


def _sample_bars() -> list[Bar]:
    """Pequeña serie ascendente de Bars con movimiento de precio conocido."""
    base = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    closes = ["42000", "42100", "42050", "42300", "42250", "42400"]
    bars: list[Bar] = []
    for i, close in enumerate(closes):
        c = Decimal(close)
        bars.append(
            Bar(
                timestamp=base.replace(minute=i),
                open=c,
                high=c + Decimal("50"),
                low=c - Decimal("50"),
                close=c,
                volume=Decimal("1.0"),
            )
        )
    return bars


def test_backtest_happy_path_returns_200_with_result(client):
    """(a) camino feliz: get_bars devuelve una serie -> 200 con BacktestResultOut."""
    bars = _sample_bars()
    with mock.patch.object(HistoricalDataService, "get_bars", return_value=bars):
        resp = client.post("/backtest", json=_body(mode="random", seed=42))

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "total_return",
        "trade_count",
        "win_rate",
        "max_drawdown",
        "trades",
        "bars_evaluated",
    }
    assert isinstance(body["trade_count"], int)
    assert body["bars_evaluated"] == len(bars)
    assert isinstance(body["trades"], list)
    # Las métricas están presentes y son numéricas/coherentes.
    assert Decimal(body["total_return"]) >= Decimal("-1")
    assert Decimal("0") <= Decimal(body["win_rate"]) <= Decimal("1")
    assert Decimal("0") <= Decimal(body["max_drawdown"]) <= Decimal("1")


def test_backtest_reproducible_with_fixed_seed(client):
    """(a') misma seed -> resultado idéntico (reproducibilidad, R4.2)."""
    bars = _sample_bars()
    with mock.patch.object(HistoricalDataService, "get_bars", return_value=bars):
        first = client.post("/backtest", json=_body(mode="random", seed=7))
        second = client.post("/backtest", json=_body(mode="random", seed=7))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_backtest_invalid_mode_returns_422(client):
    """(b) modo fuera del Literal -> 422 (rechazado en el borde antes del handler)."""
    # get_bars ni siquiera debe llamarse: la validación ocurre antes.
    with mock.patch.object(HistoricalDataService, "get_bars") as get_bars:
        resp = client.post("/backtest", json=_body(mode="foo"))

    assert resp.status_code == 422
    get_bars.assert_not_called()


def test_backtest_invalid_timeframe_returns_400(client):
    """(c) timeframe inválido -> 400 error_code 'invalid_timeframe' (propagado del servicio)."""
    with mock.patch.object(
        HistoricalDataService,
        "get_bars",
        side_effect=InvalidTimeframeError("unsupported timeframe"),
    ):
        resp = client.post("/backtest", json=_body(timeframe="7Min"))

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_timeframe"


def test_backtest_start_after_end_returns_400_invalid_range(client):
    """(d) start > end -> 400 'invalid_range'.

    IMPORTANTE: el HistoricalDataService valida el rango ANTES que el engine, así
    que un rango invertido produce ``InvalidRangeError`` (data-feed) -> 400
    ``invalid_range``, NO el ``invalid_date_range`` del engine.
    """
    from app.services.data_feed.errors import InvalidRangeError

    with mock.patch.object(
        HistoricalDataService,
        "get_bars",
        side_effect=InvalidRangeError("start must not be after end"),
    ):
        resp = client.post(
            "/backtest", json=_body(start=_VALID_END, end=_VALID_START)
        )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_range"


def test_backtest_without_credentials_returns_409(client):
    """(e) sin credenciales -> 409 error_code 'no_credentials'."""
    with mock.patch.object(
        HistoricalDataService,
        "get_bars",
        side_effect=CredentialsRequiredError("no credentials configured"),
    ):
        resp = client.post("/backtest", json=_body())

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "no_credentials"
