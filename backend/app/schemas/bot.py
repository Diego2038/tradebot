"""Pydantic schemas for the bot control API (spec 07-bot-api, Task 4).

- :class:`BotStartRequest` -- the ``POST /bot/start`` body; ``mode`` is a
  ``Literal["random", "predictive"]`` so an unknown mode is rejected at the API
  edge with a 422 before reaching the orchestrator (defense in depth for R2.4).
- :class:`BotStatusResponse` -- the output schema mirroring the domain
  :class:`~app.services.bot.state.BotStatus` (R2.6).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class BotStartRequest(BaseModel):
    """Body of ``POST /bot/start``.

    ``mode`` is constrained to the registered strategy names; any other value is
    rejected by FastAPI with a 422 validation error (R2.4).
    """

    mode: Literal["random", "predictive"]


class BotStatusResponse(BaseModel):
    """Response mirroring the domain :class:`BotStatus` (R2.6)."""

    state: str  # "running" | "stopped"
    mode: str
    symbol: str
