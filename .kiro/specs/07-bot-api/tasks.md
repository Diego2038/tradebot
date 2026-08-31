# Implementation Plan: 07 Bot API

## Overview

Incremental build of the bot API orchestration layer (`backend/app/services/bot/` +
`backend/app/api/`, Python/FastAPI). Each task builds on the previous ones and ends wired into
the app: the bot state types first, then the `WebSocketHub`, the `BotOrchestrator`, the REST +
WebSocket routers and Pydantic schemas, the `main.py` wiring that injects the real
`RiskManager` (spec 06) and mounts everything, and finally a single closing task with the
essential Hypothesis property tests.

This layer reuses every domain component (specs 01–04, 06) through their existing interfaces
and adds no heavy dependencies (FastAPI already supports WebSockets). Testing is kept minimal
and folded into the implementation tasks as inline sub-bullets; the property-based tests are
grouped into one final task rather than one task per property. All Docker verification
commands are run with `sudo`.

## Tasks

- [ ] 1. Bot state types (`services/bot/state.py`)
  - Create `app/services/bot/__init__.py` and `app/services/bot/state.py` with
    `BotState(str, Enum)` (`RUNNING = "running"`, `STOPPED = "stopped"`) and a frozen
    `BotStatus` dataclass `(state: BotState, mode: str, symbol: str)`.
  - _Requirements: 2.6_

- [ ] 2. WebSocket hub and endpoint (`api/ws.py`)
  - Create `app/api/ws.py` with a `WebSocketHub(publisher)` that subscribes once to the
    spec-04 `EventPublisher`, keeps a set of connected `WebSocket`s, and exposes
    `connect`/`disconnect`/`broadcast`. `broadcast` serializes an `OrderEvent` to a JSON-safe
    dict using only its declared, secret-free fields (Decimals→str, datetime→ISO), sends to
    every client, and drops any client whose send fails; a disconnect removes the client
    without affecting others. Bridge the synchronous publisher callback to async sends via an
    `asyncio.Queue` (or the app loop) so a slow client never stalls event production.
  - Add the `@router.websocket("/ws/bot")` endpoint that registers the client, keeps the
    connection open, and cleans up on disconnect.
  - Inline tests: `broadcast` fans out a JSON event to multiple fake clients; a failing client
    is dropped and the others still receive it; the serialized payload contains no secrets.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 3. Bot orchestrator (`services/bot/orchestrator.py`)
  - Create `app/services/bot/orchestrator.py` with `BotOrchestrator(streamer, engine,
    executor, position_manager, symbol="BTC/USD")` owning the `BotState`.
  - `start(mode)`: verify credentials exist (surface `CredentialsRequiredError` if not, no
    start — R2.3); `engine.set_active(mode)` (an unregistered mode raises
    `UnknownStrategyError`, state unchanged — R2.4); subscribe an internal `on_market_data`
    (rolling bar buffer → `engine.generate(bars, quote)` → `executor.execute_signal(signal)`)
    and `position_manager.on_quote` to the streamer, then `await streamer.start()` and
    transition to `RUNNING`; idempotent if already running (no second pipeline — R2.8).
    Catch/log per-tick exceptions so one bad tick never stops the bot.
  - `stop()`: `await streamer.stop()` (release) and transition to `STOPPED` (R2.5).
  - `status()`: return `BotStatus(state, active mode, symbol)` (R2.6). Export from
    `services/bot/__init__.py`.
  - Inline tests (streamer/engine/executor/position_manager mocked): no credentials → not
    started, state stays stopped; unknown mode → not started, state unchanged; valid start →
    `set_active` called, streamer started once, status running; second start is idempotent;
    stop → streamer stopped, status stopped.
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

- [ ] 4. REST router, schemas, and main.py wiring (`api/bot.py`, `schemas/bot.py`, `main.py`)
  - Create `app/schemas/bot.py` with `BotStartRequest` (`mode: Literal["random","predictive"]`)
    and `BotStatusResponse` (`state`, `mode`, `symbol`).
  - Create `app/api/bot.py` with `POST /bot/start`, `POST /bot/stop`, `GET /bot/status`
    delegating to the `BotOrchestrator`; register exception handlers/mapping so
    `CredentialsRequiredError` → 409 `no_credentials` (R2.3) and `UnknownStrategyError` → 400
    `invalid_mode` (R2.4), reusing the `_error_response` pattern in `main.py`.
  - Wire `app/main.py`: build the shared singletons once — `EventPublisher`,
    `build_default_engine()`, `RiskManager(...)` (spec 06) **injected into**
    `OrderExecutor(factory, risk, publisher)` **in place of `AllowAllRiskManager`**,
    `PositionManager`, `MarketDataStreamer`, `BotOrchestrator`, and `WebSocketHub(publisher)`;
    read risk limits from `Settings` with safe defaults; `app.include_router` the bot and ws
    routers (credentials/account routers from spec 01 stay mounted). Always paper mode (R2.7).
  - Inline tests (FastAPI `TestClient`, Alpaca stubbed, domain mocked/faked, SQLite in-memory
    as in prior router tests): `POST /bot/start` without credentials → 409 `no_credentials`;
    invalid mode → 400/422; valid start → running; `POST /bot/stop` → stopped; `GET
    /bot/status` → state/mode/symbol; `/health` still reports paper mode.
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

- [ ] 5. Essential property-based tests (Hypothesis)
  - Add one Hypothesis test suite grouping the seven essential properties from the design
    (min. 100 iterations each; domain components and Alpaca mocked/stubbed; FastAPI
    `TestClient`/`pytest-asyncio` as needed). Tag each test `# Feature: 07-bot-api, Property
    {n}: {property text}`.
    - **Property 1: Start without credentials never starts and errors clearly** — **Validates: Requirements 2.3**
    - **Property 2: Invalid mode leaves state unchanged** — **Validates: Requirements 2.4**
    - **Property 3: Start is idempotent while running** — **Validates: Requirements 2.2, 2.8**
    - **Property 4: Stop returns to stopped and releases the streamer** — **Validates: Requirements 2.5, 2.6**
    - **Property 5: Every published event reaches all healthy clients** — **Validates: Requirements 3.2**
    - **Property 6: A failing client is dropped without affecting others** — **Validates: Requirements 3.4, 3.5**
    - **Property 7: Broadcast events contain no secrets** — **Validates: Requirements 3.3**
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.8, 3.2, 3.3, 3.4, 3.5_

## Notes

- Each task references specific requirement clauses for traceability.
- R1 (credentials/account endpoints) is satisfied by reusing the spec-01 routers already
  mounted in `main.py`; task 4 only asserts their availability via a smoke test, it does not
  reimplement them.
- The single most important integration step is in task 4: the real `RiskManager` (spec 06) is
  injected into the `OrderExecutor`, replacing the interim `AllowAllRiskManager`.
- Critical inline tests are folded into their implementation tasks (2, 3, 4); task 5 groups
  the mandatory property-based tests instead of one task per property.
- All Docker verification uses `sudo docker ...`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["3"] },
    { "id": 2, "tasks": ["4"] },
    { "id": 3, "tasks": ["5"] }
  ]
}
```
