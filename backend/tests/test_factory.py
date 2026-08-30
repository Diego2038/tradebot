"""Pruebas del `AlpacaClientFactory` (Tarea 5).

El SDK de Alpaca se mockea por completo vía ``sys.modules`` para no depender de
la firma real ni realizar llamadas de red. Cubren:

- Property 7: todo cliente construido apunta a paper (``paper=True``).
- Properties 4 y 5: 401/403 -> InvalidCredentialsError; timeout/red ->
  TransientAlpacaError (distinguibles).
- Property 12: tras ``build_trading_client`` ningún atributo del factory
  contiene el secreto en claro.
- R4.3: sin credenciales -> CredentialsRequiredError.
"""
from __future__ import annotations

import sys
import types
from unittest import mock

import pytest
from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar el factory (no está instalado en el
# entorno de test y no debe realizar red).
# ---------------------------------------------------------------------------


class _FakeAPIError(Exception):
    """Sustituto de alpaca.common.exceptions.APIError con status HTTP."""

    def __init__(self, message: str = "api error", status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _install_alpaca_stub() -> None:
    if "alpaca" in sys.modules:
        return
    alpaca_pkg = types.ModuleType("alpaca")
    alpaca_pkg.__path__ = []  # marca como paquete

    trading_pkg = types.ModuleType("alpaca.trading")
    trading_pkg.__path__ = []
    trading_client_mod = types.ModuleType("alpaca.trading.client")

    class TradingClient:  # firma mínima compatible
        def __init__(self, api_key=None, secret_key=None, paper=True, **kwargs):
            self._api_key = api_key
            self._secret_key = secret_key
            self._paper = paper

        def get_account(self):  # pragma: no cover - se mockea en cada test
            raise NotImplementedError

    trading_client_mod.TradingClient = TradingClient

    common_pkg = types.ModuleType("alpaca.common")
    common_pkg.__path__ = []
    exceptions_mod = types.ModuleType("alpaca.common.exceptions")
    exceptions_mod.APIError = _FakeAPIError

    sys.modules["alpaca"] = alpaca_pkg
    sys.modules["alpaca.trading"] = trading_pkg
    sys.modules["alpaca.trading.client"] = trading_client_mod
    sys.modules["alpaca.common"] = common_pkg
    sys.modules["alpaca.common.exceptions"] = exceptions_mod


_install_alpaca_stub()

from app.core.config import get_settings  # noqa: E402
from app.services.alpaca_client import factory as factory_mod  # noqa: E402
from app.services.alpaca_client.errors import (  # noqa: E402
    AccountQueryError,
    CredentialsRequiredError,
    InvalidCredentialsError,
    TransientAlpacaError,
)
from app.services.alpaca_client.factory import AlpacaClientFactory  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    """Clave Fernet válida y config paper por defecto; resetea el cache."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("ALPACA_PAPER_ONLY", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeCredentialRow:
    def __init__(self, encrypted_api_key: str, encrypted_api_secret: str):
        self.encrypted_api_key = encrypted_api_key
        self.encrypted_api_secret = encrypted_api_secret
        self.key_id_last4 = "0000"
        self.validation_status = "valid"


def _make_repo(active_row):
    repo = mock.Mock()
    repo.get_active.return_value = active_row
    return repo


def _encrypt(value: str) -> str:
    from app.core import security

    return security.encrypt_secret(value)


# ---------------------------------------------------------------------------
# build_trading_client
# ---------------------------------------------------------------------------


def test_build_trading_client_uses_paper_true():
    """Property 7: el cliente se construye con paper=True."""
    api_key = "PKTEST-key-123"
    secret = "super-secret-value-xyz"
    row = _FakeCredentialRow(_encrypt(api_key), _encrypt(secret))
    repo = _make_repo(row)
    settings = get_settings()

    with mock.patch.object(factory_mod, "TradingClient") as MockClient:
        AlpacaClientFactory(repo, settings).build_trading_client()

    assert MockClient.call_count == 1
    _args, kwargs = MockClient.call_args
    # paper=True se pasa como kwarg explícito
    assert kwargs.get("paper") is True
    # Property 11 (bonus): reconstruye con la key/secret originales.
    passed = list(MockClient.call_args.args) + list(kwargs.values())
    assert api_key in passed
    assert secret in passed


def test_build_trading_client_without_credentials_raises():
    """R4.3: sin credenciales activas -> CredentialsRequiredError."""
    repo = _make_repo(None)
    settings = get_settings()

    with mock.patch.object(factory_mod, "TradingClient") as MockClient:
        with pytest.raises(CredentialsRequiredError):
            AlpacaClientFactory(repo, settings).build_trading_client()

    MockClient.assert_not_called()


def test_build_trading_client_does_not_retain_secret():
    """Property 12: tras construir, ningún atributo del factory tiene el secreto."""
    api_key = "PKTEST-key-abc"
    secret = "plaintext-secret-to-track-42"
    row = _FakeCredentialRow(_encrypt(api_key), _encrypt(secret))
    repo = _make_repo(row)
    settings = get_settings()

    fac = AlpacaClientFactory(repo, settings)
    with mock.patch.object(factory_mod, "TradingClient"):
        fac.build_trading_client()

    for name, value in vars(fac).items():
        assert secret not in repr(value), f"secreto retenido en atributo {name}"
        assert api_key not in repr(value), f"api_key retenida en atributo {name}"


# ---------------------------------------------------------------------------
# validate: clasificación de errores
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_validate_maps_auth_status_to_invalid_credentials(status):
    """Property 4: 401/403 -> InvalidCredentialsError."""
    repo = _make_repo(None)
    settings = get_settings()

    fake_client = mock.Mock()
    fake_client.get_account.side_effect = _FakeAPIError("nope", status_code=status)

    with mock.patch.object(factory_mod, "TradingClient", return_value=fake_client):
        with pytest.raises(InvalidCredentialsError):
            AlpacaClientFactory(repo, settings).validate("k", "s")


def test_validate_maps_timeout_to_transient():
    """Property 5: timeout -> TransientAlpacaError (no InvalidCredentialsError)."""
    repo = _make_repo(None)
    settings = get_settings()

    class ReadTimeout(Exception):
        pass

    fake_client = mock.Mock()
    fake_client.get_account.side_effect = ReadTimeout("timed out")

    with mock.patch.object(factory_mod, "TradingClient", return_value=fake_client):
        with pytest.raises(TransientAlpacaError):
            AlpacaClientFactory(repo, settings).validate("k", "s")


def test_validate_maps_connection_error_to_transient():
    """Property 5: error de red -> TransientAlpacaError, distinguible del auth."""
    repo = _make_repo(None)
    settings = get_settings()

    fake_client = mock.Mock()
    fake_client.get_account.side_effect = ConnectionError("connection refused")

    with mock.patch.object(factory_mod, "TradingClient", return_value=fake_client):
        with pytest.raises(TransientAlpacaError) as exc_info:
            AlpacaClientFactory(repo, settings).validate("k", "s")
    # Distinguibilidad explícita (R2.3): no es un InvalidCredentialsError.
    assert not isinstance(exc_info.value, InvalidCredentialsError)


def test_validate_maps_other_api_error_to_account_query_error():
    """Otros APIError (no-auth) -> AccountQueryError."""
    repo = _make_repo(None)
    settings = get_settings()

    fake_client = mock.Mock()
    fake_client.get_account.side_effect = _FakeAPIError("boom", status_code=500)

    with mock.patch.object(factory_mod, "TradingClient", return_value=fake_client):
        with pytest.raises(AccountQueryError):
            AlpacaClientFactory(repo, settings).validate("k", "s")


def test_validate_success_does_not_raise():
    """Camino feliz: get_account responde y validate retorna sin error."""
    repo = _make_repo(None)
    settings = get_settings()

    fake_client = mock.Mock()
    fake_client.get_account.return_value = mock.Mock()

    with mock.patch.object(factory_mod, "TradingClient", return_value=fake_client):
        AlpacaClientFactory(repo, settings).validate("k", "s")

    fake_client.get_account.assert_called_once()
