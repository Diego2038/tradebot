"""Punto de arranque de la API de TradeBot.

Esqueleto inicial. Los routers de cada feature (spec) se montarán aquí a medida
que se implementen: alpaca-client, data-feed, strategy-engine, order-execution,
backtest-engine, risk-manager, bot-api.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import credentials as credentials_api
from app.core.config import get_settings
from app.core.security import EncryptionError
from app.db.base import Base
from app.db.session import engine
from app.services.alpaca_client.barrier import assert_paper_only
from app.services.alpaca_client.errors import (
    AccountQueryError,
    CredentialsRequiredError,
    InvalidCredentialsError,
    PaperOnlyViolationError,
    TransientAlpacaError,
)

# Importar los modelos registra sus tablas en Base.metadata antes de create_all.
import app.db.models  # noqa: F401

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

# Crear las tablas al arranque. En esta fase basta con create_all; una
# herramienta de migraciones puede introducirse en una spec posterior.
Base.metadata.create_all(bind=engine)

# CORS abierto en desarrollo para permitir al frontend Flutter web conectarse.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routers de la capa cliente de Alpaca (spec 01-alpaca-client).
app.include_router(credentials_api.router)
app.include_router(credentials_api.account_router)


def _error_response(status_code: int, error_code: str, detail: str) -> JSONResponse:
    """Construye una respuesta de error estable a partir de textos estáticos.

    Los mensajes provienen SOLO de cadenas fijas: nunca se serializa el
    contenido de la excepción, de modo que ningún secreto (API Key/Secret en
    claro) puede filtrarse a la respuesta ni a los logs (R1.4).
    """
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error_code, "detail": detail},
    )


# Exception handlers: cada error de dominio se mapea a un status HTTP distinto y
# a un ``error_code`` estable, de forma que el frontend pueda distinguir un fallo
# de autenticación (401) de uno transitorio (502) programáticamente (R2.3). Sin
# filtrar secretos en ningún caso (R1.4).
@app.exception_handler(EncryptionError)
def _handle_encryption_error(request: Request, exc: EncryptionError) -> JSONResponse:
    return _error_response(
        503, "encryption_unavailable", "encryption key unavailable or invalid"
    )


@app.exception_handler(InvalidCredentialsError)
def _handle_invalid_credentials(
    request: Request, exc: InvalidCredentialsError
) -> JSONResponse:
    return _error_response(401, "invalid_credentials", "invalid Alpaca credentials")


@app.exception_handler(TransientAlpacaError)
def _handle_transient(request: Request, exc: TransientAlpacaError) -> JSONResponse:
    return _error_response(
        502, "transient_error", "temporary problem reaching Alpaca, try again"
    )


@app.exception_handler(AccountQueryError)
def _handle_account_query(request: Request, exc: AccountQueryError) -> JSONResponse:
    return _error_response(502, "account_query_failed", "account query failed")


@app.exception_handler(CredentialsRequiredError)
def _handle_credentials_required(
    request: Request, exc: CredentialsRequiredError
) -> JSONResponse:
    return _error_response(409, "no_credentials", "no credentials configured")


@app.exception_handler(PaperOnlyViolationError)
def _handle_paper_only(request: Request, exc: PaperOnlyViolationError) -> JSONResponse:
    return _error_response(500, "paper_only_violation", "paper-only barrier violation")


@app.on_event("startup")
def _enforce_paper_only() -> None:
    """Barrera dura: una mala configuración impide arrancar (R5.2)."""
    assert_paper_only(get_settings())


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Health check simple para Docker/compose y para el frontend."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "mode": "paper" if settings.alpaca_paper_only else "LIVE",
        "default_symbol": settings.default_symbol,
    }
