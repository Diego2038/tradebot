"""Pruebas de los constructores de datos de cripto del `AlpacaClientFactory` (Tarea 3).

Extiende las pruebas del spec 01 sin tocar ``test_factory.py``. El SDK de Alpaca
se stubbea por completo vía ``sys.modules`` ANTES de importar el factory, para no
depender de la firma real ni realizar red. Cubre:

- R1.7 / R2.1: ``build_crypto_data_client`` y ``build_crypto_data_stream`` con
  credenciales activas construyen el cliente correspondiente, recibiendo la
  key/secret DESCIFRADOS.
- R1.8: sin credenciales activas (``get_active() is None``) ambos lanzan
  ``CredentialsRequiredError`` y NO construyen ningún cliente.
"""
from __future__ import annotations

import sys
import types
from unittest import mock

import pytest
from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar el factory. Además del cliente de
# trading (mínimo, como en test_factory.py), stubbeamos los submódulos de datos
# que este archivo ejercita: alpaca.data.historical y alpaca.data.live.
# ---------------------------------------------------------------------------


class _FakeCryptoHistoricalDataClient:
    """Sustituto de alpaca.data.historical.CryptoHistoricalDataClient."""

    def __init__(self, api_key=None, secret_key=None, *args, **kwargs):
        # Guardamos posicional/kw para poder inspeccionar lo que se le pasó.
        self.init_args = args
        self.init_kwargs = kwargs
        self.api_key = api_key
        self.secret_key = secret_key


class _FakeCryptoDataStream:
    """Sustituto de alpaca.data.live.CryptoDataStream."""

    def __init__(self, api_key=None, secret_key=None, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs
        self.api_key = api_key
        self.secret_key = secret_key


def _install_alpaca_stub() -> None:
    """Instala paquetes stub de alpaca en sys.modules de forma idempotente.

    Reutiliza lo ya presente (p.ej. si test_factory.py corrió antes) y añade los
    submódulos de datos que faltan sin pisar los existentes.
    """
    if "alpaca" not in sys.modules:
        alpaca_pkg = types.ModuleType("alpaca")
        alpaca_pkg.__path__ = []  # marca como paquete
        sys.modules["alpaca"] = alpaca_pkg

    # --- alpaca.trading.client (mínimo, compatible con el stub del spec 01) ---
    if "alpaca.trading.client" not in sys.modules:
        trading_pkg = types.ModuleType("alpaca.trading")
        trading_pkg.__path__ = []
        trading_client_mod = types.ModuleType("alpaca.trading.client")

        class TradingClient:  # firma mínima compatible
            def __init__(self, api_key=None, secret_key=None, paper=True, **kwargs):
                self._api_key = api_key
                self._secret_key = secret_key
                self._paper = paper

            def get_account(self):  # pragma: no cover - no se usa aquí
                raise NotImplementedError

        trading_client_mod.TradingClient = TradingClient
        sys.modules["alpaca.trading"] = trading_pkg
        sys.modules["alpaca.trading.client"] = trading_client_mod

    # --- alpaca.data.historical.CryptoHistoricalDataClient ---
    if "alpaca.data.historical" not in sys.modules:
        if "alpaca.data" not in sys.modules:
            data_pkg = types.ModuleType("alpaca.data")
            data_pkg.__path__ = []
            sys.modules["alpaca.data"] = data_pkg
        historical_mod = types.ModuleType("alpaca.data.historical")
        historical_mod.CryptoHistoricalDataClient = _FakeCryptoHistoricalDataClient
        sys.modules["alpaca.data.historical"] = historical_mod

    # --- alpaca.data.live.CryptoDataStream ---
    if "alpaca.data.live" not in sys.modules:
        if "alpaca.data" not in sys.modules:
            data_pkg = types.ModuleType("alpaca.data")
            data_pkg.__path__ = []
            sys.modules["alpaca.data"] = data_pkg
        live_mod = types.ModuleType("alpaca.data.live")
        live_mod.CryptoDataStream = _FakeCryptoDataStream
        sys.modules["alpaca.data.live"] = live_mod


_install_alpaca_stub()

from app.core.config import get_settings  # noqa: E402
from app.services.alpaca_client.errors import (  # noqa: E402
    CredentialsRequiredError,
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
# build_crypto_data_client (R1.7)
# ---------------------------------------------------------------------------


def test_build_crypto_data_client_uses_decrypted_credentials():
    """R1.7: con credenciales activas construye el cliente histórico con la
    key/secret DESCIFRADOS."""
    api_key = "PKTEST-crypto-key-123"
    secret = "super-secret-crypto-xyz"
    row = _FakeCredentialRow(_encrypt(api_key), _encrypt(secret))
    repo = _make_repo(row)
    settings = get_settings()

    client = AlpacaClientFactory(repo, settings).build_crypto_data_client()

    assert isinstance(client, _FakeCryptoHistoricalDataClient)
    # El constructor recibió las credenciales descifradas (posicional o kw).
    passed = [client.api_key, client.secret_key, *client.init_args, *client.init_kwargs.values()]
    assert api_key in passed
    assert secret in passed


def test_build_crypto_data_client_without_credentials_raises():
    """R1.8: sin credenciales activas -> CredentialsRequiredError, sin construir cliente."""
    repo = _make_repo(None)
    settings = get_settings()

    with mock.patch.object(
        sys.modules["alpaca.data.historical"],
        "CryptoHistoricalDataClient",
    ) as MockClient:
        with pytest.raises(CredentialsRequiredError):
            AlpacaClientFactory(repo, settings).build_crypto_data_client()

    MockClient.assert_not_called()


# ---------------------------------------------------------------------------
# build_crypto_data_stream (R2.1)
# ---------------------------------------------------------------------------


def test_build_crypto_data_stream_uses_decrypted_credentials():
    """R2.1: con credenciales activas construye el stream con la key/secret DESCIFRADOS."""
    api_key = "PKTEST-stream-key-456"
    secret = "super-secret-stream-abc"
    row = _FakeCredentialRow(_encrypt(api_key), _encrypt(secret))
    repo = _make_repo(row)
    settings = get_settings()

    stream = AlpacaClientFactory(repo, settings).build_crypto_data_stream()

    assert isinstance(stream, _FakeCryptoDataStream)
    passed = [stream.api_key, stream.secret_key, *stream.init_args, *stream.init_kwargs.values()]
    assert api_key in passed
    assert secret in passed


def test_build_crypto_data_stream_without_credentials_raises():
    """R1.8: sin credenciales activas -> CredentialsRequiredError, sin construir stream."""
    repo = _make_repo(None)
    settings = get_settings()

    with mock.patch.object(
        sys.modules["alpaca.data.live"],
        "CryptoDataStream",
    ) as MockStream:
        with pytest.raises(CredentialsRequiredError):
            AlpacaClientFactory(repo, settings).build_crypto_data_stream()

    MockStream.assert_not_called()
