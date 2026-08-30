# Implementation Plan: 03 Strategy Engine

## Overview

Incremental build of the strategy engine in `backend/app/services/strategies/` (Python). Each task builds on the previous one and ends wired into a usable package: signals and errors first, then the plug-and-play `Strategy` interface, the pure indicators, the two concrete strategies (`random`, `predictive`), and finally the `StrategyEngine` registry with default wiring and package exports. A single closing task adds the essential property-based tests (Hypothesis).

The engine depends only on the spec-02 data models (`Bar`, `Quote`) — no Alpaca, no DB, no numeric libraries. Testing is kept minimal and folded into the implementation task that produces the code as inline sub-bullets; the property-based tests are grouped into one final task rather than one task per property.

## Tasks

- [ ] 1. Signals and domain errors
  - Create `app/services/strategies/signals.py` with `Action(str, Enum)` containing exactly `BUY`, `SELL`, `HOLD`, and a frozen `Signal` dataclass `(action: Action, reason: str, timestamp: datetime)`.
  - Create `app/services/strategies/errors.py` with `StrategyError(Exception)` and `UnknownStrategyError(StrategyError)`.
  - _Requirements: 1.2, 1.4_

- [ ] 2. Strategy interface and HOLD helper
  - Create `app/services/strategies/base.py` with a `@runtime_checkable` `Strategy` `Protocol` exposing `generate(self, bars: Sequence[Bar], quote: Quote | None = None) -> Signal`.
  - Add a `hold(reason: str, ts: datetime | None = None) -> Signal` helper that returns a HOLD `Signal` with a UTC timestamp, used for empty/insufficient data.
  - _Requirements: 1.1, 1.5, 1.6_

- [ ] 3. Pure indicators (SMA and RSI)
  - Create `app/services/strategies/indicators.py` with `sma(values, period) -> list[Decimal]` and `rsi(values, period) -> list[Decimal]`, deterministic and side-effect-free, one value per window position, `[]` on insufficient data.
  - `sma` averages `period` consecutive closes; `rsi` uses average gains/losses (100 when average loss is zero), each value within `[0, 100]`.
  - Inline test: SMA of a constant series equals that constant; RSI values stay within `[0, 100]`; equal inputs produce equal outputs (determinism).
  - _Requirements: 3.1, 3.7_

- [ ] 4. Random strategy
  - Create `app/services/strategies/random_strategy.py` with `RandomStrategy(seed: int | None = None)` holding a private `random.Random(seed)` instance so seeding is reproducible and global RNG state is untouched.
  - `generate` returns a random action in `{BUY, SELL, HOLD}` with a reason indicating randomness; with no bars and no quote it returns `HOLD` via the helper.
  - Inline test: same seed produces the same action sequence; all three actions are reachable with a fixed seed; the reason mentions "random".
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 1.6_

- [ ] 5. Predictive strategy
  - Create `app/services/strategies/predictive_strategy.py` with `PredictiveStrategy(short_period=5, long_period=20, rsi_period=14, rsi_oversold=30, rsi_overbought=70)`.
  - Validate at construction (`ValueError`): each period in `[1, 500]`, `short_period < long_period`, and `0 < rsi_oversold < rsi_overbought < 100`.
  - `generate` computes SMA crossover and/or RSI over close prices: SMA short crossing above long or RSI exiting oversold -> BUY; SMA short crossing below long or RSI entering overbought -> SELL; otherwise HOLD; fewer bars than `max(long_period, rsi_period + 1)` -> HOLD. Deterministic; reason names the triggering indicator/condition.
  - Inline test: a constructed dataset forcing an upward/downward SMA cross produces the expected BUY/SELL; RSI pushed above overbought -> SELL and below oversold -> BUY; insufficient bars -> HOLD; invalid parameters -> `ValueError`.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 1.6_

- [ ] 6. Strategy engine registry, default wiring, and package exports
  - Create `app/services/strategies/registry.py` with `StrategyEngine(default)` exposing `register(name, strategy)`, `get_active_name()`, `set_active(name)` (raises `UnknownStrategyError` and leaves the active mode unchanged when the name is not registered, checking membership before mutating), and `generate(bars, quote=None)` delegating to the active strategy.
  - Add default wiring that registers `random` and `predictive` and sets a deterministic default active mode; export `Action`, `Signal`, `Strategy`, the engine, and the errors from `app/services/strategies/__init__.py`.
  - Inline test: the default active mode is deterministic; switching by name changes the active strategy; an unregistered name raises `UnknownStrategyError` and leaves the active mode unchanged; `generate` delegates to the active strategy.
  - _Requirements: 1.3, 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 7. Essential property-based tests (Hypothesis)
  - Add Hypothesis property tests (min. 100 iterations each), building random `Bar` sequences (including empty and short) and random close-price series. Each test carries the tag `# Feature: 03-strategy-engine, Property {n}: {property text}`.
    - **Property 1: Every strategy always returns a valid Signal** (action in `{BUY, SELL, HOLD}`, non-empty reason, timestamp set) — **Validates: Requirements 1.1, 1.2, 1.5, 2.1, 2.3**
    - **Property 2: Seeded random is reproducible** (two `RandomStrategy(seed)` instances produce identical action sequences) — **Validates: Requirements 2.5**
    - **Property 3: Empty or insufficient data yields HOLD** (both strategies, no error) — **Validates: Requirements 1.6, 3.6**
    - **Property 4: Indicators are pure with known properties** (determinism; SMA of constant = constant; RSI in `[0, 100]`) — **Validates: Requirements 3.1, 3.7**
    - **Property 5: A constructed SMA crossover forces the expected action** (upward cross -> BUY, downward cross -> SELL) — **Validates: Requirements 3.2, 3.3**
    - **Property 6: Unregistered name raises and leaves the active mode unchanged** — **Validates: Requirements 1.4, 4.4**
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 2.1, 2.3, 2.5, 3.1, 3.2, 3.3, 3.6, 3.7, 4.4_

## Notes

- Each task references specific requirement clauses for traceability.
- Critical inline tests are folded into their implementation tasks (3, 4, 5, 6); task 7 groups the six essential property-based tests instead of one task per property.
- Strategies convert thin/empty data into `HOLD` rather than raising; only unregistered names (`UnknownStrategyError`) and invalid `PredictiveStrategy` parameters (`ValueError`) raise.
- The engine has no external dependencies; construct `Bar`/`Quote` directly from spec-02 models in tests — no mocks needed.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "3"] },
    { "id": 1, "tasks": ["2"] },
    { "id": 2, "tasks": ["4", "5"] },
    { "id": 3, "tasks": ["6"] },
    { "id": 4, "tasks": ["7"] }
  ]
}
```
