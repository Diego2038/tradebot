"""Persistencia de las credenciales de Alpaca (`CredentialRepository`).

Encapsula todo el acceso a la `Credential_Store`. Los llamadores pasan y reciben
valores YA cifrados; el repositorio nunca cifra ni descifra (Isolation NFR 1).
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.alpaca_credential import AlpacaCredential


class CredentialRepository:
    """Acceso a la única fila de credenciales activas de Alpaca."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_active(self) -> AlpacaCredential | None:
        """Devuelve la única fila de credenciales activas, o None."""
        stmt = select(AlpacaCredential).order_by(AlpacaCredential.id).limit(1)
        return self._db.execute(stmt).scalars().first()

    def replace_active(
        self,
        *,
        encrypted_api_key: str,
        encrypted_api_secret: str,
        key_id_last4: str,
        validation_status: str,
    ) -> AlpacaCredential:
        """Borra cualquier fila existente e inserta una nueva en una transacción.

        Garantiza que quede exactamente un conjunto activo de credenciales
        (R1.5). Los valores recibidos ya vienen cifrados.
        """
        credential = AlpacaCredential(
            encrypted_api_key=encrypted_api_key,
            encrypted_api_secret=encrypted_api_secret,
            key_id_last4=key_id_last4,
            validation_status=validation_status,
        )
        try:
            self._db.execute(delete(AlpacaCredential))
            self._db.add(credential)
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        self._db.refresh(credential)
        return credential

    def delete_active(self) -> bool:
        """Borra la fila activa. Devuelve True si se eliminó alguna (R6.3/R6.4)."""
        try:
            result = self._db.execute(delete(AlpacaCredential))
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return result.rowcount > 0
