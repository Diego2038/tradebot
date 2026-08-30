"""Pruebas basadas en propiedades (Hypothesis) de la capa cliente de Alpaca.

Tarea 9.1 del spec 01-alpaca-client. Ejercitan la lógica pura/determinista de
la capa (cifrado, ciclo de vida de credenciales, clasificación de errores,
construcción del cliente) con el SDK de Alpaca completamente mockeado y SIN red.

Cada test lleva un comentario "Feature: 01-alpaca-client, Property N: ...".
Todas las propiedades corren con >= 100 iteraciones (@settings(max_examples=100)).
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pytest
from cryptography.fernet import Fernet
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Stub del SDK alpaca-py ANTES de importar el factory (no está instalado en el
# entorno de test y nunca debe realizar red). Se reutiliza el mismo patrón que
# en tests/test_factory.py.
# ---------------------------------------------------------------------------


class _FakeAPIError(Exception):
    """Sustituto de alpaca.common.exceptions.APIError con status HTTP."""

    def __init__(self, message: str = "api error", status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _install_alpaca_stub() -> None:
    if "alpaca" in sys.modules:
        # Asegura que exista el módulo de excepciones aunque otro test haya
        # instalado su propio stub parcial.
        if "alpaca.common.exceptions" not in sys.modules:
            common_pkg = types.ModuleType("alpaca.common")
            common_pkg.__path__ = []
            exceptions_mod = types.ModuleType("alpaca.common.exceptions")
            exceptions_mod.APIError = _FakeAPIError
            sys.modules["alpaca.common"] = common_pkg
            sys.modules["alpaca.common.exceptions"] = exceptions_mod
        return

    alpaca_pkg = types.ModuleType("alpaca")
    alpaca_pkg.__path__ = []

    trading_pkg = types.ModuleType("alpaca.trading")
    trading_pkg.__path__ = []
    trading_client_mod = types.ModuleType("alpaca.trading.client")

    class TradingClient:  # firma mínima compatible con el SDK real
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

# Usa SIEMPRE la MISMA clase APIError que registró el stub en sys.modules (que
# puede haber sido instalada por otra suite de tests, p. ej. test_factory.py).
# El factory clasifica por ``isinstance(error, APIError)`` importando esa misma
# clave, así que debemos construir los errores de auth con la clase efectiva.
from alpaca.common.exceptions import APIError as _APIError  # noqa: E402

from app.core import security  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.schemas.alpaca import CredentialMetadata  # noqa: E402
from app.services.alpaca_client import factory as factory_mod  # noqa: E402
from app.services.alpaca_client.credential_service import CredentialService  # noqa: E402
from app.services.alpaca_client.errors import (  # noqa: E402
    InvalidCredentialsError,
    TransientAlpacaError,
)
from app.services.alpaca_client.factory import AlpacaClientFactory  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: clave Fernet válida + config paper por defecto (reseteando el cache).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("ALPACA_PAPER_ONLY", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# Los tests usan function-scoped fixtures (monkeypatch) dentro de @given, por lo
# que suprimimos el health check correspondiente: la clave es estable durante
# todas las iteraciones del ejemplo.
_PBT_SETTINGS = settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _stored_row(*, encrypted_api_key, encrypted_api_secret, key_id_last4,
                validation_status="valid"):
    return SimpleNamespace(
        encrypted_api_key=encrypted_api_key,
        encrypted_api_secret=encrypted_api_secret,
        key_id_last4=key_id_last4,
        validation_status=validation_status,
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Property 1: el round-trip de cifrado nunca expone el texto plano.
# ---------------------------------------------------------------------------


@_PBT_SETTINGS
@given(secret=st.text(min_size=1))
def test_property_1_encryption_roundtrip_never_exposes_plaintext(secret):
    # Feature: 01-alpaca-client, Property 1: Encryption round-trip never exposes
    # plaintext -- para cualquier string no vacío, el token cifrado difiere del
    # texto plano y descifrarlo devuelve exactamente el original.
    # Validates: Requirements 1.1, 1.2
    token = security.encrypt_secret(secret)
    assert token != secret
    assert security.decrypt_secret(token) == secret


# ---------------------------------------------------------------------------
# Property 3: la metadata devuelta nunca contiene el secreto.
# ---------------------------------------------------------------------------


# Credenciales con prefijos distintivos ("APIKEY-" / "SECRET-") y sufijo
# arbitrario. El prefijo garantiza que el valor completo (a) es más largo que el
# ``key_id_last4`` legítimamente expuesto y (b) no colisiona por azar con texto
# estructural del JSON ni con el timestamp, de modo que "valor completo ausente"
# sea una aserción significativa sobre fuga real del secreto/api_key.
_API_KEYS = st.text(min_size=1).map(lambda s: "APIKEY-" + s)
_SECRETS = st.text(min_size=1).map(lambda s: "SECRET-" + s)


@_PBT_SETTINGS
@given(api_key=_API_KEYS, secret=_SECRETS)
def test_property_3_metadata_never_contains_secret(api_key, secret):
    # Feature: 01-alpaca-client, Property 3: Metadata output never contains the
    # secret -- para credenciales almacenadas arbitrarias, el dump serializado
    # de inspect() no contiene el secreto ni la api_key en claro y expone SOLO
    # las claves {exists, key_id_last4, validation_status, updated_at}. El único
    # fragmento de la key permitido es su ``key_id_last4`` (últimos 4 caracteres).
    # Validates: Requirements 1.3, 6.1
    repository = mock.MagicMock()
    factory = mock.MagicMock()
    service = CredentialService(repository, factory)

    row = _stored_row(
        encrypted_api_key=security.encrypt_secret(api_key),
        encrypted_api_secret=security.encrypt_secret(secret),
        key_id_last4=api_key[-4:],
    )
    repository.get_active.return_value = row

    metadata = service.inspect()
    assert isinstance(metadata, CredentialMetadata)

    dumped = metadata.model_dump()
    # Solo metadatos no sensibles; ningún campo de secreto en ningún sitio.
    assert set(dumped.keys()) == {
        "exists",
        "key_id_last4",
        "validation_status",
        "updated_at",
    }

    serialized = metadata.model_dump_json()
    # El secreto NUNCA aparece en la salida serializada.
    assert secret not in serialized
    # La api_key COMPLETA nunca aparece; solo se expone su key_id_last4.
    assert api_key not in serialized
    assert dumped["key_id_last4"] == api_key[-4:]
    # El token cifrado tampoco se filtra (inspect nunca descifra).
    assert row.encrypted_api_key not in serialized
    assert row.encrypted_api_secret not in serialized


# ---------------------------------------------------------------------------
# Property 4: 401/403 -> InvalidCredentialsError y la store queda intacta.
# ---------------------------------------------------------------------------


@_PBT_SETTINGS
@given(
    status=st.sampled_from([401, 403]),
    api_key=st.text(min_size=1).filter(lambda s: s.strip() != ""),
    secret=st.text(min_size=1).filter(lambda s: s.strip() != ""),
)
def test_property_4_auth_error_maps_to_invalid_and_store_unchanged(status, api_key, secret):
    # Feature: 01-alpaca-client, Property 4: 401/403 maps to
    # InvalidCredentialsError and leaves the store unchanged -- para status en
    # {401, 403}, store() lanza InvalidCredentialsError y NO llama a
    # repository.replace_active.
    # Validates: Requirements 2.2
    repository = mock.MagicMock()
    settings_obj = get_settings()

    fake_client = mock.Mock()
    fake_client.get_account.side_effect = _APIError("nope", status_code=status)

    with mock.patch.object(factory_mod, "TradingClient", return_value=fake_client):
        factory = AlpacaClientFactory(repository, settings_obj)
        service = CredentialService(repository, factory)
        with pytest.raises(InvalidCredentialsError):
            service.store(api_key, secret)

    repository.replace_active.assert_not_called()


# ---------------------------------------------------------------------------
# Property 5: timeout/red -> TransientAlpacaError distinguible y store intacta.
# ---------------------------------------------------------------------------


# Los nombres de clase importan: el factory clasifica timeouts/red por nombre en
# el MRO (Timeout, ReadTimeout, ConnectTimeout, ConnectionError, ...), imitando a
# requests/httpx sin acoplarse a que estén instalados.
class ReadTimeout(Exception):
    pass


class ConnectTimeout(Exception):
    pass


def _transient_exceptions():
    """Genera excepciones de timeout/red que el factory debe clasificar como transitorias."""
    return st.sampled_from(
        [
            TimeoutError("timed out"),
            ConnectionError("connection refused"),
            ReadTimeout("read timed out"),
            ConnectTimeout("connect timed out"),
        ]
    )


@_PBT_SETTINGS
@given(
    exc=_transient_exceptions(),
    api_key=st.text(min_size=1).filter(lambda s: s.strip() != ""),
    secret=st.text(min_size=1).filter(lambda s: s.strip() != ""),
)
def test_property_5_transient_error_distinguishable_and_store_unchanged(exc, api_key, secret):
    # Feature: 01-alpaca-client, Property 5: Timeout/network failures map to a
    # distinguishable TransientAlpacaError -- para excepciones de timeout/red
    # arbitrarias se obtiene TransientAlpacaError (nunca InvalidCredentialsError)
    # y store no llama a repository.replace_active.
    # Validates: Requirements 2.3
    repository = mock.MagicMock()
    settings_obj = get_settings()

    fake_client = mock.Mock()
    fake_client.get_account.side_effect = exc

    with mock.patch.object(factory_mod, "TradingClient", return_value=fake_client):
        factory = AlpacaClientFactory(repository, settings_obj)
        service = CredentialService(repository, factory)
        with pytest.raises(TransientAlpacaError) as exc_info:
            service.store(api_key, secret)

    # Distinguibilidad explícita (R2.3): no es un InvalidCredentialsError.
    assert not isinstance(exc_info.value, InvalidCredentialsError)
    repository.replace_active.assert_not_called()


# ---------------------------------------------------------------------------
# Property 7: todo cliente construido apunta a paper (paper=True).
# ---------------------------------------------------------------------------


@_PBT_SETTINGS
@given(
    api_key=st.text(min_size=1).filter(lambda s: s.strip() != ""),
    secret=st.text(min_size=1).filter(lambda s: s.strip() != ""),
)
def test_property_7_every_built_client_targets_paper(api_key, secret):
    # Feature: 01-alpaca-client, Property 7: Every built client targets the paper
    # endpoint -- para credenciales arbitrarias, build_trading_client construye
    # TradingClient con paper=True (se inspeccionan los kwargs del mock).
    # Validates: Requirements 4.1, 5.1
    repository = mock.MagicMock()
    settings_obj = get_settings()

    row = _stored_row(
        encrypted_api_key=security.encrypt_secret(api_key),
        encrypted_api_secret=security.encrypt_secret(secret),
        key_id_last4=api_key[-4:],
    )
    repository.get_active.return_value = row

    with mock.patch.object(factory_mod, "TradingClient") as MockClient:
        AlpacaClientFactory(repository, settings_obj).build_trading_client()

    assert MockClient.call_count == 1
    _args, kwargs = MockClient.call_args
    assert kwargs.get("paper") is True
