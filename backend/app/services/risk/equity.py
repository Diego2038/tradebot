"""Equity provider port for the equity-based lot limit (spec ``06-risk-manager``).

Defines :class:`EquityProvider` (a ``runtime_checkable`` ``Protocol``) that
supplies the current Alpaca paper-account equity, plus an optional adapter,
:class:`AccountServiceEquityProvider`, that sources equity from spec ``01``'s
``AccountService``. Keeping equity behind this small port means ``RiskManager``
stays decoupled from spec ``01`` and is trivially mockable in tests (R2.2, R2.7).

This module never imports the Alpaca SDK: the adapter imports
``AccountService`` lazily/safely and is only used when explicitly injected.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable


@runtime_checkable
class EquityProvider(Protocol):
    """Supplies the current Alpaca paper-account equity for the equity-based lot limit.

    Kept minimal and injectable so ``RiskManager`` stays decoupled from spec
    ``01``'s ``AccountService`` and is trivially mockable in tests (R2.2, R2.7).
    """

    def get_equity(self) -> Decimal | None:
        """Return current ``Account_Equity``, or ``None`` if it cannot be determined."""
        ...


class AccountServiceEquityProvider:
    """Optional adapter that sources equity from spec ``01``'s ``AccountService``.

    Wraps ``AccountService.get_account()`` and maps its balance to a
    :class:`~decimal.Decimal`. It returns ``None`` on any failure (missing
    credentials, transient Alpaca error, unavailable value, ...) so the caller
    degrades to ``approved=False`` rather than crashing (R2.7). This adapter is
    the only place in the risk package that touches spec ``01``.
    """

    def __init__(self, account_service: object) -> None:
        # The wrapped ``AccountService`` is injected, never constructed here, so
        # this module has no import-time dependency on spec 01 or the Alpaca SDK.
        self._account_service = account_service

    def get_equity(self) -> Decimal | None:
        """Return the account's available buying power as a ``Decimal``, or ``None``.

        We use ``buying_power`` as the equity figure for the lot limit: it best
        represents the purchasing power currently available for opening a
        position (``cash`` would be an equally valid, more conservative choice).
        Any exception or non-convertible value degrades to ``None`` so the
        caller returns ``approved=False`` instead of raising (R2.7).
        """
        try:
            account = self._account_service.get_account()
            buying_power = getattr(account, "buying_power", None)
            if buying_power is None:
                return None
            if isinstance(buying_power, Decimal):
                return buying_power
            return Decimal(str(buying_power))
        except (InvalidOperation, ValueError, TypeError):
            return None
        except Exception:  # noqa: BLE001 - any backend/SDK failure degrades to None (R2.7)
            return None
