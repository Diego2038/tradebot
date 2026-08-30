"""Modelo ORM de las credenciales de Alpaca.

Solo se persisten tokens cifrados con Fernet (nunca texto plano) más metadatos
no sensibles (últimos 4 del API Key ID y último estado de validación).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlpacaCredential(Base):
    """Conjunto único de credenciales de Alpaca almacenadas cifradas.

    `encrypted_api_key` y `encrypted_api_secret` contienen exclusivamente
    tokens Fernet; el texto plano nunca se persiste (R1.2).
    """

    __tablename__ = "alpaca_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    encrypted_api_key: Mapped[str] = mapped_column(String, nullable=False)
    encrypted_api_secret: Mapped[str] = mapped_column(String, nullable=False)
    key_id_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    validation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="valid"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
