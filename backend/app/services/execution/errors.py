class ExecutionError(Exception):
    """Base for execution-layer domain errors."""


class InvalidLevelError(ExecutionError, ValueError):
    """A Stop-Loss / Take-Profit level is invalid for a long position (R2.2).

    Subclasses ValueError so callers can catch either. Raised when stop_loss >=
    entry_price or take_profit <= entry_price."""
