"""Bot state types for the bot API orchestration layer (spec 07-bot-api).

Defines the :class:`BotState` enum (``running`` / ``stopped``) and the frozen
:class:`BotStatus` snapshot returned by ``GET /bot/status`` (R2.6).
"""

from dataclasses import dataclass
from enum import Enum


class BotState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(frozen=True)
class BotStatus:
    """Snapshot returned by GET /bot/status (R2.6)."""
    state: BotState
    mode: str          # active StrategyEngine mode (e.g. "random")
    symbol: str        # e.g. "BTC/USD"
