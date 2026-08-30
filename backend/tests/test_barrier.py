"""Pruebas de la barrera de paper-trading-only.

Verifican la Property 8: la URL paper pasa sin error; cualquier URL no-paper con
``alpaca_paper_only=True`` lanza ``PaperOnlyViolationError`` (R5.1, R5.2).
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.alpaca_client.barrier import PAPER_BASE_URL, assert_paper_only
from app.services.alpaca_client.errors import PaperOnlyViolationError


def test_paper_url_passes():
    """La base URL paper no lanza, incluso con paper_only activo."""
    settings = Settings(
        alpaca_paper_only=True,
        alpaca_paper_base_url=PAPER_BASE_URL,
    )
    # No debe lanzar.
    assert assert_paper_only(settings) is None


def test_non_paper_url_raises_when_paper_only():
    """Una URL no-paper con paper_only=True lanza PaperOnlyViolationError."""
    settings = Settings(
        alpaca_paper_only=True,
        alpaca_paper_base_url="https://api.alpaca.markets",
    )
    with pytest.raises(PaperOnlyViolationError):
        assert_paper_only(settings)


def test_non_paper_url_allowed_when_paper_only_disabled():
    """Con paper_only=False la barrera no bloquea una URL no-paper."""
    settings = Settings(
        alpaca_paper_only=False,
        alpaca_paper_base_url="https://api.alpaca.markets",
    )
    assert assert_paper_only(settings) is None
