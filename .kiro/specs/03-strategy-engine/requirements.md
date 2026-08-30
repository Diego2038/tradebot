# Requirements Document

## Introduction

This spec defines the strategy engine for the TradeBot paper-trading bot. The strategy engine
transforms BTC/USD market data into trading signals, where each signal is one of BUY, SELL, or
HOLD. It defines a common, plug-and-play strategy interface and provides at least two
strategies selectable by name: `random`, a reproducible baseline used to sanity-check the
whole pipeline, and `predictive`, which derives decisions from indicators computed over
historical bars (moving-average crossover and/or RSI).

This feature consumes the single, SDK-independent market-data format defined by spec
`02-data-feed`: a `Bar` composed of timestamp, open, high, low, close, and volume, and a
`Quote` composed of timestamp and price. The strategy engine does not talk to Alpaca directly
and does not depend on Alpaca's data shapes. Mode selection is driven by the bot-api (spec
`07-bot-api`) and the frontend (spec `08-web-frontend`). The scope is intentionally minimal:
paper trading only, single asset BTC/USD, and only the essential capabilities described here.

## Glossary

- **System**: The strategy engine component implemented by this spec.
- **Bar**: A normalized OHLCV candle from spec `02-data-feed`, composed exactly of timestamp,
  open, high, low, close, and volume.
- **Quote**: A normalized price datum from spec `02-data-feed`, composed exactly of timestamp
  and price.
- **Market data**: The input consumed by a strategy, expressed in the single spec-02 format as
  a sequence of Bar and/or a Quote.
- **Signal**: The output of a strategy, composed of an action that is exactly one of {BUY,
  SELL, HOLD} plus metadata: a human-readable reason and a timestamp.
- **Action**: The decision carried by a Signal, one of BUY, SELL, or HOLD.
- **Strategy**: A component conforming to the common interface that consumes market data and
  returns a Signal.
- **Strategy registry**: The mapping from a strategy name to its Strategy implementation, used
  to register and select strategies by name.
- **Active mode**: The name of the strategy currently selected to generate signals.
- **SMA**: Simple Moving Average of close prices over a configured period.
- **RSI**: Relative Strength Index computed over close prices, with oversold and overbought
  thresholds.
- **Consumer**: Any component that requests signals from the System, including the bot-api and
  execution.

## Requirements

### Requirement 1: Common strategy interface (plug-and-play)

**User Story:** As a developer, I want a common strategy interface, so that I can add new
strategies without changing the rest of the system.

#### Acceptance Criteria

1. THE System SHALL define a `Strategy` interface that receives market data in the spec-02
   single format, a sequence of Bar and/or a Quote, and returns a Signal.
2. THE System SHALL define a Signal with an action that is exactly one of {BUY, SELL, HOLD},
   plus metadata composed of a human-readable reason and a timestamp.
3. THE System SHALL allow strategies to be registered and selected by name without changes to
   consumers.
4. IF a strategy is requested by a name that is not registered, THEN THE System SHALL raise a
   clear error and SHALL leave the active selection unchanged.
5. THE System SHALL guarantee that every strategy returns a valid Signal whose action is
   exactly one of {BUY, SELL, HOLD}.
6. IF the provided market data is empty or insufficient for the strategy, THEN THE System SHALL
   return a HOLD signal rather than failing.

### Requirement 2: Random strategy

**User Story:** As the bot operator, I want a reproducible random-signal strategy conforming to
the common interface, so that I can sanity-check the whole strategy pipeline end to end before
using predictive strategies.

#### Acceptance Criteria

1. WHEN the active mode is `random`, THE System SHALL emit a signal whose action is exactly one
   of {BUY, SELL, HOLD}.
2. WHEN the active mode is `random`, THE System SHALL choose the action by a random selection
   in which each of BUY, SELL, and HOLD is a possible outcome.
3. WHEN a random signal is emitted, THE System SHALL produce a Signal conforming to the common
   Strategy interface, including the action and the reason and timestamp metadata.
4. WHEN a random signal is emitted, THE System SHALL set the reason metadata to a value
   indicating that the signal was randomly generated.
5. WHILE a seed has been set, THE System SHALL, for the same sequence of invocations, produce
   exactly the same sequence of actions as any other run using that same seed.
6. IF no seed has been set, THEN THE System SHALL generate signals without a reproducibility
   guarantee across distinct runs.

### Requirement 3: Predictive strategy (historical indicators)

**User Story:** As a user, I want a predictive mode based on past data, so that decisions are
not pure chance.

#### Acceptance Criteria

1. WHEN the active mode is `predictive`, THE System SHALL compute indicators over the bars'
   close prices, supporting a moving-average crossover of short SMA versus long SMA and/or RSI.
2. WHEN the short SMA crosses above the long SMA, or the RSI exits the oversold region, THE
   System SHALL emit BUY.
3. WHEN the short SMA crosses below the long SMA, or the RSI enters the overbought region, THE
   System SHALL emit SELL.
4. WHILE no crossover or threshold condition holds, THE System SHALL emit HOLD.
5. THE System SHALL make the indicator periods and the RSI oversold and overbought thresholds
   configurable, with default thresholds of oversold 30 and overbought 70 and periods within
   the range 1 to 500 inclusive.
6. IF there are fewer bars than the largest required indicator window, THEN THE System SHALL
   emit HOLD.
7. WHEN the same input bars are provided, THE System SHALL compute the signal deterministically.
8. WHEN a predictive signal is emitted, THE System SHALL set the reason metadata to indicate
   which indicator or condition triggered the signal.

### Requirement 4: Mode selection

**User Story:** As the bot-api and frontend, I want to query and switch the active strategy by
name, so that the user can choose how the bot decides.

#### Acceptance Criteria

1. THE System SHALL expose which strategy mode is currently active.
2. THE System SHALL allow switching the active mode among the registered names `random` and
   `predictive`.
3. WHEN a valid mode is selected by name, THE System SHALL generate subsequent signals with
   that strategy.
4. IF a name that is not registered is selected, THEN THE System SHALL raise a clear error and
   SHALL leave the active mode unchanged.
5. THE System SHALL have a deterministic default active mode at startup.

## Minimum Tests

- The random strategy with a fixed seed produces a deterministic signal sequence.
- An SMA crossover on a constructed dataset that forces a cross produces the expected BUY or
  SELL signal.
- RSI in the overbought or oversold region produces the expected signal.
- Insufficient bars produce a HOLD signal.
- Selecting an unregistered strategy name raises a clear error and leaves the active mode
  unchanged.
- Every strategy returns a valid Signal whose action is one of {BUY, SELL, HOLD}.
