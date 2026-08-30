"""Pruebas del `AccountService` (Tarea 7).

El repositorio y el factory se mockean por completo, de modo que Alpaca nunca se
toca de verdad. Cubren:

- Store vacía -> ``CredentialsRequiredError`` y ``build_trading_client`` NUNCA
  se llama (R3.2).
- Con credenciales, un Account de Alpaca con ``cash``/``buying_power``/``status``
  se mapea a un ``AccountStatus`` correcto con ``mode == "paper"`` (R3.1, R5.3).
- Un error de Alpaca en ``get_account`` se mapea a
  ``AccountQueryError``/``TransientAlpacaError`` sin propagar la excepción cruda
  (R3.3).
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.alpaca import AccountStatus
from app.services.alpaca_client.account_service import AccountService
from app.services.alpaca_client.errors import (
    AccountQueryError,
    CredentialsRequiredError,
    TransientAlpacaError,
)


def _make_service(*, active_credential=None, account=None, get_account_exc=None):
    """Crea un ``AccountService`` con repo y factory mockeados (spies)."""
    repository = MagicMock()
    repository.get_active.return_value = active_credential

    client = MagicMock()
    if get_account_exc is not None:
        client.get_account.side_effect = get_account_exc
    else:
        client.get_account.return_value = account

    factory = MagicMock()
    factory.build_trading_client.return_value = client

    service = AccountService(repository=repository, factory=factory)
    return service, repository, factory, client


def test_no_credentials_raises_and_never_builds_client():
    """Store vacía -> CredentialsRequiredError sin tocar el factory (R3.2)."""
    service, repository, factory, _client = _make_service(active_credential=None)

    with pytest.raises(CredentialsRequiredError):
        service.get_account()

    repository.get_active.assert_called_once()
    # El factory/cliente NUNCA se construye ni se llama a Alpaca (mock spy).
    factory.build_trading_client.assert_not_called()


def test_maps_alpaca_account_to_account_status():
    """Con credenciales, mapea cash/buying_power/status y fija mode=paper (R3.1, R5.3)."""
    account = SimpleNamespace(
        cash="1000.55",
        buying_power="2500.10",
        status="ACTIVE",
    )
    service, repository, factory, client = _make_service(
        active_credential=SimpleNamespace(id=1),
        account=account,
    )

    result = service.get_account()

    assert isinstance(result, AccountStatus)
    assert result.cash == Decimal("1000.55")
    assert result.buying_power == Decimal("2500.10")
    assert result.status == "ACTIVE"
    assert result.mode == "paper"

    factory.build_trading_client.assert_called_once()
    client.get_account.assert_called_once()


def test_numeric_amounts_are_supported():
    """Importes numéricos (no string) también se convierten a Decimal."""
    account = SimpleNamespace(cash=1000, buying_power=2500.5, status="ACTIVE")
    service, *_ = _make_service(
        active_credential=SimpleNamespace(id=1),
        account=account,
    )

    result = service.get_account()

    assert result.cash == Decimal("1000")
    assert result.buying_power == Decimal("2500.5")
    assert result.mode == "paper"


class _FakeAPIError(Exception):
    """Simula un error genérico de la API de Alpaca (no-auth, no-red)."""


def test_alpaca_api_error_maps_to_account_query_error():
    """Un error de la API de Alpaca se mapea a AccountQueryError (R3.3)."""
    service, _repo, _factory, _client = _make_service(
        active_credential=SimpleNamespace(id=1),
        get_account_exc=_FakeAPIError("boom"),
    )

    with pytest.raises(AccountQueryError):
        service.get_account()


def test_timeout_maps_to_transient_error():
    """Un timeout/fallo de red se mapea a TransientAlpacaError (R3.3)."""
    service, _repo, _factory, _client = _make_service(
        active_credential=SimpleNamespace(id=1),
        get_account_exc=TimeoutError("timed out"),
    )

    with pytest.raises(TransientAlpacaError):
        service.get_account()


def test_connection_error_maps_to_transient_error():
    """Un ConnectionError se mapea a TransientAlpacaError (R3.3)."""
    service, *_ = _make_service(
        active_credential=SimpleNamespace(id=1),
        get_account_exc=ConnectionError("refused"),
    )

    with pytest.raises(TransientAlpacaError):
        service.get_account()


def test_domain_error_from_factory_is_not_reclassified():
    """Un error de dominio del factory (p. ej. CredentialsRequiredError) pasa tal cual."""
    repository = MagicMock()
    repository.get_active.return_value = SimpleNamespace(id=1)

    factory = MagicMock()
    factory.build_trading_client.side_effect = CredentialsRequiredError("gone")

    service = AccountService(repository=repository, factory=factory)

    with pytest.raises(CredentialsRequiredError):
        service.get_account()
