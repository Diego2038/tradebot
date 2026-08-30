"""Servicio de credenciales de Alpaca (`CredentialService`).

Orquesta la validación, el cifrado y la persistencia de las credenciales.
Depende del repositorio (persistencia) y del factory (validación contra
Alpaca). El orden crítico es: cifrar y validar ANTES de escribir en la
`Credential_Store`; ante cualquier fallo la store queda intacta (R2.2, R2.3).
"""
from __future__ import annotations

from app.core.security import encrypt_secret
from app.schemas.alpaca import CredentialMetadata, DeletionResult
from app.services.alpaca_client.errors import CredentialsRequiredError
from app.services.alpaca_client.factory import AlpacaClientFactory
from app.services.alpaca_client.repository import CredentialRepository

# Estado de validación que se registra tras una prueba exitosa contra Alpaca.
_VALIDATION_STATUS_VALID = "valid"


class CredentialService:
    """Gestiona el ciclo de vida de las credenciales: store / inspect / delete."""

    def __init__(
        self,
        repository: CredentialRepository,
        factory: AlpacaClientFactory,
    ) -> None:
        self._repository = repository
        self._factory = factory

    def store(self, api_key: str, secret: str) -> CredentialMetadata:
        """Valida contra Alpaca y luego cifra + persiste como único conjunto activo.

        Orden crítico (R2.1): cifrar y validar ANTES de escribir. Ante cualquier
        fallo, la `Credential_Store` queda intacta.

        Raises:
            CredentialsRequiredError: api_key o secret vacíos/solo espacios (R1.7).
            EncryptionError: APP_ENCRYPTION_KEY ausente/inválida (R1.6).
            InvalidCredentialsError: Alpaca devolvió 401/403 (R2.2).
            TransientAlpacaError: timeout/fallo de red (R2.3).
        """
        # (1) Rechazar campos vacíos o solo espacios sin tocar la store (R1.7).
        if not api_key or not api_key.strip() or not secret or not secret.strip():
            raise CredentialsRequiredError("field is required")

        # (2) Cifrar api_key y secret; deja propagar EncryptionError si la clave
        # de cifrado falta o es inválida (R1.6). La store sigue intacta.
        encrypted_api_key = encrypt_secret(api_key)
        encrypted_api_secret = encrypt_secret(secret)

        # (3) VALIDAR ANTES DE PERSISTIR: si validate() lanza
        # InvalidCredentialsError o TransientAlpacaError NO persistimos y
        # re-lanzamos, dejando la store intacta (R2.1, R2.2, R2.3).
        self._factory.validate(api_key, secret)

        # (4) Solo tras validar OK: calcular key_id_last4 del api_key en claro y
        # persistir como único conjunto activo con estado "valid" (R1.5, R2.4).
        key_id_last4 = api_key[-4:]
        credential = self._repository.replace_active(
            encrypted_api_key=encrypted_api_key,
            encrypted_api_secret=encrypted_api_secret,
            key_id_last4=key_id_last4,
            validation_status=_VALIDATION_STATUS_VALID,
        )

        # (5) Devolver metadata (nunca el secreto, R1.3).
        return CredentialMetadata(
            exists=True,
            key_id_last4=credential.key_id_last4,
            validation_status=credential.validation_status,
            updated_at=credential.updated_at,
        )

    def inspect(self) -> CredentialMetadata:
        """Devuelve SOLO metadatos; nunca descifra el secreto (R6.1/R6.2)."""
        credential = self._repository.get_active()
        if credential is None:
            return CredentialMetadata(exists=False)
        return CredentialMetadata(
            exists=True,
            key_id_last4=credential.key_id_last4,
            validation_status=credential.validation_status,
            updated_at=credential.updated_at,
        )

    def delete(self) -> DeletionResult:
        """Elimina el conjunto activo si existe y reporta el resultado (R6.3/R6.4)."""
        deleted = self._repository.delete_active()
        if deleted:
            return DeletionResult(deleted=True, detail="credentials removed")
        return DeletionResult(deleted=False, detail="no credentials to delete")
