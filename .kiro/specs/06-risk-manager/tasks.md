# Implementation Plan: 06 Risk Manager

## Overview

Incremental build of the Risk Manager domain package (`backend/app/services/risk/`, Python) that implements the `RiskPort` defined by spec `04-order-execution`. Each task builds on the previous one and ends wired together: first the spec-04 port types are made available (the minimal `services/execution/risk.py` module is created if spec `04` has not implemented it yet, and reused otherwise), then errors and the equity port, then the pure rule helpers, then the `RiskManager` that combines them and exposes the package, and finally a single closing task with the essential Hypothesis property tests.

Testing is kept minimal and folded into the implementation task that produces the code (as inline sub-bullets), rather than living in separate test epics. The only stand-alone testing task is the final property-based test suite, which groups the six essential properties from the design into one task (not one task per property). No `*` marks are used: the closing property task is a required deliverable.

## Tasks

- [ ] 1. Ensure the spec-04 risk port types (create the minimal module only if absent)
  - Dependency note: spec `06` imports `ProposedOrder`, `RiskDecision`, and `RiskPort` from `app.services.execution.risk`, which are **owned by spec `04-order-execution`**. Spec `04` is not implemented on disk yet, so this task unblocks spec `06` (implementable and importable, tests runnable) without waiting for spec `04`.
  - If `backend/app/services/execution/risk.py` does not exist: create `backend/app/services/execution/__init__.py` and `backend/app/services/execution/risk.py` with EXACTLY the port types the spec `04` design defines: `ProposedOrder(symbol: str, side: str, qty: Decimal)` (frozen dataclass), `RiskDecision(approved: bool, reason: str)` (frozen dataclass), and `RiskPort` as a `@runtime_checkable` `Protocol` with `evaluate(proposed_order: ProposedOrder) -> RiskDecision`.
  - If the module already exists (spec `04` implemented it): reuse it as-is; do not duplicate or redefine the types. The path and type names must be identical so spec `04`, when implemented, reuses the SAME module without conflict.
  - Keep the module pure Python (dataclasses / `Protocol` / `Decimal`) with no `alpaca` import.
  - _Requirements: 3.1_

- [ ] 2. Configuration error and equity provider port (`errors.py`, `equity.py`)
  - Create `backend/app/services/risk/__init__.py` and `backend/app/services/risk/errors.py` with `RiskConfigError(ValueError)`, raised at `RiskManager` construction on invalid configuration (never by `evaluate`).
  - Create `backend/app/services/risk/equity.py` with `EquityProvider` as a `@runtime_checkable` `Protocol` exposing `get_equity() -> Decimal | None`, plus the optional `AccountServiceEquityProvider` adapter that wraps spec `01`'s `AccountService` and returns `None` on any failure so the caller degrades to `approved=False` rather than crashing.
  - `equity.py` depends only on the package structure; it does not depend on `rules.py` or `manager.py` and never imports `alpaca`.
  - _Requirements: 2.2, 2.7_

- [ ] 3. Pure rule helpers (`rules.py`)
  - Create `backend/app/services/risk/rules.py` with the stable, secret-free reason constants (`REASON_INVALID_QTY`, `REASON_MAX_LOT`, `REASON_EQUITY_UNAVAILABLE`, `REASON_DAILY_LOSS`).
  - Implement `effective_allowed_max(max_qty, max_equity_pct, equity) -> Decimal | None` (returns `max_qty` when no pct, `min(max_qty, equity * pct / 100)` when equity is available and positive, `None` when equity is required but unavailable/non-positive).
  - Implement `check_lot_size(qty, max_qty, max_equity_pct, equity) -> RiskDecision | None` (invalid `qty <= 0` → invalid-qty block without lot comparison; equity required but unavailable → equity-unavailable block; `qty > effective_allowed_max` → max-lot block; otherwise `None`).
  - Implement `check_daily_loss(accumulated_loss, daily_loss_limit) -> RiskDecision | None` (block when `accumulated_loss >= daily_loss_limit`, else `None`). All helpers are pure and deterministic; import `RiskDecision` from `app.services.execution.risk`.
  - Inline tests: lot within/above the max; `qty <= 0` rejected as invalid without lot comparison; equity required but unavailable rejected; daily-loss boundary (below vs at/above the limit).
  - _Requirements: 1.4, 1.5, 2.3, 2.4, 2.5, 2.6, 2.7_

- [ ] 4. Risk manager and package exports (`manager.py`, `__init__.py`)
  - Create `backend/app/services/risk/manager.py` with `RiskManager(daily_loss_limit, max_qty, max_equity_pct=None, equity_provider=None, publisher=None)` implementing `RiskPort` by importing `ProposedOrder`/`RiskDecision` from `app.services.execution.risk`.
  - Validate configuration at construction, raising `RiskConfigError`: `daily_loss_limit > 0`, `max_qty > 0`, and `max_equity_pct` in `(0, 100]` when set.
  - Maintain private per-UTC-day state (`_current_utc_day`, `_accumulated_loss >= 0`); implement `record_realized_pnl(amount, at=None)` that resets the accumulated loss to zero when the UTC day changes, then applies the amount (losses raise it, profits lower it but never below zero).
  - Implement `evaluate(proposed_order)`: treat every order as an opening order; roll the day if stale; fetch equity via `equity_provider.get_equity()` only when `max_equity_pct` is set; apply rules in fixed order (quantity validity → lot size → daily loss) returning the first blocking `RiskDecision`, else `RiskDecision(approved=True, reason="")`. Deterministic, state-non-mutating, and never raises for a rule violation.
  - Export `RiskManager`, `EquityProvider`, and `RiskConfigError` from `backend/app/services/risk/__init__.py`.
  - Inline tests: invalid config (`daily_loss_limit <= 0`, `max_qty <= 0`, `max_equity_pct` outside `(0, 100]`) raises `RiskConfigError`; `evaluate` approves within limits and blocks per rule; two identical calls return equal decisions (determinism); a UTC-day change resets the accumulated loss; `isinstance(rm, RiskPort)` is `True`.
  - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.8, 2.1, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 5. Essential property-based tests (Hypothesis)
  - Add one Hypothesis test suite grouping the six essential properties from the design (min. 100 iterations each; `EquityProvider` mocked as a stub returning a configured `Decimal | None`); import ONLY `app.services.execution.risk` for the port types so no `alpaca` dependency is pulled in. Tag each test with **Feature: 06-risk-manager, Property {n}: {property text}**.
    - **Property 1: Invalid quantity is rejected as invalid** — **Validates: Requirements 2.6**
    - **Property 2: Lot-size boundary** — **Validates: Requirements 2.2, 2.4, 2.5**
    - **Property 3: An order within all limits is approved** — **Validates: Requirements 1.5, 2.4, 3.3**
    - **Property 4: Daily-loss boundary with UTC-day reset** — **Validates: Requirements 1.4, 1.5, 1.6**
    - **Property 5: `evaluate` is deterministic and never raises on a violation** — **Validates: Requirements 3.5, 3.6**
    - **Property 6: `RiskManager` satisfies the spec-04 `RiskPort`** — **Validates: Requirements 3.1**
  - _Requirements: 1.4, 1.5, 1.6, 2.2, 2.4, 2.5, 2.6, 3.1, 3.3, 3.5, 3.6_

## Notes

- Task 1 guarantees the spec-04 port types are available: it creates the minimal `app/services/execution/risk.py` only if spec `04` has not yet implemented it, and reuses the existing module otherwise, so both specs share the SAME path and types without duplication or conflict.
- Critical example/edge tests are folded into their implementation tasks (tasks 3 and 4); task 5 groups the mandatory property-based tests instead of one task per property.
- No sub-task is marked optional: the property-based test suite (task 5) is a required deliverable.
- Each task references specific requirement clauses for traceability.
- Tests import only `app.services.execution.risk`, keeping the risk package and its tests free of the Alpaca SDK.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2", "3"] },
    { "id": 2, "tasks": ["4"] },
    { "id": 3, "tasks": ["5"] }
  ]
}
```
