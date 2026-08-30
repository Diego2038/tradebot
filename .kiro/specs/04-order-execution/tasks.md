# Implementation Plan: 04 Order Execution

## Overview

Incremental build of the order execution layer in `backend/app/services/execution/` (Python). Each task builds on the previous ones and ends wired into a usable package: domain events and the in-memory publisher, the risk port with a pass-through default, the deterministic idempotency key and order-request builder, the execution errors, the SL/TP position manager, and finally the `OrderExecutor` that ties signal → risk gate → submit → record → events, exported from `__init__.py`. A single closing task adds the essential property-based tests (Hypothesis).

The layer reuses spec-01 (`AlpacaClientFactory`, `CredentialsRequiredError`, `TransientAlpacaError`), spec-02 (`Quote`), and spec-03 (`Signal`, `Action`) through explicit interfaces; the real Risk Manager arrives later in spec 06. Alpaca is never constructed directly — always via `AlpacaClientFactory.build_trading_client()`. Testing is kept minimal and folded into the implementation tasks as inline sub-bullets; the property-based tests are grouped into one final task rather than one task per property.

## Tasks

- [ ] 1. Domain events and in-memory publisher
  - Create `app/services/execution/events.py` with `EventType(str, Enum)` containing exactly `SUBMITTED`, `FILLED`, `REJECTED`, `ERROR`, `RISK_BLOCK`, `STOP_LOSS_CLOSE`, `TAKE_PROFIT_CLOSE`, and a frozen `OrderEvent` dataclass `(event_type, symbol, side=None, qty=None, price=None, order_id=None, reason="", timestamp=<utc now>)` carrying only non-sensitive fields.
  - Add an in-memory `EventPublisher` with `subscribe`, `unsubscribe`, and `publish`; `publish` fans out over a copy of the subscriber list, wraps each callback in `try/except`, logs a subscriber failure (without secrets), and continues so the caller is never interrupted.
  - Inline test: an event fans out to several subscribers; a subscriber that raises does not interrupt `publish` and the remaining subscribers still receive the event.
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 2. Risk port and pass-through manager
  - Create `app/services/execution/risk.py` with frozen `ProposedOrder` `(symbol, side, qty)` and frozen `RiskDecision` `(approved, reason="")` dataclasses.
  - Add a `@runtime_checkable` `RiskPort` `Protocol` exposing `evaluate(self, proposed_order: ProposedOrder) -> RiskDecision`, and an `AllowAllRiskManager` pass-through that approves every proposed order (the real implementation is provided later by spec 06).
  - _Requirements: 5.1, 5.2_

- [ ] 3. Deterministic idempotency key and order-request builder
  - Create `app/services/execution/orders.py` with `make_client_order_id(symbol, side, attempt_key) -> str`, a pure function deriving a deterministic id from the logical attempt via a stable hash (within Alpaca's length limit) so equal inputs yield an equal id and retries reuse it.
  - Add `build_market_order_request(symbol, side, qty, client_order_id)` using lazy imports of `alpaca.trading.requests.MarketOrderRequest` and `alpaca.trading.enums` (`OrderSide`, `TimeInForce`), mapping side `"buy"`/`"sell"` and attaching the `client_order_id`.
  - Inline test: `make_client_order_id` is deterministic (same input → same id; different input → different id).
  - _Requirements: 3.1, 3.2_

- [ ] 4. Execution errors
  - Create `app/services/execution/errors.py` with `ExecutionError(Exception)` as the base and `InvalidLevelError(ExecutionError, ValueError)` for an invalid Stop-Loss / Take-Profit level on a long position (subclasses `ValueError` so callers can catch either).
  - _Requirements: 2.2_

- [ ] 5. Position manager (Stop-Loss / Take-Profit)
  - Create `app/services/execution/positions.py` with an internal `Position` dataclass `(symbol, side, qty, entry_price, stop_loss=None, take_profit=None)` and a `PositionManager(factory, publisher)`.
  - Implement `open_position(symbol, side, qty, entry_price, stop_loss=None, take_profit=None)` validating `stop_loss < entry_price < take_profit`; an invalid level raises `InvalidLevelError`, starts no tracking for that level, and keeps the process running.
  - Implement `on_quote(quote)`: `price <= stop_loss` closes the position and publishes `STOP_LOSS_CLOSE`; `price >= take_profit` closes and publishes `TAKE_PROFIT_CLOSE`; neither level configured is a no-op. Closing uses `factory.build_trading_client()`.
  - Inline test: a Stop-Loss hit closes and emits the event; a Take-Profit hit closes and emits the event; no levels means no close; an invalid level raises `InvalidLevelError`.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [ ] 6. Order executor and package exports
  - Create `app/services/execution/executor.py` with `OrderExecutor(factory, risk, publisher, symbol="BTC/USD", qty=Decimal("0.001"))` and `execute_signal(signal) -> OrderEvent | None`.
  - HOLD returns `None` and submits no order; BUY/SELL calls `risk.evaluate(proposed_order)` first — a rejection submits no order and publishes `RISK_BLOCK` with the reason; an approval computes the deterministic `client_order_id`, builds the request, obtains the client via `factory.build_trading_client()`, and submits with retries (max 3, 10s timeout, same id) without duplicating.
  - Record `(id, status, symbol, qty, side)` and publish `SUBMITTED` then `FILLED`; a non-auth API rejection publishes `REJECTED` and stays alive; a timeout/network failure is treated as `TransientAlpacaError` and after exhaustion publishes `ERROR` and stays alive; a response whose `client_order_id` is already accepted is treated as the existing order with no second order; missing credentials propagate `CredentialsRequiredError`. Export the public symbols from `app/services/execution/__init__.py`.
  - Inline test (Alpaca mocked): HOLD sends nothing; an approved BUY/SELL calls `submit_order` with the correct parameters; a risk rejection sends no order and emits `RISK_BLOCK`; missing credentials raise `CredentialsRequiredError` and never call `submit_order`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 3.3, 3.4, 3.5, 5.1, 5.2, 5.3_

- [ ] 7. Essential property-based tests (Hypothesis)
  - Add Hypothesis property tests (min. 100 iterations each), stubbing the `alpaca` package via `sys.modules` (as in specs 01/02) and patching `AlpacaClientFactory.build_trading_client` to return a fake client. Generators build random `Signal`s, random `Quote` prices, and random SL/TP levels. Each test carries the tag `# Feature: 04-order-execution, Property {n}: {property text}`.
    - **Property 1: Approved BUY/SELL submits exactly one order and records it** (`evaluate` precedes one `submit_order` with matching side/symbol/qty; result records id/status/symbol/qty/side) — **Validates: Requirements 1.1, 1.2, 1.3, 5.1, 5.2**
    - **Property 2: HOLD never submits an order** (`submit_order` never called, returns `None`) — **Validates: Requirements 1.4**
    - **Property 3: A risk-rejected signal never submits and emits RISK_BLOCK** (no `submit_order`, exactly one `RISK_BLOCK` with reason) — **Validates: Requirements 1.5, 5.1, 5.3**
    - **Property 4: Deterministic id and idempotent retries create no duplicate order** (equal inputs → equal id; N transient failures → ≤3 attempts, same id, one recorded order) — **Validates: Requirements 3.1, 3.2, 3.4, 3.5**
    - **Property 5: SL/TP thresholds close with the correct event, and no levels means no close** (price ≤ SL → `STOP_LOSS_CLOSE`; price ≥ TP → `TAKE_PROFIT_CLOSE`; no levels → never closes) — **Validates: Requirements 2.3, 2.4, 2.5, 2.6**
    - **Property 6: A failing subscriber never interrupts execution** (others still invoked, `publish` returns normally) — **Validates: Requirements 4.3**
    - **Property 7: No emitted event contains secrets or credentials** (no API key/secret/credential substrings in any `OrderEvent`) — **Validates: Requirements 4.2**
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.4, 3.5, 4.2, 4.3, 5.1, 5.2, 5.3_

## Notes

- Each task references specific requirement clauses for traceability.
- Critical inline tests are folded into their implementation tasks (1, 3, 5, 6); task 7 groups the seven essential property-based tests instead of one task per property.
- The layer never constructs an Alpaca client directly — both services use `AlpacaClientFactory.build_trading_client()`. Only `CredentialsRequiredError` propagates; non-auth rejections and transient failures become events and keep the bot alive.
- Property/unit tests mock Alpaca via `sys.modules` and patch the factory, keeping tests fast and network-free; `RiskPort` and `EventPublisher` are trivial to fake/use in-memory.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2", "3", "4"] },
    { "id": 1, "tasks": ["5", "6"] },
    { "id": 2, "tasks": ["7"] }
  ]
}
```
