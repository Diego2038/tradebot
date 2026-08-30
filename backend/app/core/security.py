"""Cifrado simétrico de credenciales sensibles (API keys de Alpaca).

Las credenciales se guardan cifradas en la base de datos y solo se descifran
en memoria del backend en el momento de usarlas. Nunca se devuelven al frontend
ni se registran en logs.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class EncryptionError(RuntimeError):
    """Error al cifrar o descifrar un secreto."""


def _get_cipher() -> Fernet:
    key = get_settings().app_encryption_key
    if not key:
        raise EncryptionError(
            "APP_ENCRYPTION_KEY no está configurada. Genera una con "
            "Fernet.generate_key() y pásala por entorno."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise EncryptionError("APP_ENCRYPTION_KEY inválida (debe ser una clave Fernet).") from exc


def encrypt_secret(plaintext: str) -> str:
    """Cifra un secreto y devuelve el token en texto (para persistir en BD)."""
    if not plaintext:
        raise EncryptionError("No se puede cifrar un valor vacío.")
    return _get_cipher().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Descifra un token previamente producido por encrypt_secret."""
    try:
        return _get_cipher().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionError("No se pudo descifrar el secreto (token inválido).") from exc
