"""Predictive strategy: SMA crossover and/or RSI over close prices (spec 03, R3).

Deterministic on its input bars. Validates its periods and thresholds at
construction and raises ``ValueError`` for invalid configurations, so an invalid
strategy can never produce signals. Thin/empty data yields ``HOLD`` rather than
raising (R3.6, R1.6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from app.services.data_feed.models import Bar, Quote
from app.services.strategies.base import hold
from app.services.strategies.indicators import rsi, sma
from app.services.strategies.signals import Action, Signal

PERIOD_MIN = 1
PERIOD_MAX = 500


class PredictiveStrategy:
    """SMA-crossover and/or RSI strategy over close prices (R3).

    SMA crossover has precedence: if a crossover is detected it decides the
    signal; otherwise the RSI threshold crossings are evaluated; if nothing
    triggers, the result is ``HOLD`` (R3.2, R3.3, R3.4).
    """

    def __init__(
        self,
        short_period: int = 5,
        long_period: int = 20,
        rsi_period: int = 14,
        rsi_oversold: int = 30,
        rsi_overbought: int = 70,
    ) -> None:
        """Validate ranges at construction (R3.5).

        - each period (short, long, rsi) in ``[1, 500]`` inclusive, else ValueError
        - ``short_period < long_period``, else ValueError
        - ``0 < rsi_oversold < rsi_overbought < 100``, else ValueError
        """
        for name, value in (
            ("short_period", short_period),
            ("long_period", long_period),
            ("rsi_period", rsi_period),
        ):
            if not (PERIOD_MIN <= value <= PERIOD_MAX):
                raise ValueError(
                    f"{name} must be in [{PERIOD_MIN}, {PERIOD_MAX}], got {value}"
                )

        if short_period >= long_period:
            raise ValueError(
                f"short_period ({short_period}) must be < long_period ({long_period})"
            )

        if not (0 < rsi_oversold < rsi_overbought < 100):
            raise ValueError(
                "thresholds must satisfy 0 < rsi_oversold < rsi_overbought < 100, "
                f"got oversold={rsi_oversold}, overbought={rsi_overbought}"
            )

        self.short_period = short_period
        self.long_period = long_period
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def generate(self, bars: Sequence[Bar], quote: Quote | None = None) -> Signal:
        """Compute indicators over close prices and emit BUY/SELL/HOLD.

        - Fewer bars than ``max(long_period, rsi_period + 1)`` -> HOLD (R3.6, R1.6).
        - Short SMA crosses above long SMA -> BUY; below -> SELL (SMA has precedence).
        - Else RSI exits oversold -> BUY; enters overbought -> SELL.
        - Otherwise -> HOLD (R3.4).
        - Deterministic on the input bars (R3.7); reason names the triggering
          indicator/condition (R3.8).
        """
        required = max(self.long_period, self.rsi_period + 1)
        # Consistent, deterministic timestamp: use the last bar's timestamp when
        # available, else now(UTC). With enough bars we always have a last bar.
        ts = bars[-1].timestamp if bars else datetime.now(timezone.utc)

        if len(bars) < required:
            return hold(
                f"predictive: insufficient bars ({len(bars)} < {required})", ts=ts
            )

        closes = [b.close for b in bars]

        short_sma = sma(closes, self.short_period)
        long_sma = sma(closes, self.long_period)
        rsi_values = rsi(closes, self.rsi_period)

        # --- SMA crossover (precedence) -------------------------------------
        # The two SMAs have different lengths; align them by the end so that
        # position -1 of each corresponds to the same (latest) bar and -2 to the
        # previous bar. With len(closes) >= long_period there are at least two
        # long-SMA positions, so the alignment below is always valid.
        if len(short_sma) >= 2 and len(long_sma) >= 2:
            short_last = short_sma[-1]
            short_prev = short_sma[-2]
            long_last = long_sma[-1]
            long_prev = long_sma[-2]

            if short_prev <= long_prev and short_last > long_last:
                return Signal(
                    action=Action.BUY,
                    reason="predictive: SMA short crossed above long",
                    timestamp=ts,
                )
            if short_prev >= long_prev and short_last < long_last:
                return Signal(
                    action=Action.SELL,
                    reason="predictive: SMA short crossed below long",
                    timestamp=ts,
                )

        # --- RSI threshold crossings ----------------------------------------
        if rsi_values:
            rsi_last = rsi_values[-1]
            if len(rsi_values) >= 2:
                rsi_prev = rsi_values[-2]
                # Exit oversold: was in the oversold band, now above it -> BUY.
                if rsi_prev <= self.rsi_oversold and rsi_last > self.rsi_oversold:
                    return Signal(
                        action=Action.BUY,
                        reason="predictive: RSI exited oversold",
                        timestamp=ts,
                    )
                # Enter overbought: was below the band, now in it -> SELL.
                if rsi_prev < self.rsi_overbought and rsi_last >= self.rsi_overbought:
                    return Signal(
                        action=Action.SELL,
                        reason="predictive: RSI entered overbought",
                        timestamp=ts,
                    )
            else:
                # Only one RSI position available: compare the latest value to
                # the thresholds directly.
                if rsi_last > self.rsi_oversold and rsi_last < self.rsi_overbought:
                    pass
                elif rsi_last >= self.rsi_overbought:
                    return Signal(
                        action=Action.SELL,
                        reason="predictive: RSI entered overbought",
                        timestamp=ts,
                    )

        # --- Nothing triggered ----------------------------------------------
        return hold("predictive: no signal", ts=ts)
