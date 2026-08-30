"""Pruebas unitarias de `CredentialRepository` con SQLite en memoria.

Verifican el ciclo de vida de la única fila de credenciales activas:
- `replace_active` deja siempre exactamente una fila (la última) (R1.5).
- `delete_active` devuelve True cuando había fila y False cuando está vacío (R6.3/R6.4).
- `get_active` refleja el estado actual de la store.

El repositorio recibe/devuelve valores ya cifrados; aquí usamos cadenas
opacas como sustitutos de los tokens Fernet.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.alpaca_credential import AlpacaCredential
from app.services.alpaca_client.repository import CredentialRepository


@pytest.fixture()
def db() -> Session:
    """Sesión SQLite en memoria con las tablas creadas."""
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(AlpacaCredential)).scalar_one()


def test_replace_active_twice_leaves_single_latest_row(db: Session):
    repo = CredentialRepository(db)

    repo.replace_active(
        encrypted_api_key="enc-key-1",
        encrypted_api_secret="enc-secret-1",
        key_id_last4="0001",
        validation_status="valid",
    )
    second = repo.replace_active(
        encrypted_api_key="enc-key-2",
        encrypted_api_secret="enc-secret-2",
        key_id_last4="0002",
        validation_status="valid",
    )

    assert _count(db) == 1  # exactamente un conjunto activo (R1.5)

    active = repo.get_active()
    assert active is not None
    assert active.id == second.id
    assert active.encrypted_api_key == "enc-key-2"
    assert active.encrypted_api_secret == "enc-secret-2"
    assert active.key_id_last4 == "0002"
    assert active.validation_status == "valid"


def test_get_active_none_when_empty(db: Session):
    repo = CredentialRepository(db)
    assert repo.get_active() is None


def test_delete_active_returns_true_then_false(db: Session):
    repo = CredentialRepository(db)

    repo.replace_active(
        encrypted_api_key="enc-key",
        encrypted_api_secret="enc-secret",
        key_id_last4="1234",
        validation_status="valid",
    )
    assert repo.get_active() is not None

    assert repo.delete_active() is True  # había fila -> True (R6.3)
    assert repo.get_active() is None
    assert _count(db) == 0

    assert repo.delete_active() is False  # store vacía -> False (R6.4)
