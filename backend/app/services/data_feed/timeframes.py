"""Supported bar aggregation intervals and mapping to the alpaca-py TimeFrame.

The :class:`Timeframe` enum defines the supported values (R1.4). The
``SUPPORTED_TIMEFRAMES`` set is used by the historical service to validate a
requested timeframe before any Alpaca call. ``to_alpaca_timeframe`` maps a
supported timeframe to the alpaca-py ``TimeFrame`` object using a lazy import so
this module stays decoupled from the SDK and test stubs are not broken at import
time.
"""

from enum import Enum


class Timeframe(str, Enum):
    """Supported bar aggregation intervals (R1.4)."""

    MIN_1 = "1Min"
    MIN_5 = "5Min"
    MIN_15 = "15Min"
    HOUR_1 = "1Hour"
    DAY_1 = "1Day"


SUPPORTED_TIMEFRAMES: frozenset[str] = frozenset(tf.value for tf in Timeframe)


def to_alpaca_timeframe(tf: "Timeframe | str"):
    """Map a :class:`Timeframe` (or its string value) to the alpaca-py TimeFrame.

    Uses a lazy import of ``TimeFrame`` / ``TimeFrameUnit`` inside the function so
    the module does not couple to the SDK at import time and does not break test
    stubs.

    Raises:
        ValueError: if ``tf`` is not one of the supported timeframes.
    """
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    value = tf.value if isinstance(tf, Timeframe) else tf

    mapping = {
        Timeframe.MIN_1.value: (1, TimeFrameUnit.Minute),
        Timeframe.MIN_5.value: (5, TimeFrameUnit.Minute),
        Timeframe.MIN_15.value: (15, TimeFrameUnit.Minute),
        Timeframe.HOUR_1.value: (1, TimeFrameUnit.Hour),
        Timeframe.DAY_1.value: (1, TimeFrameUnit.Day),
    }

    try:
        amount, unit = mapping[value]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe: {value!r}") from exc

    return TimeFrame(amount, unit)
