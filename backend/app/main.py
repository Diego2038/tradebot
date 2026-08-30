"""Punto de arranque de la API de TradeBot.

Esqueleto inicial. Los routers de cada feature (spec) se montarán aquí a medida
que se implementen: alpaca-client, data-feed, strategy-engine, order-execution,
backtest-engine, risk-manager, bot-api.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

# CORS abierto en desarrollo para permitir al frontend Flutter web conectarse.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Health check simple para Docker/compose y para el frontend."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "mode": "paper" if settings.alpaca_paper_only else "LIVE",
        "default_symbol": settings.default_symbol,
    }
