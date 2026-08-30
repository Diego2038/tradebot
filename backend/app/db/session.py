"""Sesión y engine de SQLAlchemy hacia PostgreSQL."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """Dependency de FastAPI para obtener una sesión de BD por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
