"""Barrera dura de paper-trading-only.

Se invoca en el arranque de la aplicación (R5.2, fail fast) y por el factory de
clientes (R5.1, defensa en profundidad), de modo que ningún cliente pueda
construirse jamás contra una base URL no-paper.
"""
from __future__ import annotations

from app.core.config import Settings
from app.services.alpaca_client.errors import PaperOnlyViolationError

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def assert_paper_only(settings: Settings) -> None:
    """Lanza PaperOnlyViolationError si paper-only está activo pero la base URL no es paper.

    Cuando ``settings.alpaca_paper_only`` es ``True`` y
    ``settings.alpaca_paper_base_url`` difiere de :data:`PAPER_BASE_URL`, se
    considera una configuración inválida y se aborta (R5.1, R5.2). Con la URL
    paper correcta la función retorna sin lanzar.
    """
    if settings.alpaca_paper_only and settings.alpaca_paper_base_url != PAPER_BASE_URL:
        raise PaperOnlyViolationError(
            "paper-only barrier violation: configured base URL is not the paper endpoint"
        )
