"""Servicio de consulta de cuenta paper de Alpaca (`AccountService`).

Expone ``get_account`` que devuelve el saldo (``cash``), el poder de compra
(``buying_power``) y el estado de la cuenta reportado por Alpaca, con el modo
fijo ``paper`` (R3.1, R5.3).

Si no hay credenciales configuradas, la petición se rechaza SIN construir un
cliente ni llamar a Alpaca (R3.2). Los errores y timeouts de Alpaca se
clasifican como :class:`AccountQueryError` o :class:`TransientAlpacaError`, de
modo que el backend sigue en pie y la ``Credential_Store`` queda intacta (R3.3).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from app.schemas.alpaca import AccountStatus
from app.services.alpaca_client.errors import (
    AccountQueryError,
    CredentialsRequiredError,
    TransientAlpacaError,
)
from app.services.alpaca_client.repository import CredentialRepository

if TYPE_CHECKING:  # pragma: no cover - solo para anotaciones de tipo
    from app.services.alpaca_client.factory import AlpacaClientFactory


def _to_decimal(value: object) -> Decimal:
    """Convierte de forma segura un valor monetario de Alpaca a ``Decimal``.

    Alpaca suele reportar los importes como cadenas (p. ej. ``"1000.55"``), pero
    también podrían llegar como ``int``/``float``/``Decimal``. Se pasa siempre
    por ``str`` para evitar la imprecisión binaria del ``float`` y se envuelve
    cualquier valor no numérico en :class:`AccountQueryError`.
    """
    if value is None:
        raise AccountQueryError("account query failed")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise AccountQueryError("account query failed") from exc


class AccountService:
    """Consulta el estado y el saldo de la cuenta paper de Alpaca (R3)."""

    def __init__(
        self,
        repository: CredentialRepository,
        factory: "AlpacaClientFactory",
    ) -> None:
        self._repository = repository
        self._factory = factory

    def get_account(self) -> AccountStatus:
        """Devuelve ``cash``, ``buying_power``, ``status`` y ``mode='paper'``.

        Raises:
            CredentialsRequiredError: no hay credenciales configuradas; Alpaca
                NO se llama y no se construye ningún cliente (R3.2).
            TransientAlpacaError: fallo de red o timeout (>10s) alcanzando
                Alpaca; el backend sigue en pie y la store no se altera (R3.3).
            AccountQueryError: Alpaca devolvió un error no-auth al consultar la
                cuenta; el backend sigue en pie y la store no se altera (R3.3).
        """
        # (R3.2) Comprobamos primero la existencia de credenciales; si no hay,
        # rechazamos SIN construir cliente ni tocar Alpaca.
        if self._repository.get_active() is None:
            raise CredentialsRequiredError("no credentials configured")

        # (R3.1) Construimos el cliente autenticado vía el factory y leemos la
        # cuenta. Cualquier fallo se clasifica sin propagar la excepción cruda.
        try:
            client = self._factory.build_trading_client()
            account = client.get_account()
        except (
            CredentialsRequiredError,
            AccountQueryError,
            TransientAlpacaError,
        ):
            # Errores de dominio ya clasificados (p. ej. por el factory): se
            # dejan pasar tal cual.
            raise
        except Exception as exc:  # noqa: BLE001 - clasificamos y re-lanzamos
            self._raise_classified(exc)

        # (R3.1, R5.3) Mapeamos los campos del Account de Alpaca a AccountStatus.
        return AccountStatus(
            cash=_to_decimal(getattr(account, "cash", None)),
            buying_power=_to_decimal(getattr(account, "buying_power", None)),
            status=str(getattr(account, "status", "")),
            mode="paper",
        )

    @staticmethod
    def _raise_classified(error: Exception) -> None:
        """Traduce una excepción del SDK/red a un error de dominio (R3.3).

        Timeouts y fallos de red -> :class:`TransientAlpacaError`; cualquier
        otro error de la API de Alpaca -> :class:`AccountQueryError`. En ningún
        caso se propaga la excepción cruda, de modo que el backend no se cae.
        """
        if _is_transient_error(error):
            raise TransientAlpacaError(
                "temporary problem reaching Alpaca, try again"
            ) from error
        raise AccountQueryError("account query failed") from error


def _is_transient_error(error: Exception) -> bool:
    """Indica si ``error`` es un timeout o fallo de red (por tipo o nombre).

    Se comprueba por MRO de nombres para no acoplarse a que ``requests`` o
    ``httpx`` estén instalados, y para reconocer también ``TimeoutError`` y
    ``ConnectionError`` estándar de Python.
    """
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    transient_names = {
        "Timeout",
        "ConnectTimeout",
        "ReadTimeout",
        "ConnectionError",
        "ConnectError",
        "NewConnectionError",
        "MaxRetryError",
    }
    for klass in type(error).__mro__:
        if klass.__name__ in transient_names:
            return True
    return False
