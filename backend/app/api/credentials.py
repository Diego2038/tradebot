"""Router REST de la capa cliente de Alpaca (Tarea 8).

Expone los endpoints de credenciales y de cuenta, cableando por request el
repositorio y los servicios de dominio a partir de la sesión de BD
(``Depends(get_db)``) y de la configuración (``get_settings``). Los handlers son
finos: delegan en los servicios y dejan que los ``exception handlers``
registrados en ``app/main.py`` traduzcan cada error de dominio a su respuesta
HTTP distinguible (ver tabla de Error Handling del diseño).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.alpaca import (
    AccountStatus,
    CredentialMetadata,
    CredentialSubmit,
    DeletionResult,
)
from app.services.alpaca_client.account_service import AccountService
from app.services.alpaca_client.credential_service import CredentialService
from app.services.alpaca_client.factory import AlpacaClientFactory
from app.services.alpaca_client.repository import CredentialRepository

router = APIRouter(prefix="/credentials", tags=["alpaca"])
account_router = APIRouter(prefix="/account", tags=["alpaca"])


def _build_credential_service(db: Session, settings: Settings) -> CredentialService:
    """Cablea repositorio + factory + servicio de credenciales para una request."""
    repository = CredentialRepository(db)
    factory = AlpacaClientFactory(repository, settings)
    return CredentialService(repository, factory)


def _build_account_service(db: Session, settings: Settings) -> AccountService:
    """Cablea repositorio + factory + servicio de cuenta para una request."""
    repository = CredentialRepository(db)
    factory = AlpacaClientFactory(repository, settings)
    return AccountService(repository, factory)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CredentialMetadata,
)
def submit_credentials(
    body: CredentialSubmit,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CredentialMetadata:
    """Valida y almacena las credenciales; responde solo metadatos (R1, R2)."""
    service = _build_credential_service(db, settings)
    return service.store(body.api_key, body.secret)


@router.get("", response_model=CredentialMetadata)
def get_credentials(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CredentialMetadata:
    """Inspecciona los metadatos almacenados; sin exponer el secreto (R6.1/R6.2)."""
    service = _build_credential_service(db, settings)
    return service.inspect()


@router.delete("", response_model=DeletionResult)
def delete_credentials(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeletionResult:
    """Elimina las credenciales almacenadas y confirma el resultado (R6.3/R6.4)."""
    service = _build_credential_service(db, settings)
    return service.delete()


@account_router.get("", response_model=AccountStatus)
def get_account(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AccountStatus:
    """Consulta el estado y saldo de la cuenta paper (R3, R5.3)."""
    service = _build_account_service(db, settings)
    return service.get_account()
