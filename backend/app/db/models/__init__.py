"""Modelos ORM de SQLAlchemy.

Importar los modelos aquí garantiza que queden registrados en
`app.db.base.Base.metadata` cuando se importe el paquete, de modo que
`Base.metadata.create_all` los tenga en cuenta.
"""
from __future__ import annotations

from app.db.models.alpaca_credential import AlpacaCredential

__all__ = ["AlpacaCredential"]
