# Requirements Document

## Introduction

This spec defines the backtest engine of the TradeBot paper-trading bot. The backtest engine
simulates a trading strategy over historical BTC/USD data to estimate the strategy's
performance before it is run live, even in paper trading. It replays historical bars in
chronological order, applies the strategy step by step, simulates the resulting trades entirely
in memory, and reports summary performance metrics at the end of the run.

This feature depends on two earlier specs through explicit, SDK-independent interfaces and does
**not** talk to Alpaca directly:

- It reuses the exact same `Strategy` interface and `Signal` type defined by spec
  `03-strategy-engine`, so that the behavior observed in a backtest is comparable to the
  behavior of the live strategy engine.
- It consumes historical market data in the single, SDK-independent normalization format of
  spec `02-data-feed`: a `Bar` composed exactly of timestamp, open, high, low, close, and
  volume. The backtest engine receives an already-fetched, ordered sequence of Bar as input and
  performs no Alpaca calls during a run.

The scope is intentionally minimal, matching the same bounded criteria as specs `01`, `02`,
`03`, and `04`: paper trading only, single asset `BTC/USD`, no Alpaca interaction during a
backtest, and only the essential capabilities described below. This feature maps to
`backend/app/services/backtest/`.

## Glossary

- **System**: The backtest engine component implemented by this spec.
- **Strategy**: A component conforming to the common `Strategy` interface defined by spec
  `03-strategy-engine`, which consumes market data and returns a Signal. The System reuses this
  exact interface without modification.
- **Signal**: The output of a Strategy as defined by spec `03-strategy-engine`, carrying an
  action that is exactly one of `BUY`, `SELL`, or `HOLD`, plus a reason and a timestamp.
- **Action**: The decision carried by a Signal, one of `BUY`, `SELL`, or `HOLD`.
- **Bar**: A normalized OHLCV candle from spec `02-data-feed`, composed exactly of timestamp,
  open, high, low, close, and volume.
- **Symbol**: The traded asset, fixed to `BTC/USD` in this phase.
- **Timeframe**: The bar aggregation interval as defined by spec `02-data-feed`, one of `1Min`,
  `5Min`, `15Min`, `1Hour`, `1Day`.
- **Date_Range**: The inclusive start and end timestamps bounding the historical Bar sequence
  replayed in a backtest.
- **Bar_Sequence**: The chronologically ordered sequence of Bar for the Symbol, Timeframe, and
  Date_Range that the System replays during a backtest.
- **Backtest_Request**: The input to a backtest run, composed of the Strategy selected by name,
  the Symbol, the Timeframe, the Date_Range, and an optional random seed.
- **Simulated_Trade**: An in-memory entry or exit derived from a Signal during a backtest, which
  never reaches Alpaca.
- **Backtest_Result**: The output of a backtest run, composed of the summary performance metrics
  and the list of Simulated_Trade.
- **Starting_Equity**: The fixed positive equity with which every backtest run is initialized,
  set to a constant 100000 units of the quote currency and applied identically across all runs.
- **Total_Return**: The relative change of simulated equity from the start to the end of the
  backtest, expressed as a fraction of the starting equity.
- **Trade_Count**: The number of completed round-trip Simulated_Trade (an entry followed by its
  closing exit) executed during the backtest.
- **Win_Rate**: The fraction of completed Simulated_Trade whose realized profit is greater than
  zero, expressed relative to Trade_Count.
- **Max_Drawdown**: The largest observed peak-to-trough decline of simulated equity during the
  backtest, expressed as a fraction of the peak equity.
- **Seed**: The value used to initialize any randomness in a Strategy so that a backtest run is
  reproducible.

## Requirements

### Requirement 1: Run a backtest over historical data

**User Story:** As a user, I want to test a strategy against the past, so that I can decide
whether it is worth letting the strategy operate before running it live.

#### Acceptance Criteria

1. WHEN a Backtest_Request is submitted with a Strategy, a Symbol, a Timeframe, and a Date_Range, THE System SHALL replay the corresponding Bar_Sequence in strictly ascending timestamp order, applying the Strategy to each Bar exactly once and evaluating exactly one Signal per replayed Bar.
2. WHEN the System applies the Strategy at each step, THE System SHALL provide the Strategy with market data in the spec-02 Bar format and receive a Signal whose action is exactly one of `BUY`, `SELL`, or `HOLD`.
3. WHEN a Signal with action `BUY` or `SELL` is produced during replay, THE System SHALL record a Simulated_Trade in memory without performing any call to Alpaca.
4. WHEN a Signal with action `HOLD` is produced during replay, THE System SHALL record no Simulated_Trade for that step.
5. THE System SHALL perform no Alpaca calls at any point during a backtest run.
6. IF the Bar_Sequence for the requested Symbol, Timeframe, and Date_Range is empty, THEN THE System SHALL complete the run and return a Backtest_Result reporting a Trade_Count of zero and a Total_Return of zero.
7. IF the Strategy is requested by a name that is not registered in the spec-03 strategy registry, THEN THE System SHALL raise an error identifying the unregistered Strategy name, SHALL replay no Bar, and SHALL return no Backtest_Result.
8. IF the Date_Range of a Backtest_Request has a start timestamp later than its end timestamp, THEN THE System SHALL raise an error indicating the Date_Range is invalid, SHALL replay no Bar, and SHALL return no Backtest_Result.
9. IF the Strategy returns a Signal whose action is not exactly one of `BUY`, `SELL`, or `HOLD` during replay, THEN THE System SHALL raise an error indicating the action is invalid, SHALL stop the replay, and SHALL return no Backtest_Result.

### Requirement 2: Report result metrics

**User Story:** As a user, I want summary performance metrics at the end of a backtest, so that
I can judge how the strategy performed over the historical period.

#### Acceptance Criteria

1. WHEN a backtest run completes, THE System SHALL return a Backtest_Result reporting exactly the following four metrics: the Total_Return, the Trade_Count, the Win_Rate, and the Max_Drawdown.
2. THE System SHALL initialize every backtest run with a fixed positive starting equity of 100000 units of the quote currency, applied identically across all runs.
3. WHEN a backtest run completes, THE System SHALL compute the Total_Return as the ending simulated equity minus the starting equity, divided by the starting equity, yielding a fraction that is greater than or equal to -1.
4. WHEN a backtest run completes, THE System SHALL compute the Win_Rate as the count of completed Simulated_Trade whose realized profit is strictly greater than zero, divided by the Trade_Count, yielding a fraction in the inclusive range 0 to 1.
5. WHEN a backtest run completes, THE System SHALL compute the Max_Drawdown as the largest peak-to-trough decline of simulated equity observed during the run divided by the peak equity at that peak, yielding a fraction in the inclusive range 0 to 1, and SHALL report a Max_Drawdown of zero when simulated equity never declines from a prior peak.
6. WHEN a backtest run completes, THE System SHALL report each of the Total_Return, the Win_Rate, and the Max_Drawdown rounded to 6 decimal places.
7. IF the Trade_Count is zero, THEN THE System SHALL report a Total_Return of zero, a Win_Rate of zero, and a Max_Drawdown of zero.

### Requirement 3: Consistency with live operation

**User Story:** As a developer, I want the backtest to use the same strategy interface as the
live bot, so that backtest behavior is directly comparable to live behavior.

#### Acceptance Criteria

1. THE System SHALL apply every Strategy exclusively through the `Strategy` interface defined by spec `03-strategy-engine`, SHALL consume that interface without altering its method signatures or its `Signal` output type, and SHALL apply no wrapper or adapter that changes the action carried by a Signal.
2. WHEN a Strategy produces a Signal during replay, THE System SHALL interpret its action using the same observable rules as the live strategy engine, such that a `BUY` or `SELL` action results in a recorded Simulated_Trade and a `HOLD` action results in no recorded Simulated_Trade for that step.
3. WHEN a Strategy is selected by name for a backtest, THE System SHALL resolve it through the same spec-03 strategy registry used by live operation, and SHALL apply the same registered Strategy instance behavior that live operation would resolve for that name.

### Requirement 4: Reproducibility

**User Story:** As a user, I want a backtest to be reproducible, so that the same inputs always
produce the same result.

#### Acceptance Criteria

1. WHEN two backtest runs use the same Bar_Sequence, the same Strategy, and the same Seed, THE System SHALL produce Backtest_Result values that are equal field by field, including identical metric values and an identical ordered sequence of Simulated_Trade.
2. WHERE a Backtest_Request includes a Seed, THE System SHALL initialize any Strategy randomness with that Seed before replaying the Bar_Sequence.
3. WHEN the same Bar_Sequence is replayed with a deterministic Strategy, THE System SHALL produce Backtest_Result values that are equal field by field regardless of whether a Seed is provided.
4. WHEN a backtest is run repeatedly with an identical Backtest_Request, THE System SHALL produce the same Backtest_Result on every run.
5. IF a Backtest_Request selects a randomized Strategy without providing a Seed, THEN THE System SHALL still complete the run and return a valid Backtest_Result, without any guarantee that the result is reproducible across runs.

## Minimum Tests

- A backtest over a small, known dataset produces the expected metrics (Total_Return,
  Trade_Count, Win_Rate, Max_Drawdown).
- A strategy that always returns `HOLD` produces a Trade_Count of zero and a Total_Return of
  zero.
- Reproducibility: the same input plus the same Seed produces an identical Backtest_Result.
- An empty Bar_Sequence completes the run and returns a Trade_Count of zero and a Total_Return
  of zero.
- Selecting a strategy by an unregistered name raises a clear error and runs no backtest.
- The backtest performs no Alpaca calls during a run (verified with a strategy over a static
  in-memory dataset).
- An invalid Date_Range whose start timestamp is later than its end timestamp raises an error
  and runs no backtest (no Bar is replayed and no Backtest_Result is returned).
- A Strategy that returns an out-of-range action (not one of `BUY`, `SELL`, or `HOLD`) raises an
  error, stops the replay, and returns no Backtest_Result.
- The reported Total_Return, Win_Rate, and Max_Drawdown are rounded to 6 decimal places.
- A randomized strategy selected without a Seed still completes the run and returns a valid
  Backtest_Result, with the understanding that the result is not guaranteed to be reproducible
  across runs.
