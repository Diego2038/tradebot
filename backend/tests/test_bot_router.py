"""Pruebas del router REST de control del bot (Tarea 4, spec 07-bot-api).

Ejercen ``POST /bot/start``, ``POST /bot/stop`` y ``GET /bot/status`` con el
``TestClient`` de FastAPI. El SDK de Alpaca se stubbea vía ``sys.modules`` ANTES
de importar ``app.main`` (igual que en ``test_credentials_router.py`` /
``test_market_data_router.py``: solo ``alpaca.trading.client``) para no depender
del paquete real ni realizar llamadas de red. La BD es una SQLite en memoria
(``StaticPool``) que sobreescribe la dependency ``get_db``.

Para controlar el comportamiento del bot sin depender del streamer real, se
sobreescribe ``app.state.bot_orchestrator`` con un doble que implementa
``async start(mode)`` / ``async stop()`` / ``status()`` devolviendo un
:class:`BotStatus`. El ``TestClient`` corre el event loop, así que los métodos
async del doble funcionan con normalidad.

Se verifica que los ``error_code`` sean distinguibles por causa (409
``no_credentials`` R2.3, 400 ``invalid_mode`` R2.4) y que el camino feliz
devuelva ``state``/``mode``/``symbol`` (R2.2, R2.5, R2.6).
"""
from __future__ import annotations

import os
import sys
import types

import pytest
from cryptography.fernet import Fernet

# El engine de ``app.db.session`` se crea a nivel de módulo a partir de
# ``DATABASE_URL``. La imagen de test slim no trae el driver de PostgreSQL, así
# que forzamos SQLite ANTES de que se importe la cadena de servicios (app.main).
os.environ.setdefault("DATABASE_URL", "sqlite://")


# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar app.main. Igual que en los otros
# tests de routers: registramos SOLO ``alpaca.trading.client`` (que ``factory``
# importa a nivel de módulo). El orchestrator se sustituye por un doble, así que
# ni el streamer/executor ni la red se llegan a tocar.
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
from app.services.bot.state import BotState, BotStatus  # noqa: E402
from app.services.strategies.errors import UnknownStrategyError  # noqa: E402

import app.db.models  # noqa: E402,F401 - registra el modelo en Base.metadata
import app.main as main_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Doble del BotOrchestrator: implementa la misma interfaz (async start/stop,
# status síncrono) para no depender del streamer/executor reales. Cada test
# configura su comportamiento (start OK, start que lanza un error, etc.).
# ---------------------------------------------------------------------------
class FakeOrchestrator:
    def __init__(
        self,
        *,
        symbol: str = "BTC/USD",
        start_error: Exception | None = None,
    ) -> None:
        self._symbol = symbol
        self._state = BotState.STOPPED
        self._mode = "random"
        self._start_error = start_error
        self.start_calls: list[str] = []
        self.stop_calls = 0

    async def start(self, mode: str) -> BotStatus:
        self.start_calls.append(mode)
        if self._start_error is not None:
            raise self._start_error
        self._mode = mode
        self._state = BotState.RUNNING
        return self.status()

    async def stop(self) -> BotStatus:
        self.stop_calls += 1
        self._state = BotState.STOPPED
        return self.status()

    def status(self) -> BotStatus:
        return BotStatus(state=self._state, mode=self._mode, symbol=self._symbol)


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
    """TestClient con una BD SQLite en memoria sobreescribiendo get_db.

    Guarda y restaura el ``app.state.bot_orchestrator`` original para que cada
    test pueda inyectar su propio doble sin filtrarse a otras pruebas.
    """
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
    original_orchestrator = main_mod.app.state.bot_orchestrator
    with TestClient(main_mod.app) as test_client:
        yield test_client
    main_mod.app.state.bot_orchestrator = original_orchestrator
    main_mod.app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _set_orchestrator(fake: FakeOrchestrator) -> None:
    main_mod.app.state.bot_orchestrator = fake


def test_start_without_credentials_returns_409(client):
    """(a) POST /bot/start sin credenciales -> 409 error_code 'no_credentials' (R2.3)."""
    fake = FakeOrchestrator(
        start_error=CredentialsRequiredError("no credentials configured")
    )
    _set_orchestrator(fake)

    resp = client.post("/bot/start", json={"mode": "random"})

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "no_credentials"
    # El pipeline no arrancó: sigue stopped (el doble no cambia estado en error).
    assert fake.status().state is BotState.STOPPED


def test_start_invalid_mode_literal_returns_422(client):
    """(b) POST /bot/start con modo fuera del Literal -> 422 (validación FastAPI) (R2.4)."""
    fake = FakeOrchestrator()
    _set_orchestrator(fake)

    resp = client.post("/bot/start", json={"mode": "chaos"})

    assert resp.status_code == 422
    # El orchestrator ni siquiera se invoca: la validación ocurre en el borde.
    assert fake.start_calls == []


def test_start_unknown_strategy_returns_400(client):
    """(b) POST /bot/start cuyo orchestrator lanza UnknownStrategyError -> 400 'invalid_mode' (R2.4)."""
    fake = FakeOrchestrator(start_error=UnknownStrategyError("unknown strategy 'x'"))
    _set_orchestrator(fake)

    resp = client.post("/bot/start", json={"mode": "predictive"})

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_mode"


def test_start_valid_returns_200_running(client):
    """(c) POST /bot/start válido -> 200 con state 'running', mode y symbol (R2.2)."""
    fake = FakeOrchestrator(symbol="BTC/USD")
    _set_orchestrator(fake)

    resp = client.post("/bot/start", json={"mode": "predictive"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "running"
    assert body["mode"] == "predictive"
    assert body["symbol"] == "BTC/USD"
    assert fake.start_calls == ["predictive"]


def test_stop_returns_200_stopped(client):
    """(d) POST /bot/stop -> 200 state 'stopped' (R2.5)."""
    fake = FakeOrchestrator()
    _set_orchestrator(fake)

    resp = client.post("/bot/stop")

    assert resp.status_code == 200
    assert resp.json()["state"] == "stopped"
    assert fake.stop_calls == 1


def test_status_returns_200_state_mode_symbol(client):
    """(e) GET /bot/status -> 200 con state/mode/symbol (R2.6)."""
    fake = FakeOrchestrator(symbol="BTC/USD")
    _set_orchestrator(fake)

    resp = client.get("/bot/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "stopped"
    assert body["mode"] == "random"
    assert body["symbol"] == "BTC/USD"


def test_health_still_reports_paper_mode(client):
    """(f) GET /health sigue respondiendo con mode 'paper' (R2.7, no regresión)."""
    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["mode"] == "paper"
