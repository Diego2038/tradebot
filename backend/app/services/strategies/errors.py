"""Domain errors for the strategy engine (spec 03-strategy-engine)."""


class StrategyError(Exception):
    """Base for strategy engine domain errors."""


class UnknownStrategyError(StrategyError):
    """A strategy was requested by a name that is not registered (R1.4, R4.4)."""
