"""Factory de clientes autenticados de Alpaca (`AlpacaClientFactory`).

Única puerta para construir un cliente autenticado en todo el backend (R4). El
factory descifra las credenciales almacenadas SOLO en variables locales, las
pasa al constructor del SDK y nunca las retiene en ``self`` (R4.2, Security
NFR 2). Además refuerza la barrera de paper-trading-only en cada construcción
(R5.1).
"""
from __future__ import annotations

from alpaca.trading.client import TradingClient

from app.core.config import Settings
from app.core.security import decrypt_secret
from app.services.alpaca_client.barrier import assert_paper_only
from app.services.alpaca_client.errors import (
    AccountQueryError,
    CredentialsRequiredError,
    InvalidCredentialsError,
    TransientAlpacaError,
)
from app.services.alpaca_client.repository import CredentialRepository

# Timeout máximo (segundos) que esperamos a Alpaca antes de tratar el intento
# como Transient_Error (R2.3, Resilience NFR 1 / Validation_Timeout).
VALIDATION_TIMEOUT_SECONDS = 10

# Estados HTTP que Alpaca devuelve cuando rechaza las credenciales (R2.2).
_AUTH_STATUS_CODES = frozenset({401, 403})


def _extract_status_code(error: Exception) -> int | None:
    """Extrae de forma defensiva el código HTTP de un ``APIError`` de Alpaca.

    El SDK ha expuesto el código en distintos atributos según la versión
    (``status_code`` o ``code``); intentamos ambos sin acoplarnos a uno solo.
    """
    for attr in ("status_code", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


class AlpacaClientFactory:
    """Construye clientes ``TradingClient`` de Alpaca en modo paper."""

    def __init__(self, repository: CredentialRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def build_trading_client(self) -> TradingClient:
        """Descifra las credenciales en memoria y construye un cliente paper (R4.1).

        Lanza :class:`CredentialsRequiredError` si no hay credenciales activas
        (R4.3). El secreto descifrado vive únicamente como variable local dentro
        de este método y se descarta al retornar (R4.2, Security NFR 2). Refuerza
        la barrera de paper-only (R5.1).
        """
        assert_paper_only(self._settings)

        credential = self._repository.get_active()
        if credential is None:
            raise CredentialsRequiredError("no credentials configured")

        # Descifrado SOLO en locales: nunca se asigna a self.
        api_key = decrypt_secret(credential.encrypted_api_key)
        secret = decrypt_secret(credential.encrypted_api_secret)

        client = TradingClient(api_key, secret, paper=True)
        # api_key y secret quedan fuera de alcance al retornar; no se retienen.
        return client

    def build_crypto_data_client(self):
        """Construye el cliente de datos históricos de cripto de Alpaca (R1.7).

        Reutiliza las credenciales cifradas activas, las descifra SOLO en
        variables locales (nunca en ``self``, Security NFR 2) y las pasa al
        constructor del SDK. Refuerza la barrera paper-only por coherencia con
        el resto del factory (defensa en profundidad). Lanza
        :class:`CredentialsRequiredError` si no hay credenciales configuradas
        (R1.8).

        Import perezoso de ``alpaca.data.historical`` para no acoplar la carga
        del módulo ni requerir que ese submódulo esté presente/mockeado en
        entornos que solo usan el cliente de trading.
        """
        assert_paper_only(self._settings)

        credential = self._repository.get_active()
        if credential is None:
            raise CredentialsRequiredError("no credentials configured")

        from alpaca.data.historical import CryptoHistoricalDataClient

        # Descifrado SOLO en locales: nunca se asigna a self.
        api_key = decrypt_secret(credential.encrypted_api_key)
        secret = decrypt_secret(credential.encrypted_api_secret)

        client = CryptoHistoricalDataClient(api_key, secret)
        # api_key y secret quedan fuera de alcance al retornar; no se retienen.
        return client

    def build_crypto_data_stream(self):
        """Construye el cliente de streaming de cripto de Alpaca (R2.1).

        Mismo patrón que :meth:`build_crypto_data_client`: credenciales activas,
        descifrado en locales, barrera paper-only y
        :class:`CredentialsRequiredError` cuando faltan credenciales.

        Import perezoso de ``alpaca.data.live`` por las mismas razones de
        desacoplamiento.
        """
        assert_paper_only(self._settings)

        credential = self._repository.get_active()
        if credential is None:
            raise CredentialsRequiredError("no credentials configured")

        from alpaca.data.live import CryptoDataStream

        # Descifrado SOLO en locales: nunca se asigna a self.
        api_key = decrypt_secret(credential.encrypted_api_key)
        secret = decrypt_secret(credential.encrypted_api_secret)

        stream = CryptoDataStream(api_key, secret)
        # api_key y secret quedan fuera de alcance al retornar; no se retienen.
        return stream

    def validate(self, api_key: str, secret: str) -> None:
        """Construye un cliente efímero paper y sondea ``get_account()`` (R2.1).

        Mapea las respuestas 401/403 de Alpaca a
        :class:`InvalidCredentialsError`; los timeouts y fallos de red a
        :class:`TransientAlpacaError` (distinguible del anterior, R2.3); y
        cualquier otro error de la API a :class:`AccountQueryError`.
        """
        assert_paper_only(self._settings)

        client = TradingClient(api_key, secret, paper=True)
        self._apply_timeout(client)

        try:
            client.get_account()
        except Exception as exc:  # noqa: BLE001 - clasificamos y re-lanzamos
            self._raise_classified(exc)

    def _apply_timeout(self, client: TradingClient) -> None:
        """Aplica el Validation_Timeout de 10s al cliente HTTP subyacente del SDK.

        alpaca-py usa por debajo una ``requests.Session``; configuramos su
        timeout donde el SDK lo expone. Si una versión del SDK no ofreciera un
        punto de configuración accesible, la clasificación de errores en
        :meth:`validate` sigue tratando cualquier timeout/red como
        ``TransientAlpacaError``, por lo que el comportamiento observable se
        mantiene.
        """
        # El SDK expone su sesión HTTP como atributo interno; ajustamos su
        # timeout de forma defensiva sin romper si cambia entre versiones.
        session = getattr(client, "_session", None)
        if session is not None:
            try:
                session.timeout = VALIDATION_TIMEOUT_SECONDS
            except Exception:  # noqa: BLE001 - best-effort, no debe romper validate
                pass

    @staticmethod
    def _raise_classified(error: Exception) -> None:
        """Traduce una excepción del SDK/red a un error de dominio."""
        # Import perezoso: el SDK y su tipo de excepción pueden no estar
        # disponibles/mockeados en algunos entornos de prueba.
        try:
            from alpaca.common.exceptions import APIError
        except Exception:  # noqa: BLE001
            APIError = None  # type: ignore[assignment]

        if APIError is not None and isinstance(error, APIError):
            status = _extract_status_code(error)
            if status in _AUTH_STATUS_CODES:
                raise InvalidCredentialsError("invalid Alpaca credentials") from error
            raise AccountQueryError("account query failed") from error

        # Timeouts y errores de red (requests/httpx) -> Transient (R2.3).
        if _is_transient_error(error):
            raise TransientAlpacaError(
                "temporary problem reaching Alpaca, try again"
            ) from error

        # Cualquier otro fallo inesperado se trata como error de consulta.
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
