"""Pruebas de humo del router REST de la capa Alpaca (Tarea 8).

Ejercen ``POST/GET/DELETE /credentials`` y ``GET /account`` con el ``TestClient``
de FastAPI. El SDK de Alpaca se stubbea vía ``sys.modules`` ANTES de importar
``app.main`` (igual que en test_factory.py / test_credential_service.py) para no
depender del paquete real ni realizar llamadas de red. La BD es una SQLite en
memoria que sobreescribe la dependency ``get_db``; el ``factory.validate`` (que
sería la única llamada de red) se mockea con ``patch`` en cada caso.

Se verifica que los códigos HTTP y los ``error_code`` sean distinguibles y que
ninguna respuesta contenga el secreto en claro.
"""
from __future__ import annotations

import os
import sys
import types
from unittest import mock

import pytest
from cryptography.fernet import Fernet

# El engine de ``app.db.session`` se crea a nivel de módulo a partir de
# ``DATABASE_URL``. La imagen de test slim no trae el driver de PostgreSQL, así
# que forzamos SQLite ANTES de que se importe la cadena de servicios (app.main).
os.environ.setdefault("DATABASE_URL", "sqlite://")


# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar app.main (que importa la cadena de
# servicios y, transitivamente, ``alpaca.trading.client``). No está instalado en
# la imagen de test slim.
# ---------------------------------------------------------------------------


def _install_alpaca_stub() -> None:
    """Registra SOLO el submódulo que ``factory.py`` importa a nivel de módulo.

    Igual que en ``test_credential_service.py``: deliberadamente NO registramos
    el paquete ``alpaca`` de primer nivel ni ``alpaca.common.exceptions`` para no
    interferir con otras pruebas (p. ej. ``test_factory.py``) que instalan su
    propio stub completo, incluida su ``APIError``. Estas pruebas mockean
    ``factory.validate`` por completo, así que ``APIError`` nunca se toca aquí.
    """
    if "alpaca.trading.client" in sys.modules:
        return

    trading_client_mod = types.ModuleType("alpaca.trading.client")

    class TradingClient:  # firma mínima compatible
        def __init__(self, api_key=None, secret_key=None, paper=True, **kwargs):
            self._api_key = api_key
            self._secret_key = secret_key
            self._paper = paper

        def get_account(self):  # pragma: no cover - se mockea en cada test
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
from app.services.alpaca_client import factory as factory_mod  # noqa: E402
from app.services.alpaca_client.errors import InvalidCredentialsError  # noqa: E402

import app.db.models  # noqa: E402,F401 - registra el modelo en Base.metadata
import app.main as main_mod  # noqa: E402


SECRET_VALUE = "super-secret-value-should-never-leak"


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
    # ``StaticPool`` + una única conexión compartida hace que la BD SQLite en
    # memoria persista entre sesiones (de lo contrario cada conexión abre una BD
    # vacía y la tabla creada no se ve).
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


def test_get_credentials_without_credentials_returns_exists_false(client):
    """GET /credentials sin credenciales -> 200 exists=False (R6.2)."""
    resp = client.get("/credentials")
    assert resp.status_code == 200
    body = resp.json()
    assert body["exists"] is False
    assert body["key_id_last4"] is None


def test_get_account_without_credentials_returns_409(client):
    """GET /account sin credenciales -> 409 error_code 'no_credentials' (R3.2)."""
    resp = client.get("/account")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "no_credentials"


def test_post_credentials_valid_returns_201_without_secret(client):
    """POST /credentials válido (validate OK) -> 201 y sin secreto en la respuesta."""
    # Mockeamos validate para no llamar a la red; la validación pasa OK.
    with mock.patch.object(factory_mod.AlpacaClientFactory, "validate", return_value=None):
        resp = client.post(
            "/credentials",
            json={"api_key": "PKTEST-api-key-wxyz", "secret": SECRET_VALUE},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["exists"] is True
    assert body["validation_status"] == "valid"
    assert body["key_id_last4"] == "wxyz"
    # El secreto NUNCA aparece en la respuesta (R1.3).
    assert SECRET_VALUE not in resp.text
    assert "secret" not in body


def test_post_credentials_invalid_returns_401(client):
    """validate lanza InvalidCredentialsError -> 401 error_code 'invalid_credentials'."""
    with mock.patch.object(
        factory_mod.AlpacaClientFactory,
        "validate",
        side_effect=InvalidCredentialsError("invalid Alpaca credentials"),
    ):
        resp = client.post(
            "/credentials",
            json={"api_key": "PKTEST-api-key-wxyz", "secret": SECRET_VALUE},
        )

    assert resp.status_code == 401
    assert resp.json()["error_code"] == "invalid_credentials"
    # Ni siquiera en el camino de error se filtra el secreto (R1.4).
    assert SECRET_VALUE not in resp.text
