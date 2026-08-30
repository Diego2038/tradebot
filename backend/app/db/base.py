"""Base declarativa compartida de SQLAlchemy 2.0.

Todos los modelos ORM del backend heredan de `Base` para compartir una única
`metadata`. Esto permite crear las tablas (`Base.metadata.create_all`) y, en el
futuro, integrar una herramienta de migraciones sobre esa misma metadata.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """DeclarativeBase compartida por todos los modelos del backend."""

    pass
