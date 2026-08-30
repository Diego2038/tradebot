"""Domain errors for the data feed.

Only two new errors are introduced here. Missing-credentials and transient
failures are reused from spec ``01-alpaca-client``
(``CredentialsRequiredError`` R1.8, ``TransientAlpacaError`` R1.9).
"""


class DataFeedError(Exception):
    """Base for data feed domain errors."""


class InvalidTimeframeError(DataFeedError):
    """Requested timeframe is not one of the supported values (R1.4)."""


class InvalidRangeError(DataFeedError):
    """Date range is invalid: start after end, or missing/unparseable date (R1.5)."""
