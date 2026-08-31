"""Bot API orchestration domain package (spec 07-bot-api).

This package holds the FastAPI orchestration layer for the trading bot: the bot
state types (:class:`BotState`, :class:`BotStatus`) and the
:class:`BotOrchestrator` that wires and drives the trading pipeline.
"""

from app.services.bot.orchestrator import BotOrchestrator
from app.services.bot.state import BotState, BotStatus

__all__ = ["BotOrchestrator", "BotState", "BotStatus"]
