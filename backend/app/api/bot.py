"""REST router for bot control (spec 07-bot-api, Task 4).

Exposes the thin bot-control surface that delegates to the shared
:class:`~app.services.bot.orchestrator.BotOrchestrator` (R2.1):

- ``POST /bot/start`` -- start the pipeline in a mode (R2.2). A missing credential
  set surfaces :class:`CredentialsRequiredError` (mapped to ``409 no_credentials``
  by the app-level handler, R2.3); an unregistered mode surfaces
  :class:`UnknownStrategyError` (mapped to ``400 invalid_mode``, R2.4); a mode
  outside the ``Literal`` is rejected by FastAPI with ``422`` before reaching the
  orchestrator (R2.4). Starting while running is idempotent (R2.8).
- ``POST /bot/stop`` -- stop the pipeline and return the resulting status (R2.5).
- ``GET /bot/status`` -- the current bot status (R2.6).

The router is deliberately thin: all lifecycle/state logic lives in the
orchestrator. The orchestrator is read defensively from
``request.app.state.bot_orchestrator`` (wired once at startup in ``main.py``), so
domain errors propagate to the app-level exception handlers rather than being
mapped here — keeping error mapping in a single place (``main.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas.bot import BotStartRequest, BotStatusResponse
from app.services.bot.orchestrator import BotOrchestrator

router = APIRouter(prefix="/bot", tags=["bot"])


def _get_orchestrator(request: Request) -> BotOrchestrator:
    """Return the shared :class:`BotOrchestrator` from ``app.state``.

    Wired once at startup in ``main.py``. Read defensively so a misconfigured app
    fails with a clear error instead of an ``AttributeError``.
    """
    orchestrator = getattr(request.app.state, "bot_orchestrator", None)
    if orchestrator is None:  # pragma: no cover - defensive; always wired in main
        raise RuntimeError("bot orchestrator is not configured")
    return orchestrator


@router.post("/start", response_model=BotStatusResponse)
async def start_bot(body: BotStartRequest, request: Request) -> BotStatusResponse:
    """Start the bot in the requested mode (R2.1, R2.2).

    Delegates to the orchestrator. ``CredentialsRequiredError`` (R2.3) and
    ``UnknownStrategyError`` (R2.4) propagate to the app-level handlers, which map
    them to ``409 no_credentials`` and ``400 invalid_mode`` respectively. Starting
    while already running is idempotent (R2.8).
    """
    orchestrator = _get_orchestrator(request)
    status = await orchestrator.start(body.mode)
    return BotStatusResponse(
        state=status.state.value, mode=status.mode, symbol=status.symbol
    )


@router.post("/stop", response_model=BotStatusResponse)
async def stop_bot(request: Request) -> BotStatusResponse:
    """Stop the bot and return the resulting status (R2.5)."""
    orchestrator = _get_orchestrator(request)
    status = await orchestrator.stop()
    return BotStatusResponse(
        state=status.state.value, mode=status.mode, symbol=status.symbol
    )


@router.get("/status", response_model=BotStatusResponse)
def bot_status(request: Request) -> BotStatusResponse:
    """Return the current bot status (R2.6)."""
    orchestrator = _get_orchestrator(request)
    status = orchestrator.status()
    return BotStatusResponse(
        state=status.state.value, mode=status.mode, symbol=status.symbol
    )
