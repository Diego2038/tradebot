# Requirements Document

## Introduction

This spec defines the **web frontend** of TradeBot: a React + TypeScript (Vite)
single-page application that lets a single user configure Alpaca credentials, control the
trading bot, and observe its actions in **real time**. The frontend is a pure client of the
spec `07-bot-api` surface and owns no domain logic; it renders state and forwards user
intent to the backend over REST and WebSocket.

The frontend operates **exclusively in paper trading mode** (`https://paper-api.alpaca.markets`)
for the single asset `BTC/USD`. No real money is ever at risk in this phase, and the UI must
make the paper-trading context visible at all times.

The frontend consumes the following spec-07 API surface (reused, not redefined here):

- **Credentials (spec 01, reused by spec 07).** `POST /credentials` stores the API Key
  ID/Secret (backend encrypts them); `GET /credentials` returns non-sensitive metadata only
  (whether credentials exist, the last 4 characters of the API Key ID, the last validation
  status); `DELETE /credentials` removes them. The plaintext Secret is never returned.
- **Account (spec 01, reused by spec 07).** `GET /account` returns the paper balance and
  account status.
- **Bot control (spec 07).** `POST /bot/start` accepts a Mode (`random` or `predictive`),
  `POST /bot/stop` stops the bot, `GET /bot/status` returns `{ state, mode, symbol }` where
  `state` is `running` or `stopped`.
- **Real-time feed (spec 07).** `GET /ws/bot` is a WebSocket that broadcasts JSON-serialized
  `OrderEvent`s with fields `event_type` (one of `SUBMITTED`, `FILLED`, `REJECTED`, `ERROR`,
  `RISK_BLOCK`, `STOP_LOSS_CLOSE`, `TAKE_PROFIT_CLOSE`), `symbol`, `side`, `qty`, `price`,
  `order_id`, `reason`, `timestamp`.

The scope is intentionally minimal and matches the bounded criteria of the other specs:
single user, single asset, paper trading only, and only the essential UI capabilities
described below.

## Glossary

- **Frontend**: The React + TypeScript (Vite) single-page application implemented by this
  spec, served as static assets behind nginx in production.
- **Backend**: The FastAPI application defined by spec `07-bot-api`, exposing the REST and
  WebSocket surface the Frontend consumes.
- **API_Client**: The Frontend module that performs REST calls to the Backend.
- **WebSocket_Client**: The Frontend module that maintains the connection to `GET /ws/bot`
  and delivers received events to the UI.
- **Credentials_Form**: The Frontend view where the user submits the Alpaca API Key ID and
  Secret.
- **Credentials_Metadata**: The non-sensitive information returned by `GET /credentials`:
  whether credentials exist, the last 4 characters of the API Key ID, and the last
  validation status.
- **Bot_Controls**: The Frontend view where the user selects the Mode and starts or stops
  the Bot.
- **Mode**: The active strategy name, one of `random` or `predictive`.
- **Bot_Status**: The Backend snapshot `{ state, mode, symbol }` returned by
  `GET /bot/status`, where `state` is `running` or `stopped`.
- **Dashboard**: The Frontend view that renders the live stream of Bot events.
- **Bot_Event**: A JSON-serialized `OrderEvent` received over the WebSocket, with fields
  `event_type`, `symbol`, `side`, `qty`, `price`, `order_id`, `reason`, and `timestamp`.
- **Connection_Status**: The Frontend indicator of the WebSocket state, one of `connected`,
  `connecting`, or `disconnected`.
- **Paper_Trading_Indicator**: The persistent Frontend element that signals the application
  operates in paper trading (no real money).

## Requirements

### Requirement 1: Configure Alpaca credentials

**User Story:** As a user, I want to enter my Alpaca API Key ID and Secret from the web
interface, so that the bot can connect to my paper account.

#### Acceptance Criteria

1. THE Credentials_Form SHALL provide an input field for the API Key ID and a masked input
   field for the API Secret.
2. WHEN the user submits the Credentials_Form, THE API_Client SHALL send the API Key ID and
   Secret to the Backend via `POST /credentials`.
3. THE Frontend SHALL exclude the plaintext API Secret from every rendered view after
   submission.
4. WHEN the Frontend loads, THE API_Client SHALL request Credentials_Metadata via
   `GET /credentials`.
5. WHERE Credentials_Metadata reports that credentials exist, THE Frontend SHALL display the
   last 4 characters of the API Key ID and the last validation status without displaying the
   API Secret.
6. WHEN the user requests removal of stored credentials, THE API_Client SHALL send
   `DELETE /credentials` and THE Frontend SHALL update the displayed Credentials_Metadata to
   reflect that no credentials exist.
7. IF a credentials request to the Backend returns an error, THEN THE Frontend SHALL display
   an error message and SHALL retain the previously displayed Credentials_Metadata.

### Requirement 2: View paper account

**User Story:** As a user, I want to see my paper account balance and status, so that I know
the bot is connected to the correct account.

#### Acceptance Criteria

1. WHEN the Frontend loads and Credentials_Metadata reports that credentials exist, THE
   API_Client SHALL request the account snapshot via `GET /account`.
2. WHEN the account snapshot is received, THE Frontend SHALL display the paper balance and
   the account status.
3. IF the account request returns an error, THEN THE Frontend SHALL display an error message
   indicating the account could not be loaded.

### Requirement 3: Select mode and control the bot

**User Story:** As a user, I want to choose the bot mode and start or stop the bot from the
interface, so that I control when and how the bot operates.

#### Acceptance Criteria

1. THE Bot_Controls SHALL provide a selection between the Mode values `random` and
   `predictive`.
2. WHEN the user starts the bot, THE API_Client SHALL send `POST /bot/start` with the
   selected Mode.
3. WHEN the user stops the bot, THE API_Client SHALL send `POST /bot/stop`.
4. WHEN the Frontend loads, THE API_Client SHALL request the Bot_Status via
   `GET /bot/status`.
5. WHEN a Bot_Status response is received, THE Frontend SHALL display the state (`running` or
   `stopped`), the active Mode, and the symbol.
6. IF `POST /bot/start` returns a `no_credentials` error, THEN THE Frontend SHALL display a
   message directing the user to configure credentials and SHALL keep the displayed state as
   `stopped`.
7. IF `POST /bot/start` returns an `invalid_mode` error, THEN THE Frontend SHALL display an
   error message and SHALL keep the displayed state unchanged.
8. WHILE a start or stop request is in progress, THE Bot_Controls SHALL disable the start and
   stop actions until the request completes.

### Requirement 4: Real-time dashboard

**User Story:** As a user, I want to see the bot's actions live, so that I can follow what it
does without reloading the page.

#### Acceptance Criteria

1. WHEN the Frontend loads, THE WebSocket_Client SHALL open a connection to `GET /ws/bot`.
2. WHEN a Bot_Event is received over the WebSocket, THE Dashboard SHALL render the event
   showing its `event_type`, `symbol`, `side`, `qty`, `price`, and `timestamp`.
3. WHEN multiple Bot_Events are received, THE Dashboard SHALL display them in reverse
   chronological order, with the most recent event first.
4. IF the WebSocket connection is lost, THEN THE WebSocket_Client SHALL attempt to reconnect
   using increasing backoff delays.
5. THE Frontend SHALL display the current Connection_Status (`connected`, `connecting`, or
   `disconnected`) to the user.

### Requirement 5: Paper trading indicator

**User Story:** As a user, I want a clear visual signal that the app runs in paper trading,
so that I never confuse it with real-money operation.

#### Acceptance Criteria

1. THE Frontend SHALL display the Paper_Trading_Indicator on every view.
2. THE Paper_Trading_Indicator SHALL state that the application operates in paper trading
   without real money.

## Minimum Tests

- Component test: the Credentials_Form masks the API Secret input and no rendered view
  exposes the submitted Secret value.
- Component test: given existing Credentials_Metadata, the Frontend shows the last 4
  characters of the API Key ID and the last validation status, and never the Secret.
- Component test: submitting the Credentials_Form triggers a `POST /credentials` call with
  the entered API Key ID and Secret.
- Component test: on load, the Frontend requests `GET /credentials` and, when credentials
  exist, `GET /account`, rendering the paper balance and status.
- Component test: selecting a Mode and starting the bot triggers `POST /bot/start` with the
  selected Mode; stopping triggers `POST /bot/stop`.
- Component test: a `no_credentials` error from `POST /bot/start` shows a configure-credentials
  message and keeps the displayed state as `stopped`.
- Component test: a Bot_Status response renders the state, active Mode, and symbol.
- Component test: a simulated Bot_Event received from the stream is rendered on the Dashboard
  with its `event_type`, `symbol`, `side`, `qty`, `price`, and `timestamp`.
- Component test: multiple simulated Bot_Events render most-recent-first.
- Component test: a simulated WebSocket disconnect updates the Connection_Status to
  `disconnected` and a reconnect attempt is made.
- Component test: the Paper_Trading_Indicator is present and visible on every view.
