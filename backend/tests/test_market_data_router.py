"""Pruebas del router REST de datos históricos (Tarea 6, spec 02-data-feed).

Ejercen ``GET /market-data/bars`` con el ``TestClient`` de FastAPI. El SDK de
Alpaca se stubbea vía ``sys.modules`` ANTES de importar ``app.main`` (igual que
en ``test_credentials_router.py``: solo ``alpaca.trading.client``) para no
depender del paquete real ni realizar llamadas de red. La BD es una SQLite en
memoria (``StaticPool``) que sobreescribe la dependency ``get_db``. En cada caso
se mockea ``HistoricalDataService.get_bars`` para no tocar la red y controlar el
comportamiento (timeframe/rango inválido, camino feliz, sin credenciales).

Se verifica que los ``error_code`` sean distinguibles por causa (R1.4, R1.5,
R1.8) y que el camino feliz serialice cada ``Bar`` como ``BarOut``.
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
# Stub del SDK alpaca-py ANTES de importar app.main. Igual que en
# ``test_credentials_router.py``: registramos SOLO ``alpaca.trading.client``
# (que ``factory.py`` importa a nivel de módulo), sin tocar otros submódulos.
# Aquí mockeamos ``HistoricalDataService.get_bars`` por completo, así que ni el
# cliente de datos ni la red se llegan a tocar.
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
from app.services.data_feed.errors import (  # noqa: E402
    InvalidRangeError,
    InvalidTimeframeError,
)
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


# Rango válido reutilizable (ISO 8601) para los query params.
_VALID_START = "2024-01-01T00:00:00+00:00"
_VALID_END = "2024-01-02T00:00:00+00:00"


def _params(**overrides) -> dict[str, str]:
    params = {
        "timeframe": "1Min",
        "start": _VALID_START,
        "end": _VALID_END,
    }
    params.update(overrides)
    return params


def test_bars_invalid_timeframe_returns_400(client):
    """(a) timeframe inválido -> 400 error_code 'invalid_timeframe' (R1.4)."""
    with mock.patch.object(
        HistoricalDataService,
        "get_bars",
        side_effect=InvalidTimeframeError("unsupported timeframe"),
    ):
        resp = client.get("/market-data/bars", params=_params(timeframe="7Min"))

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_timeframe"


def test_bars_invalid_range_returns_400(client):
    """(b) rango inválido (start > end) -> 400 error_code 'invalid_range' (R1.5)."""
    with mock.patch.object(
        HistoricalDataService,
        "get_bars",
        side_effect=InvalidRangeError("start must not be after end"),
    ):
        resp = client.get(
            "/market-data/bars",
            params=_params(start=_VALID_END, end=_VALID_START),
        )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_range"


def test_bars_happy_path_returns_200_with_bars(client):
    """(c) camino feliz: get_bars devuelve 2 Bars -> 200 y JSON con 2 BarOut."""
    bars = [
        Bar(
            timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            open=Decimal("42000.00"),
            high=Decimal("42100.50"),
            low=Decimal("41950.25"),
            close=Decimal("42050.75"),
            volume=Decimal("1.5"),
        ),
        Bar(
            timestamp=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
            open=Decimal("42050.75"),
            high=Decimal("42200.00"),
            low=Decimal("42000.00"),
            close=Decimal("42180.10"),
            volume=Decimal("2.25"),
        ),
    ]
    with mock.patch.object(HistoricalDataService, "get_bars", return_value=bars):
        resp = client.get("/market-data/bars", params=_params())

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    # Cada elemento expone exactamente los campos de BarOut (R3.1).
    for item in body:
        assert set(item.keys()) == {
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }
    assert Decimal(body[0]["close"]) == Decimal("42050.75")
    assert Decimal(body[1]["open"]) == Decimal("42050.75")


def test_bars_empty_list_returns_200_empty(client):
    """Rango válido sin datos -> 200 y lista vacía (R1.3)."""
    with mock.patch.object(HistoricalDataService, "get_bars", return_value=[]):
        resp = client.get("/market-data/bars", params=_params())

    assert resp.status_code == 200
    assert resp.json() == []


def test_bars_without_credentials_returns_409(client):
    """(d) sin credenciales -> 409 error_code 'no_credentials' (R1.8)."""
    with mock.patch.object(
        HistoricalDataService,
        "get_bars",
        side_effect=CredentialsRequiredError("no credentials configured"),
    ):
        resp = client.get("/market-data/bars", params=_params())

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "no_credentials"
