# Implementation Plan: 05 Backtest Engine

## Overview

Incremental build of the backtest engine in `backend/app/services/backtest/` (Python). Each task builds on the previous one and ends wired into a usable package: domain errors and constants first, then the data models (`BacktestRequest`, `SimulatedTrade`, `BacktestResult`), the pure metrics functions, the `BacktestEngine.run` replay loop, and finally package exports. A single closing task adds the essential property-based tests (Hypothesis).

The engine depends only on the spec-02 `Bar` and on the spec-03 `StrategyEngine`/`Strategy`/`Signal`/`Action`/`UnknownStrategyError` — no Alpaca, no DB, and no numeric libraries (money math is hand-rolled over `Decimal`). It performs no I/O and no network calls: `run` receives the ordered `Bar` sequence as an argument and simulates trades entirely in memory. Testing is kept minimal and folded into the implementation tasks that produce the code as inline sub-bullets; the property-based tests are grouped into one final task rather than one task per property.

## Tasks

- [x] 1. Domain errors and constants
  - Create `app/services/backtest/errors.py` with `BacktestError(Exception)`, `InvalidDateRangeError(BacktestError, ValueError)` (Date_Range start later than end), and `InvalidActionError(BacktestError, ValueError)` (Signal action not exactly one of `BUY`/`SELL`/`HOLD`).
  - Create `app/services/backtest/constants.py` with `STARTING_EQUITY: Decimal = Decimal("100000")` and `METRIC_DECIMALS: int = 6`.
  - _Requirements: 1.7, 1.8, 1.9, 2.2, 2.6_

- [x] 2. Data models
  - Create `app/services/backtest/models.py` with three frozen dataclasses.
  - `BacktestRequest(strategy_name: str, symbol: str = "BTC/USD", timeframe: str = "1Min", start: datetime | None = None, end: datetime | None = None, seed: int | None = None)` — carries run configuration only; the `Bar` sequence is passed separately to `run`.
  - `SimulatedTrade(side: str, qty: Decimal, price: Decimal, timestamp: datetime, reason: str = "", realized_profit: Decimal | None = None)` — an in-memory entry/exit derived from a Signal; `realized_profit` set only on the closing exit of a round trip.
  - `BacktestResult(total_return: Decimal, trade_count: int, win_rate: Decimal, max_drawdown: Decimal, trades: list[SimulatedTrade])` — reports exactly the four metrics plus the ordered trades.
  - _Requirements: 1.1, 1.3, 2.1_

- [x] 3. Pure metrics module
  - Create `app/services/backtest/metrics.py` with three deterministic, side-effect-free functions over `Decimal`, each rounded to `METRIC_DECIMALS`.
  - `total_return(start_equity, end_equity) -> Decimal` returns `(end_equity - start_equity) / start_equity`, always `>= -1` for a positive start equity (precondition `start_equity > 0`).
  - `win_rate(realized_profits: Sequence[Decimal]) -> Decimal` returns the fraction of profits strictly `> 0` over the count, in `[0, 1]`, and `Decimal("0")` for an empty sequence.
  - `max_drawdown(equity_curve: Sequence[Decimal]) -> Decimal` tracks the running peak and returns the maximum `(peak - value) / peak`, in `[0, 1]`, and `Decimal("0")` when equity never declines from a prior peak or the curve is empty.
  - Inline test: `total_return` matches its formula and is rounded to 6 dp; `win_rate` of an all-positive list is `1`, of an empty list is `0`, and stays within `[0, 1]`; `max_drawdown` of a non-decreasing curve is `0` and of a known peak-to-trough curve equals the expected fraction within `[0, 1]`.
  - _Requirements: 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 4. Backtest engine replay loop
  - Create `app/services/backtest/engine.py` with `BacktestEngine(strategy_engine: StrategyEngine, qty: Decimal = Decimal("0.001"))` wired to the shared spec-03 registry, and `run(request: BacktestRequest, bars: Sequence[Bar]) -> BacktestResult`.
  - Validate the Date_Range before any replay: when `request.start` and `request.end` are both set and `request.start > request.end`, raise `InvalidDateRangeError`, replay no bar, return no result.
  - Resolve the strategy by `request.strategy_name` through the spec-03 `StrategyEngine`; an unregistered name propagates `UnknownStrategyError` before replay begins, replaying no bar and returning no result. When `request.seed` is set, initialize the resolved strategy's randomness with it before replay.
  - Empty `bars` -> complete immediately with `BacktestResult(total_return=0, trade_count=0, win_rate=0, max_drawdown=0, trades=[])`.
  - Sort bars into strictly ascending timestamp order and replay them, calling the strategy exactly once per bar with the history up to and including that bar: action not in `{BUY, SELL, HOLD}` -> raise `InvalidActionError` and stop the replay with no result; `BUY`/`SELL` -> record a `SimulatedTrade` in memory and update simulated equity with no Alpaca call; `HOLD` -> record no trade.
  - Compute `total_return`, `win_rate`, and `max_drawdown` over the equity curve / completed round trips via the metrics module (rounded to 6 dp), pinning all three to zero when `trade_count == 0`, and return `BacktestResult` with the four metrics and the ordered trades. Add no randomness of the engine's own.
  - Inline test: a small known dataset with a scripted strategy yields the expected `Total_Return`/`Trade_Count`/`Win_Rate`/`Max_Drawdown`; a HOLD-only strategy yields `trade_count == 0` and `total_return == 0`; empty bars complete with zeros; `start > end` raises `InvalidDateRangeError`; an unregistered name raises `UnknownStrategyError` with the strategy never invoked; a scripted out-of-range action raises `InvalidActionError` and stops the replay; the same request + seed run twice yields a field-by-field equal result.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 5. Package exports
  - Populate `app/services/backtest/__init__.py` to export `BacktestRequest`, `SimulatedTrade`, `BacktestResult`, `BacktestEngine`, the errors (`BacktestError`, `InvalidDateRangeError`, `InvalidActionError`), and the constants (`STARTING_EQUITY`, `METRIC_DECIMALS`), so callers import from the package root.
  - _Requirements: 2.1_

- [x] 6. Essential property-based tests (Hypothesis)
  - Add Hypothesis property tests (min. 100 iterations each), building random `Bar` sequences (including empty and single-bar; strictly increasing timestamps; positive `Decimal` OHLCV), random equity curves and realized-profit lists for the metric functions, and random seeds. Construct `Bar`s directly from spec-02 models and register real/scripted strategies in a spec-03 `StrategyEngine`; no mocks needed since the engine performs no Alpaca calls. Each test carries the tag `# Feature: 05-backtest-engine, Property {n}: {property text}`.
    - **Property 1: Every completed run returns a valid Backtest_Result with in-range metrics** (`total_return >= -1`, `win_rate ∈ [0, 1]`, `max_drawdown ∈ [0, 1]`, `trade_count >= 0`) — **Validates: Requirements 2.1, 2.3, 2.4, 2.5**
    - **Property 2: Signal-to-trade correspondence during replay, with no Alpaca calls** (scripted strategy with a known action per bar + spy: one call per bar in strictly ascending order, a `SimulatedTrade` for exactly the `BUY`/`SELL` steps and none for `HOLD`, no `alpaca.*` access) — **Validates: Requirements 1.1, 1.3, 1.4, 1.5, 3.2**
    - **Property 3: Metrics are computed correctly and rounded to 6 decimals** (random start/end equity, equity curves, and profit lists match their defining formulas rounded to 6 dp; any zero-trade / HOLD-only run yields `total_return`, `win_rate`, `max_drawdown` all zero) — **Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7**
    - **Property 4: An empty bar sequence completes with zero trades and zero return** (registered strategy over empty bars completes without error, `trade_count == 0`, `total_return == 0`) — **Validates: Requirements 1.6**
    - **Property 5: Reproducibility of results** (same bars + strategy + seed -> field-by-field equal result including identical ordered trades; a deterministic strategy -> equal result regardless of/without a seed) — **Validates: Requirements 4.1, 4.3, 4.4**
    - **Property 6: Invalid request or out-of-range action raises and returns no result** (`start > end` -> `InvalidDateRangeError` with no bar replayed; unregistered name -> `UnknownStrategyError` with no bar replayed; out-of-range action mid-replay -> `InvalidActionError` stopping the replay; no `BacktestResult` in any case) — **Validates: Requirements 1.7, 1.8, 1.9**
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.1, 2.3, 2.4, 2.5, 2.6, 2.7, 3.2, 4.1, 4.3, 4.4_

## Notes

- Each task references specific requirement clauses for traceability.
- Critical inline tests are folded into their implementation tasks (3, 4); task 6 groups the six essential property-based tests instead of one task per property.
- The engine separates the degenerate-but-valid case (empty bars / zero trades -> a completed result pinned to zeros) from hard-stop errors: `InvalidDateRangeError` and `UnknownStrategyError` (reused from spec 03) are raised before any replay, and `InvalidActionError` stops the replay mid-run; a run either returns a complete `BacktestResult` or raises.
- The engine has no external dependencies and performs no Alpaca calls; construct `Bar` directly from spec-02 models and register strategies in a spec-03 `StrategyEngine` in tests — no mocks needed. All money math uses `Decimal`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2", "3"] },
    { "id": 2, "tasks": ["4"] },
    { "id": 3, "tasks": ["5"] },
    { "id": 4, "tasks": ["6"] }
  ]
}
```
