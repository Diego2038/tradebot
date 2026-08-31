"""Domain errors for the backtest engine (spec 05-backtest-engine)."""


class BacktestError(Exception):
    """Base for backtest-engine domain errors."""


class InvalidDateRangeError(BacktestError, ValueError):
    """The Date_Range start timestamp is later than its end timestamp (R1.8).

    Raised before any bar is replayed; the run returns no Backtest_Result.
    """


class InvalidActionError(BacktestError, ValueError):
    """A Strategy returned a Signal whose action is not exactly one of
    ``BUY``/``SELL``/``HOLD`` during replay (R1.9).

    Raised mid-replay; the replay stops and the run returns no Backtest_Result.
    """
