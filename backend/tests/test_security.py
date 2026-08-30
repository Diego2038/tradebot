"""Pruebas mínimas del cifrado de credenciales.

Verifican el requisito clave: la API key se guarda cifrada y solo se recupera
descifrándola explícitamente (ida y vuelta correcta, y el cifrado no expone el
texto plano).
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core import security
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    """Inyecta una clave de cifrado válida y resetea la config cacheada."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_encrypt_decrypt_roundtrip():
    secret = "PKTEST-alpaca-api-key-123"
    token = security.encrypt_secret(secret)
    assert token != secret  # el valor persistido no es el texto plano
    assert security.decrypt_secret(token) == secret


def test_encrypt_empty_raises():
    with pytest.raises(security.EncryptionError):
        security.encrypt_secret("")


def test_decrypt_invalid_token_raises():
    with pytest.raises(security.EncryptionError):
        security.decrypt_secret("no-es-un-token-valido")
