# Requirements Document

## Introduction

This spec defines the order execution layer of TradeBot. It translates strategy signals
into orders on the Alpaca **paper trading** account (`https://paper-api.alpaca.markets`)
for the single asset `BTC/USD`, manages automatic Stop-Loss and Take-Profit closes,
guarantees idempotent submission under network retries, and emits domain events describing
everything the bot does. It operates **exclusively in paper trading mode**; no real money is
ever at risk in this phase.

This layer sits downstream of several other specs and depends on them through explicit,
SDK-independent interfaces:

- It obtains the authenticated trading client **exclusively** through
  `AlpacaClientFactory.build_trading_client()` provided by spec `01-alpaca-client`, and it
  reuses that spec's error types `CredentialsRequiredError` (no usable credentials) and
  `TransientAlpacaError` (timeout or network failure).
- It consumes live BTC/USD prices from the data feed of spec `02-data-feed`, reading the
  normalized `Quote.price` value.
- It consults a **Risk Manager through a risk port (interface)**. The Risk Manager itself is
  **not implemented yet**; it belongs to spec `06-risk-manager`. For this spec the System
  depends only on a risk port that, given a proposed order, either approves or rejects it.
  The concrete Risk Manager implementation is provided later by spec `06-risk-manager`.
- It emits domain events to an **event publisher**. This spec only emits events to that
  publisher. Mapping those events onto the frontend WebSocket is the responsibility of spec
  `07-bot-api`, which connects the publisher to the WebSocket.

The scope is intentionally minimal, matching the same bounded criteria as specs `01`, `02`,
and `03`: paper trading only, single asset `BTC/USD`, and only the essential capabilities
described below.

## Glossary

- **System**: The order execution component implemented by this spec.
- **Signal**: A strategy decision produced by spec `03-strategy-engine`, carrying an action
  of `BUY`, `SELL`, or `HOLD`.
- **AlpacaClientFactory**: The single authenticated-client builder provided by spec
  `01-alpaca-client`. The System obtains its trading client only through
  `AlpacaClientFactory.build_trading_client()`.
- **Trading_Client**: The authenticated `alpaca-py` trading client returned by
  `AlpacaClientFactory.build_trading_client()`, configured for paper trading.
- **CredentialsRequiredError**: The error type from spec `01-alpaca-client` raised when no
  usable Alpaca credentials are configured.
- **TransientAlpacaError**: The error type from spec `01-alpaca-client` representing a timeout
  or network failure when calling Alpaca, distinct from an authentication or validation error.
- **Quote**: The normalized live price datum from spec `02-data-feed`, whose `price` field is
  the current BTC/USD price the System evaluates against Stop-Loss and Take-Profit levels.
- **Risk_Port**: The interface (port) through which the System asks whether a proposed order
  is approved or rejected. This spec depends only on the port. The concrete Risk Manager that
  implements this port is provided by spec `06-risk-manager` and is **not implemented yet**.
- **Risk_Manager**: The component behind the Risk_Port that approves or rejects orders,
  implemented later by spec `06-risk-manager`.
- **Stop_Loss**: A configured price level for a long position at which the System
  automatically closes the position to cap losses.
- **Take_Profit**: A configured price level for a long position at which the System
  automatically closes the position to secure gains.
- **Client_Order_Id**: An identifier attached to each Alpaca order, generated deterministically
  from a logical order attempt, used to make submission idempotent under retries.
- **Logical_Order_Attempt**: A single intent to place one order derived from one signal, which
  may involve multiple network retries but corresponds to exactly one Alpaca order.
- **Event_Publisher**: The publisher to which the System emits domain events. Spec
  `07-bot-api` connects this publisher to the frontend WebSocket.
- **Domain_Event**: A structured event describing an order or execution state change (for
  example: order submitted, filled, canceled, rejected/error, stop-loss close, take-profit
  close, or risk block).
- **Submission_Timeout**: The maximum time of 10 seconds the System waits for a confirmed
  Alpaca response for an order submission before treating the attempt as unconfirmed.

## Requirements

### Requirement 1: Order submission

**User Story:** As the bot, I want to send buy/sell orders from a signal, so that I can
execute the strategy on the paper account.

#### Acceptance Criteria

1. WHEN a BUY Signal arrives and the Risk_Manager approves it, THE System SHALL submit a buy
   order for `BTC/USD` via the Trading_Client obtained from
   `AlpacaClientFactory.build_trading_client()`.
2. WHEN a SELL Signal arrives and the Risk_Manager approves it, THE System SHALL submit a sell
   order for `BTC/USD` via the Trading_Client obtained from
   `AlpacaClientFactory.build_trading_client()`.
3. WHEN Alpaca paper accepts a submitted order, THE System SHALL record the result including
   the order id, the order status, the symbol, the quantity, and the side.
4. WHEN the Signal action is HOLD, THE System SHALL submit no order.
5. IF the Risk_Manager rejects the Signal, THEN THE System SHALL submit no order, with reject
   behavior detailed in Requirement 5.
6. IF Alpaca paper rejects the order with a non-authentication API error, THEN THE System
   SHALL capture the error, log the error, emit a Domain_Event indicating the rejection, and
   keep the bot process running.
7. IF the Alpaca call fails by timeout or network error, THEN THE System SHALL treat the
   failure as a TransientAlpacaError, log the error, emit a Domain_Event indicating the
   error, and keep the bot process running.
8. IF no credentials are configured when obtaining the Trading_Client, THEN THE System SHALL
   surface a CredentialsRequiredError and submit no order.

### Requirement 2: Stop-Loss and Take-Profit

**User Story:** As the bot trading long BTC/USD positions on the paper account, I want a
position to close automatically when the live price hits the configured Stop-Loss or
Take-Profit, so that losses are capped and gains secured without manual intervention.

#### Acceptance Criteria

1. WHEN a long `BTC/USD` position is opened and a Stop_Loss level, a Take_Profit level, or
   both are configured, THE System SHALL record those levels associated with that position.
2. IF a Stop_Loss level is greater than or equal to the open price, or a Take_Profit level is
   less than or equal to the open price, THEN THE System SHALL reject registering that level
   with an invalid-level error, SHALL start no automatic tracking for that level, and SHALL
   keep the process running.
3. WHILE a long position with a Stop_Loss level, a Take_Profit level, or both is open, WHEN a
   new live Quote arrives, THE System SHALL evaluate whether the Quote price reached the
   Stop_Loss level or the Take_Profit level.
4. WHEN the live Quote price reaches the Stop_Loss level such that the price is less than or
   equal to the Stop_Loss level, THE System SHALL close that position and emit a stop-loss
   close Domain_Event.
5. WHEN the live Quote price reaches the Take_Profit level such that the price is greater than
   or equal to the Take_Profit level, THE System SHALL close that position and emit a
   take-profit close Domain_Event.
6. IF an open position has neither a Stop_Loss level nor a Take_Profit level configured, THEN
   THE System SHALL trigger no automatic price-based close for that position.

### Requirement 3: Idempotency and consistency

**User Story:** As the bot operator, I want order submission to be idempotent under network
retries, so that a transient connection failure does not create duplicate orders in my paper
account.

#### Acceptance Criteria

1. WHEN the System submits an order to Alpaca, THE System SHALL assign a Client_Order_Id
   generated deterministically from the Logical_Order_Attempt so that the same
   Logical_Order_Attempt always yields the same Client_Order_Id.
2. WHEN a Logical_Order_Attempt is retried after a network failure, THE System SHALL reuse the
   Client_Order_Id from the first submission rather than generate a new Client_Order_Id.
3. IF a retry sends a Client_Order_Id that corresponds to an order already accepted by Alpaca,
   THEN THE System SHALL treat the response as the existing order and SHALL record no second
   order.
4. IF an order submission fails without a confirmed Alpaca response within the
   Submission_Timeout of 10 seconds, THEN THE System SHALL retry up to a maximum of 3 attempts
   using the same Client_Order_Id, and after exhausting the attempts THE System SHALL log an
   error indicating the submission was not confirmed and SHALL create no additional orders.
5. THE System SHALL create no more than one Alpaca order per Logical_Order_Attempt regardless
   of the number of network retries.

### Requirement 4: Real-time domain events

**User Story:** As the frontend observing the bot, I want to receive domain events whenever an
order or execution state changes, so that the UI can show in real time what the bot is doing
without exposing credentials.

#### Acceptance Criteria

1. WHEN an order or execution state changes, including order submitted, order filled, order
   canceled, order rejected or error, stop-loss close, take-profit close, or risk block, THE
   System SHALL emit a Domain_Event to the Event_Publisher including at least the event type,
   the symbol, the side, the quantity, the price when applicable, and the reason.
2. THE System SHALL exclude secrets and credentials from all emitted Domain_Events.
3. IF a subscriber of the Event_Publisher fails or raises while handling a Domain_Event, THEN
   THE System SHALL capture the failure, log the subscriber failure, and continue order
   execution without interruption.
4. THE System SHALL emit Domain_Events only to the Event_Publisher, where mapping those events
   to the frontend WebSocket is the responsibility of spec `07-bot-api`.

### Requirement 5: Risk approval gate

**User Story:** As the bot operator, I want every order gated by the Risk_Manager, so that
orders that violate risk limits are never sent to the paper account.

#### Acceptance Criteria

1. WHEN a BUY or SELL Signal arrives, THE System SHALL request approval from the Risk_Manager
   through the Risk_Port before submitting any order.
2. IF the Risk_Manager approves the proposed order, THEN THE System SHALL proceed with order
   submission as defined in Requirement 1.
3. IF the Risk_Manager rejects the proposed order, THEN THE System SHALL submit no order, log
   the rejection, and emit a risk block Domain_Event including the reason for the rejection.

## Minimum Tests

- **Approved BUY/SELL submission**: an approved BUY or SELL Signal causes the Trading_Client
  to be called with the correct parameters (symbol, side, quantity), using a mocked client.
- **Risk rejection blocks order**: a Signal rejected by the Risk_Manager results in no order
  submission.
- **HOLD blocks order**: a HOLD Signal results in no order submission.
- **Alpaca rejection stays alive**: when Alpaca rejects the order with a non-authentication
  error, an error Domain_Event is emitted and the bot process keeps running.
- **Stop-Loss / Take-Profit trigger**: reaching the simulated Stop_Loss or Take_Profit level
  triggers the position close and emits the corresponding close Domain_Event.
- **Idempotent retry**: a retry using the same Client_Order_Id does not create a second order.
- **Resilient subscribers**: a failing Event_Publisher subscriber does not interrupt order
  execution.
- **No credentials**: obtaining the Trading_Client without configured credentials surfaces a
  CredentialsRequiredError and results in no order submission.
