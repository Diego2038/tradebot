"""Pruebas mínimas del diseño no cubiertas inline (Sub-tarea 9.2).

Complementan (sin solapar) las suites existentes:
- ``test_credential_service.py`` ya cubre rechazo de campos en blanco, 401 no
  persiste, éxito persiste con last4 e ``inspect`` sin credenciales (R6.2).
- ``test_credentials_router.py`` ya cubre GET /credentials sin credenciales,
  GET /account 409, POST 201 y POST 401.

Aquí se añade SOLO lo que falta del apartado "Unit / example tests" y de la
integración/smoke del diseño:
- Orden explícito validate-antes-de-persistir (R2.1) con un ``parent mock``.
- Clave de cifrado ausente/inválida -> ``EncryptionError`` y store intacta (R1.6).
- Ningún secreto en ``str(exc)`` ni en logs a lo largo de los caminos de error
  (InvalidCredentialsError, TransientAlpacaError, EncryptionError) (R1.4).
- Smoke del router: DELETE /credentials -> 200 ``DeletionResult`` y el mapeo de
  TransientAlpacaError -> 502 ``transient_error`` y EncryptionError -> 503
  ``encryption_unavailable`` a nivel de endpoint.
"""
from __future__ import annotations

import logging
import os
import sys
import types
from unittest import mock
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

# El engine de ``app.db.session`` se crea a nivel de módulo a partir de
# ``DATABASE_URL``. La imagen de test slim no trae el driver de PostgreSQL, así
# que forzamos SQLite ANTES de importar la cadena de servicios (app.main).
os.environ.setdefault("DATABASE_URL", "sqlite://")


def _install_alpaca_stub() -> None:
    """Registra SOLO el submódulo que ``factory.py`` importa a nivel de módulo.

    Igual patrón que las otras suites: no registramos el paquete ``alpaca`` de
    primer nivel para no interferir con ``test_factory.py`` (que instala su stub
    completo con su propia ``APIError``). Aquí el factory se mockea o su
    ``validate`` se sustituye, así que Alpaca nunca se toca de verdad.
    """
    if "alpaca.trading.client" in sys.modules:
        return

    trading_client_mod = types.ModuleType("alpaca.trading.client")

    class TradingClient:  # firma mínima compatible
        def __init__(self, api_key=None, secret_key=None, paper=True, **kwargs):
            self._api_key = api_key
            self._secret_key = secret_key
            self._paper = paper

        def get_account(self):  # pragma: no cover - se mockea/patchéa
            raise NotImplementedError

    trading_client_mod.TradingClient = TradingClient
    sys.modules["alpaca.trading.client"] = trading_client_mod


_install_alpaca_stub()

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import EncryptionError  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.services.alpaca_client import factory as factory_mod  # noqa: E402
from app.services.alpaca_client.credential_service import CredentialService  # noqa: E402
from app.services.alpaca_client.errors import (  # noqa: E402
    InvalidCredentialsError,
    TransientAlpacaError,
)

import app.db.models  # noqa: E402,F401 - registra el modelo en Base.metadata
import app.main as main_mod  # noqa: E402


# Secreto y api_key reconocibles: si alguno aparece en un mensaje de error o en
# los logs, la prueba debe fallar (R1.4).
SECRET_VALUE = "super-secret-value-should-never-leak"
API_KEY_VALUE = "PKTEST-api-key-wxyz"


# ---------------------------------------------------------------------------
# Fixtures a nivel de servicio (repositorio y factory mockeados)
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_key(monkeypatch):
    """Clave Fernet válida en el entorno; resetea el cache de settings."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


def _make_service():
    repository = MagicMock()
    factory = MagicMock()
    service = CredentialService(repository, factory)
    return service, repository, factory


# ---------------------------------------------------------------------------
# Validate-before-persist ordering (R2.1) — explícito
# ---------------------------------------------------------------------------


def test_store_validates_before_persisting_call_order(valid_key):
    """En el camino feliz, factory.validate se invoca ANTES de replace_active (R2.1).

    Se registra el orden real de llamadas con un ``parent mock`` y ``attach_mock``
    para no depender del orden en que se leen los mocks por separado.
    """
    service, repository, factory = _make_service()

    parent = mock.Mock()
    parent.attach_mock(factory.validate, "validate")
    parent.attach_mock(repository.replace_active, "replace_active")

    # replace_active devuelve una fila plausible para construir la metadata.
    repository.replace_active.return_value = MagicMock(
        key_id_last4="wxyz", validation_status="valid", updated_at=None
    )

    service.store(API_KEY_VALUE, SECRET_VALUE)

    # El orden observado debe ser: primero validate, luego replace_active.
    ordered_names = [call[0] for call in parent.mock_calls]
    assert ordered_names.index("validate") < ordered_names.index("replace_active")


# ---------------------------------------------------------------------------
# Encryption key missing/invalid -> EncryptionError, store unchanged (R1.6)
# ---------------------------------------------------------------------------


def test_store_missing_encryption_key_raises_and_leaves_store_unchanged(monkeypatch):
    """APP_ENCRYPTION_KEY ausente -> EncryptionError sin persistir ni validar (R1.6)."""
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    try:
        service, repository, factory = _make_service()

        with pytest.raises(EncryptionError):
            service.store(API_KEY_VALUE, SECRET_VALUE)

        # La store queda intacta y ni siquiera se llega a validar contra Alpaca:
        # el cifrado ocurre antes de validar/persistir.
        repository.replace_active.assert_not_called()
        factory.validate.assert_not_called()
    finally:
        get_settings.cache_clear()


def test_store_invalid_encryption_key_raises_and_leaves_store_unchanged(monkeypatch):
    """APP_ENCRYPTION_KEY inválida (no-Fernet) -> EncryptionError sin persistir (R1.6)."""
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    get_settings.cache_clear()
    try:
        service, repository, factory = _make_service()

        with pytest.raises(EncryptionError):
            service.store(API_KEY_VALUE, SECRET_VALUE)

        repository.replace_active.assert_not_called()
        factory.validate.assert_not_called()
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# No secret in error messages / logs across error paths (R1.4)
# ---------------------------------------------------------------------------


def test_invalid_credentials_error_message_excludes_secret(valid_key, caplog):
    """InvalidCredentialsError: str(exc) y logs no contienen el secreto (R1.4)."""
    service, repository, factory = _make_service()
    factory.validate.side_effect = InvalidCredentialsError("invalid Alpaca credentials")

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(InvalidCredentialsError) as excinfo:
            service.store(API_KEY_VALUE, SECRET_VALUE)

    assert SECRET_VALUE not in str(excinfo.value)
    assert API_KEY_VALUE not in str(excinfo.value)
    assert SECRET_VALUE not in caplog.text
    repository.replace_active.assert_not_called()


def test_transient_error_message_excludes_secret(valid_key, caplog):
    """TransientAlpacaError: str(exc) y logs no contienen el secreto (R1.4)."""
    service, repository, factory = _make_service()
    factory.validate.side_effect = TransientAlpacaError(
        "temporary problem reaching Alpaca, try again"
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(TransientAlpacaError) as excinfo:
            service.store(API_KEY_VALUE, SECRET_VALUE)

    assert SECRET_VALUE not in str(excinfo.value)
    assert API_KEY_VALUE not in str(excinfo.value)
    assert SECRET_VALUE not in caplog.text
    repository.replace_active.assert_not_called()


def test_encryption_error_message_excludes_secret(monkeypatch, caplog):
    """EncryptionError: str(exc) y logs no contienen el secreto (R1.4)."""
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    get_settings.cache_clear()
    try:
        service, repository, _ = _make_service()

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(EncryptionError) as excinfo:
                service.store(API_KEY_VALUE, SECRET_VALUE)

        assert SECRET_VALUE not in str(excinfo.value)
        assert API_KEY_VALUE not in str(excinfo.value)
        assert SECRET_VALUE not in caplog.text
        repository.replace_active.assert_not_called()
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Router smoke tests vía TestClient (códigos y error_code)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _router_env(monkeypatch):
    """Clave Fernet válida y config paper para el TestClient del router."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("ALPACA_PAPER_ONLY", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    """TestClient con SQLite en memoria (StaticPool) sobreescribiendo get_db."""
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


def test_delete_credentials_returns_200_deletion_result(client):
    """DELETE /credentials -> 200 DeletionResult (sin credenciales: deleted=False)."""
    resp = client.delete("/credentials")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is False
    assert body["detail"] == "no credentials to delete"


def test_delete_credentials_after_store_returns_deleted_true(client):
    """Tras almacenar, DELETE /credentials -> 200 deleted=True (idempotencia observable)."""
    with mock.patch.object(
        factory_mod.AlpacaClientFactory, "validate", return_value=None
    ):
        post = client.post(
            "/credentials",
            json={"api_key": API_KEY_VALUE, "secret": SECRET_VALUE},
        )
    assert post.status_code == 201

    resp = client.delete("/credentials")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_post_credentials_transient_returns_502(client):
    """validate lanza TransientAlpacaError -> 502 error_code 'transient_error'."""
    with mock.patch.object(
        factory_mod.AlpacaClientFactory,
        "validate",
        side_effect=TransientAlpacaError("temporary problem reaching Alpaca, try again"),
    ):
        resp = client.post(
            "/credentials",
            json={"api_key": API_KEY_VALUE, "secret": SECRET_VALUE},
        )

    assert resp.status_code == 502
    assert resp.json()["error_code"] == "transient_error"
    assert SECRET_VALUE not in resp.text


def test_post_credentials_encryption_error_returns_503(client, monkeypatch):
    """Clave de cifrado inválida -> EncryptionError -> 503 'encryption_unavailable'.

    Se fuerza una clave Fernet inválida DESPUÉS de arrancar el TestClient para
    que ``security._get_cipher`` (que lee la clave por request) falle al cifrar.
    """
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    get_settings.cache_clear()

    resp = client.post(
        "/credentials",
        json={"api_key": API_KEY_VALUE, "secret": SECRET_VALUE},
    )

    assert resp.status_code == 503
    assert resp.json()["error_code"] == "encryption_unavailable"
    assert SECRET_VALUE not in resp.text
