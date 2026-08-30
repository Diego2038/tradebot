"""Jerarquía de errores de dominio de la capa cliente de Alpaca.

Cada error permite al router mapear la causa a una respuesta HTTP distinta y
distinguible (R2.3, Resilience NFR 2). `EncryptionError` de
`app.core.security` se reutiliza tal cual para el caso R1.6.
"""
from __future__ import annotations


class AlpacaClientError(Exception):
    """Base de todos los errores emitidos por la capa cliente de Alpaca."""


class CredentialsRequiredError(AlpacaClientError):
    """Un campo estaba vacío/en blanco, o no hay credenciales configuradas."""


class InvalidCredentialsError(AlpacaClientError):
    """Alpaca rechazó las credenciales con HTTP 401/403."""


class TransientAlpacaError(AlpacaClientError):
    """Timeout (>10s) o fallo de red al alcanzar Alpaca."""


class AccountQueryError(AlpacaClientError):
    """Alpaca devolvió un error no-auth al consultar la cuenta."""


class PaperOnlyViolationError(AlpacaClientError):
    """La configuración apunta a una base URL no-paper con ALPACA_PAPER_ONLY activo."""
