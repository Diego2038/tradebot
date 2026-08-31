"""Tests for the risk equity provider port and config error (spec 06, Task 2).

Covers the ``EquityProvider`` ``runtime_checkable`` ``Protocol``, the optional
``AccountServiceEquityProvider`` adapter (success + degrade-to-None), and
``RiskConfigError`` being a ``ValueError`` subclass.

To stay free of the Alpaca SDK, the adapter is exercised against a fully fake
``account_service`` (a plain stub), so ``AccountService`` is never imported.

Validates: Requirements 2.2, 2.7
"""

from decimal import Decimal

from app.services.risk.equity import AccountServiceEquityProvider, EquityProvider
from app.services.risk.errors import RiskConfigError


class _DummyEquityProvider:
    """A minimal object exposing ``get_equity`` -> ``Decimal | None``."""

    def get_equity(self) -> Decimal | None:
        return Decimal("1000")


class _FakeAccount:
    def __init__(self, buying_power: Decimal) -> None:
        self.buying_power = buying_power
        self.cash = buying_power
        self.status = "ACTIVE"


class _FakeAccountService:
    """Fake ``AccountService`` returning a configured account object."""

    def __init__(self, account: object) -> None:
        self._account = account

    def get_account(self) -> object:
        return self._account


class _RaisingAccountService:
    def get_account(self) -> object:
        raise RuntimeError("alpaca unreachable")


def test_dummy_provider_satisfies_equity_provider_protocol() -> None:
    # (a) runtime_checkable: any object with get_equity() is an EquityProvider.
    assert isinstance(_DummyEquityProvider(), EquityProvider)


def test_adapter_maps_buying_power_to_decimal() -> None:
    # (b) adapter returns the account's buying_power as a Decimal.
    account = _FakeAccount(buying_power=Decimal("2500.75"))
    provider = AccountServiceEquityProvider(_FakeAccountService(account))

    equity = provider.get_equity()

    assert equity == Decimal("2500.75")
    assert isinstance(equity, Decimal)


def test_adapter_satisfies_equity_provider_protocol() -> None:
    provider = AccountServiceEquityProvider(_FakeAccountService(_FakeAccount(Decimal("1"))))
    assert isinstance(provider, EquityProvider)


def test_adapter_returns_none_when_get_account_raises() -> None:
    # (c) any failure from the account service degrades to None (R2.7).
    provider = AccountServiceEquityProvider(_RaisingAccountService())
    assert provider.get_equity() is None


def test_adapter_returns_none_when_buying_power_missing() -> None:
    # A missing/None value also degrades to None rather than raising.
    class _NoBuyingPower:
        status = "ACTIVE"

    provider = AccountServiceEquityProvider(_FakeAccountService(_NoBuyingPower()))
    assert provider.get_equity() is None


def test_adapter_maps_string_buying_power_to_decimal() -> None:
    # Alpaca often reports monetary values as strings; they map cleanly.
    account = _FakeAccount(buying_power="1234.50")  # type: ignore[arg-type]
    provider = AccountServiceEquityProvider(_FakeAccountService(account))
    assert provider.get_equity() == Decimal("1234.50")


def test_risk_config_error_is_value_error_subclass() -> None:
    # (d) RiskConfigError is a subclass of ValueError.
    assert issubclass(RiskConfigError, ValueError)
    assert isinstance(RiskConfigError("bad config"), ValueError)
