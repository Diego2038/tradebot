"""Constants for the backtest engine (spec 05-backtest-engine)."""

from decimal import Decimal

# Fixed positive equity every run starts from, applied identically across all runs (R2.2).
STARTING_EQUITY: Decimal = Decimal("100000")

# Total_Return, Win_Rate, and Max_Drawdown are reported rounded to this many decimals (R2.6).
METRIC_DECIMALS: int = 6
