"""Pruebas del `CredentialService` (repositorio y factory mockeados).

Verifican el orden crítico (cifrar + validar ANTES de persistir) y que ante
cualquier fallo la `Credential_Store` queda intacta, además de que la
inspección nunca expone el secreto.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet


def _install_alpaca_stub() -> None:
    """Registra un stub mínimo del SDK ``alpaca`` si no está instalado.

    ``CredentialService`` importa (transitivamente) ``factory.py``, que a nivel
    de módulo importa ``alpaca.trading.client.TradingClient``. Estas pruebas
    mockean el factory por completo, así que Alpaca nunca se toca; el stub solo
    permite que la importación funcione en entornos sin ``alpaca-py``. Si el
    paquete real (o el stub de otra prueba) ya está registrado, no hacemos nada.
    """
    if "alpaca.trading.client" in sys.modules:
        return

    trading_client_mod = types.ModuleType("alpaca.trading.client")

    class TradingClient:  # noqa: D401 - stub mínimo (el factory se mockea)
        def __init__(self, *args, **kwargs) -> None:  # pragma: no cover
            self._args = args
            self._kwargs = kwargs

    trading_client_mod.TradingClient = TradingClient
    # Registramos SOLO el submódulo que ``factory.py`` importa a nivel de módulo
    # (``from alpaca.trading.client import TradingClient``). Deliberadamente NO
    # registramos el paquete ``alpaca`` de primer nivel para no interferir con
    # otras pruebas (p. ej. las del factory) que instalan su propio stub
    # completo, incluida su ``APIError``, en función de esa clave.
    sys.modules["alpaca.trading.client"] = trading_client_mod


_install_alpaca_stub()

from app.core.config import get_settings
from app.schemas.alpaca import CredentialMetadata, DeletionResult
from app.services.alpaca_client.credential_service import CredentialService
from app.services.alpaca_client.errors import (
    CredentialsRequiredError,
    InvalidCredentialsError,
)


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    """Inyecta una clave Fernet válida para que encrypt_secret funcione."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_service():
    repository = MagicMock()
    factory = MagicMock()
    service = CredentialService(repository, factory)
    return service, repository, factory


def _stored_row(*, key_id_last4="cdef", validation_status="valid"):
    return SimpleNamespace(
        encrypted_api_key="enc-key",
        encrypted_api_secret="enc-secret",
        key_id_last4=key_id_last4,
        validation_status=validation_status,
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    "api_key,secret",
    [
        ("", "secret-value"),
        ("   ", "secret-value"),
        ("api-key-value", ""),
        ("api-key-value", "   "),
    ],
)
def test_store_blank_field_rejected_without_persisting(api_key, secret):
    """Campo en blanco -> CredentialsRequiredError sin llamar a replace_active (R1.7)."""
    service, repository, factory = _make_service()

    with pytest.raises(CredentialsRequiredError):
        service.store(api_key, secret)

    repository.replace_active.assert_not_called()
    factory.validate.assert_not_called()


def test_store_invalid_credentials_leaves_store_unchanged():
    """factory.validate lanza InvalidCredentialsError -> no se persiste (R2.2)."""
    service, repository, factory = _make_service()
    factory.validate.side_effect = InvalidCredentialsError("invalid Alpaca credentials")

    with pytest.raises(InvalidCredentialsError):
        service.store("PKTEST-api-key-abcd", "super-secret-value")

    factory.validate.assert_called_once_with("PKTEST-api-key-abcd", "super-secret-value")
    repository.replace_active.assert_not_called()


def test_store_success_persists_valid_with_last4():
    """Éxito -> replace_active una vez con validation_status='valid' y last4 correcto."""
    service, repository, factory = _make_service()
    repository.replace_active.return_value = _stored_row(key_id_last4="wxyz")

    result = service.store("PKTEST-api-key-wxyz", "super-secret-value")

    # Validación ocurre antes de persistir.
    factory.validate.assert_called_once_with(
        "PKTEST-api-key-wxyz", "super-secret-value"
    )
    repository.replace_active.assert_called_once()
    _, kwargs = repository.replace_active.call_args
    assert kwargs["validation_status"] == "valid"
    assert kwargs["key_id_last4"] == "wxyz"  # últimos 4 del api_key en claro
    # Los valores persistidos están cifrados (no son el texto plano).
    assert kwargs["encrypted_api_key"] != "PKTEST-api-key-wxyz"
    assert kwargs["encrypted_api_secret"] != "super-secret-value"

    assert isinstance(result, CredentialMetadata)
    assert result.exists is True
    assert result.validation_status == "valid"
    assert result.key_id_last4 == "wxyz"


def test_inspect_without_credentials_returns_exists_false():
    """inspect sin credenciales -> exists=False (R6.2)."""
    service, repository, _ = _make_service()
    repository.get_active.return_value = None

    result = service.inspect()

    assert isinstance(result, CredentialMetadata)
    assert result.exists is False
    assert result.key_id_last4 is None


def test_inspect_never_exposes_secret():
    """inspect nunca descifra ni expone el secreto (R6.1/R6.2)."""
    service, repository, _ = _make_service()
    row = _stored_row(key_id_last4="cdef")
    repository.get_active.return_value = row

    result = service.inspect()

    serialized = result.model_dump()
    # Solo metadatos no sensibles; sin campo de secreto en ningún sitio.
    assert set(serialized.keys()) == {
        "exists",
        "key_id_last4",
        "validation_status",
        "updated_at",
    }
    assert result.exists is True
    assert result.key_id_last4 == "cdef"
    # El repositorio nunca se descifra: get_active se usa, pero el token cifrado
    # no aparece en la salida serializada.
    assert row.encrypted_api_secret not in str(serialized)
    assert row.encrypted_api_key not in str(serialized)


def test_delete_reports_outcome():
    """delete devuelve el resultado apropiado según haya o no credenciales (R6.3/R6.4)."""
    service, repository, _ = _make_service()

    repository.delete_active.return_value = True
    removed = service.delete()
    assert isinstance(removed, DeletionResult)
    assert removed.deleted is True
    assert removed.detail == "credentials removed"

    repository.delete_active.return_value = False
    none = service.delete()
    assert none.deleted is False
    assert none.detail == "no credentials to delete"
