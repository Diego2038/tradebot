# Requirements Document

## Introduction

This spec defines the **bot API** of TradeBot: the FastAPI layer that orchestrates the whole
system and exposes the REST + WebSocket surface consumed by the React frontend. It ties
together the components already built by the previous specs into a running application that
operates **exclusively in paper trading mode** (`https://paper-api.alpaca.markets`) for the
single asset `BTC/USD`. No real money is ever at risk in this phase.

This layer does not reimplement domain logic; it wires and exposes it:

- **Credentials & account (spec `01-alpaca-client`).** The credential and account endpoints
  (`POST/GET/DELETE /credentials`, `GET /account`) already exist and are mounted in
  `app/main.py`. This spec **reuses** them, not reimplements them: the encryption and
  validation logic is owned by spec `01`.
- **Data feed (spec `02-data-feed`).** The `MarketDataStreamer` (async `start`/`stop`,
  `subscribe(callback)`, backoff reconnection) delivers live `Bar`/`Quote` values.
- **Strategy engine (spec `03-strategy-engine`).** The `StrategyEngine`
  (`build_default_engine`, `get_active_name`, `set_active('random'|'predictive')`,
  `generate(bars, quote) -> Signal`) turns market data into signals.
- **Order execution (spec `04-order-execution`).** The `OrderExecutor.execute_signal(signal)`
  and `PositionManager.on_quote(quote)`, plus the `EventPublisher` (in-memory pub/sub of
  `OrderEvent`).
- **Risk manager (spec `06-risk-manager`).** The real `RiskManager` (implements `RiskPort`)
  is injected into the `OrderExecutor`, **replacing** the interim `AllowAllRiskManager` used
  by spec `04` until now.

The WebSocket endpoint **connects the spec-04 `EventPublisher`** to the frontend: it
subscribes to the publisher and broadcasts each domain event to all connected clients.

The scope is intentionally minimal, matching the same bounded criteria as specs `01`–`06`:
paper trading only, single asset `BTC/USD`, and only the essential capabilities described
below.

## Glossary

- **System**: The bot API component implemented by this spec (the FastAPI app surface and the
  orchestrator that runs the trading pipeline).
- **Pipeline**: The running data flow when the bot is active: `MarketDataStreamer` →
  `StrategyEngine.generate` → `OrderExecutor.execute_signal`, with each `Quote` also fed to
  `PositionManager.on_quote` for Stop-Loss / Take-Profit evaluation.
- **Bot state**: Either `running` (the Pipeline is active) or `stopped` (no Pipeline active).
- **Mode**: The active strategy name, one of `random` or `predictive`, selected on the
  `StrategyEngine`.
- **MarketDataStreamer**: The spec-02 component that streams live `Bar`/`Quote` values and is
  started/stopped by the System.
- **StrategyEngine**: The spec-03 component that holds the active mode and generates a
  `Signal` from market data.
- **OrderExecutor**: The spec-04 component that turns a `Signal` into (at most) one paper
  order, gated by the injected `RiskManager`.
- **PositionManager**: The spec-04 component that closes the open position on Stop-Loss /
  Take-Profit as quotes arrive.
- **RiskManager**: The spec-06 `RiskPort` implementation injected into the `OrderExecutor`,
  replacing the interim `AllowAllRiskManager`.
- **EventPublisher**: The spec-04 in-memory pub/sub of `OrderEvent`. The System subscribes to
  it and bridges events to the WebSocket.
- **OrderEvent**: The spec-04 secret-free domain event (`event_type`, `symbol`, `side`,
  `qty`, `price`, `order_id`, `reason`, `timestamp`) with `event_type` one of `SUBMITTED`,
  `FILLED`, `REJECTED`, `ERROR`, `RISK_BLOCK`, `STOP_LOSS_CLOSE`, `TAKE_PROFIT_CLOSE`.
- **WebSocket client**: A frontend connection to the real-time feed endpoint.
- **CredentialsRequiredError**: The spec-01 error surfaced when no usable credentials are
  configured.

## Requirements

### Requirement 1: Credentials and account endpoints (reused from spec 01)

**User Story:** As the frontend, I want the credentials and account endpoints available, so
that the user can configure Alpaca keys and see the paper balance.

#### Acceptance Criteria

1. THE System SHALL expose to the frontend the spec-01 credential endpoints: `POST
   /credentials` (store encrypted), `GET /credentials` (non-sensitive metadata only: whether
   credentials exist, the last 4 characters of the API Key ID, and the last validation
   status), `DELETE /credentials`, and `GET /account` (paper balance and status).
2. THE System SHALL exclude the plaintext API Key and Secret from every response.
3. THE System SHALL ensure these endpoints are mounted and available on the FastAPI app,
   where the encryption and validation logic is owned by spec `01-alpaca-client` and reused,
   not reimplemented, here.

### Requirement 2: Bot control

**User Story:** As a user, I want to start and stop the bot and choose its mode, so that I
control when and how it operates.

#### Acceptance Criteria

1. THE System SHALL expose `POST /bot/start` accepting a Mode of `random` or `predictive`,
   `POST /bot/stop`, and `GET /bot/status`.
2. WHEN `POST /bot/start` is called with a valid Mode and valid credentials are configured,
   THE System SHALL set the active Mode on the StrategyEngine and start the Pipeline
   (subscribing live-data consumption that feeds the StrategyEngine, the OrderExecutor, and
   the PositionManager) and transition the Bot state to `running`.
3. IF `POST /bot/start` is called and no credentials are configured, THEN THE System SHALL
   respond with a clear error and SHALL NOT start the Pipeline.
4. IF `POST /bot/start` is called with a Mode that is invalid or not registered, THEN THE
   System SHALL respond with a clear error and SHALL NOT change the Bot state.
5. WHEN `POST /bot/stop` is called, THE System SHALL stop the Pipeline, stopping and
   releasing the MarketDataStreamer, and transition the Bot state to `stopped`.
6. WHEN `GET /bot/status` is called, THE System SHALL return the Bot state (`running` or
   `stopped`), the active Mode, and the symbol.
7. THE System SHALL always operate in paper mode and SHALL never place real-money orders.
8. IF `POST /bot/start` is called while the Bot state is already `running`, THEN THE System
   SHALL respond idempotently with a clear indication and SHALL NOT start a second Pipeline.

### Requirement 3: Real-time feed (WebSocket)

**User Story:** As a user, I want to see live what the bot is doing, so that I have full
transparency.

#### Acceptance Criteria

1. THE System SHALL expose a WebSocket endpoint (for example `GET /ws/bot`) to which the
   frontend connects.
2. WHEN a domain event is published to the EventPublisher (a signal, order submitted, fill,
   bot state change, risk block, error, or Stop-Loss/Take-Profit close), THE System SHALL
   broadcast the event, serialized to JSON, to all connected WebSocket clients.
3. THE System SHALL exclude secrets and credentials from every broadcast event.
4. WHEN a WebSocket client disconnects, THE System SHALL remove it from the connection set
   without affecting the other clients and without interrupting the bot.
5. IF sending a broadcast to a WebSocket client fails, THEN THE System SHALL drop that
   connection and SHALL continue broadcasting to the remaining clients.

## Minimum Tests

- `GET /health` responds and reports paper mode (already covered by the skeleton).
- `POST /credentials` stores credentials encrypted and `GET /credentials` does not expose the
  secret (reused from spec `01`; smoke-check that the surface is available).
- `POST /bot/start` without configured credentials returns a clear error and does not start.
- `POST /bot/start` with an invalid/unregistered Mode returns a clear error and leaves the Bot
  state unchanged.
- `POST /bot/start` with a valid Mode and credentials sets the active Mode and transitions the
  Bot state to `running`.
- `POST /bot/stop` transitions the Bot state to `stopped`.
- `GET /bot/status` returns the Bot state, the active Mode, and the symbol.
- A WebSocket client receives an event published to the EventPublisher.
- A broadcast event contains no secrets or credentials.
- A failing or disconnected WebSocket client is dropped without affecting the other clients.
