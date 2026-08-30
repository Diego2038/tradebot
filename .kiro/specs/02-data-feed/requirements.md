# Requirements Document

## Introduction

This spec captures BTC/USD market data from Alpaca for the TradeBot paper-trading bot. It
covers two data paths: historical bars (candles) used by the strategy engine for indicator
computation and backtesting, and real-time streaming used by the running bot to react to
market movements. Both paths deliver data to internal consumers through a single,
SDK-independent normalization format so that no downstream component depends on Alpaca's
specific data shapes.

This feature depends on spec `01-alpaca-client`: it obtains the authenticated Alpaca client
exclusively through that spec's `AlpacaClientFactory`. The scope is intentionally minimal:
paper trading only, single asset BTC/USD, and only the essential capabilities described here.

## Glossary

- **System**: The data feed component implemented by this spec.
- **AlpacaClientFactory**: The single authenticated-client builder provided by spec
  `01-alpaca-client`. It is the only source of an authenticated Alpaca client for the System.
- **Bar**: A normalized OHLCV candle, composed exactly of timestamp, open, high, low, close,
  and volume.
- **Tick/Quote**: A normalized price datum, composed exactly of timestamp and price.
- **Timeframe**: The bar aggregation interval. Supported values are `1Min`, `5Min`, `15Min`,
  `1Hour`, `1Day`.
- **Internal consumer**: Any downstream component that receives market data from the System,
  including the strategy engine, execution, backtest, and the frontend WebSocket bridge.
- **Transient error**: A failure caused by timeout (greater than 10 seconds) or network
  problems reaching Alpaca, distinguishable from validation errors.
- **Active / Stopped**: The running state of the bot that governs streaming subscription
  lifecycle.

## Requirements

### Requirement 1: Historical bars

**User Story:** As the strategy engine, I want historical BTC/USD bars, so that I can compute
indicators and run backtests.

#### Acceptance Criteria

1. WHEN bars are requested for BTC/USD with a valid timeframe and a valid date range, THE
   System SHALL return a list of normalized bars, each exposing timestamp, open, high, low,
   close, and volume.
2. WHEN a bar list is returned, THE System SHALL order the list by timestamp ascending, from
   oldest to newest.
3. IF Alpaca returns no bars for the requested range, THEN THE System SHALL return an empty
   list without raising an error and without interrupting the process.
4. IF the requested timeframe is not one of the supported values (`1Min`, `5Min`, `15Min`,
   `1Hour`, `1Day`), THEN THE System SHALL reject the request with an invalid-timeframe error
   without calling Alpaca.
5. IF the date range is invalid, where the start is after the end or a date is missing or
   unparseable, THEN THE System SHALL reject the request with an invalid-range error without
   calling Alpaca.
6. WHERE more than 10,000 bars are needed to satisfy the request, THE System SHALL paginate
   internally and return the full set as a single ordered list without duplicates.
7. THE System SHALL obtain the authenticated client exclusively through the
   AlpacaClientFactory from spec `01-alpaca-client`.
8. IF no Alpaca credentials are configured, THEN THE System SHALL reject the request with a
   "no credentials configured" error without calling Alpaca.
9. IF the Alpaca call fails by timeout greater than 10 seconds or by network error, THEN THE
   System SHALL respond with a transient error distinguishable from validation errors,
   without interrupting the backend process.

### Requirement 2: Real-time streaming

**User Story:** As the running bot, I want live BTC/USD prices, so that I can react to market
movements.

#### Acceptance Criteria

1. WHEN the bot transitions to active, THE System SHALL subscribe to Alpaca's BTC/USD stream
   using a client obtained from the AlpacaClientFactory.
2. WHILE the stream subscription is active, THE System SHALL emit each received update,
   normalized to the single market-data format defined in Requirement 3, to internal
   consumers including the strategy engine and the frontend WebSocket.
3. IF the streaming connection drops while the bot is active, THEN THE System SHALL retry
   reconnection with exponential backoff starting at 1 second, doubling after each failed
   attempt up to a maximum of 30 seconds between attempts, repeating indefinitely while the
   bot remains active and without terminating the application process.
4. WHEN the bot transitions to stopped, THE System SHALL cancel the stream subscription and
   release the Alpaca connection.

### Requirement 3: Single normalization format

**User Story:** As an internal market-data consumer such as the strategy, execution, or
backtest component, I want each BTC/USD datum in a single SDK-independent format, so that I do
not depend on Alpaca's details or changes.

#### Acceptance Criteria

1. THE System SHALL expose a single SDK-independent bar format composed exactly of timestamp,
   open, high, low, close, and volume, and a single tick/quote format composed exactly of
   timestamp and price.
2. WHEN a raw Alpaca datum is received, whether historical or streaming, THE System SHALL
   convert the datum to the corresponding single format, bar or tick/quote, before delivering
   the datum to any internal consumer.
3. IF a raw Alpaca datum lacks any field required by its single format, THEN THE System SHALL
   discard that datum, SHALL NOT deliver the datum to any consumer, and SHALL log the discard,
   without interrupting processing of subsequent data.

## Minimum Tests

- Normalization of an Alpaca bar to the internal bar format.
- Empty range returns an empty list, using a mocked client.
- Reconnection and backoff retry logic, using a simulated disconnect.
- A malformed datum is discarded without interrupting processing of subsequent data.
- A historical request without configured credentials returns a clear error.
