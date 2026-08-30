# Implementation Plan

## Overview

Incremental implementation of the BTC/USD data feed (`services/data_feed/`) on top of spec
`01-alpaca-client`. The single normalization format comes first, followed by the normalizer
and supporting types, the factory extension for crypto data clients, the historical service,
the streamer, an optional HTTP router, and a final grouped property-test task. Each task
builds on the previous ones and ends wired into the backend. Essential example tests live
inline as sub-bullets; the exhaustive property suite (Hypothesis) is a single final task.

Implementation language: **Python** (as used throughout the design).

## Tasks

- [x] 1. Define the single normalization format (`services/data_feed/models.py`)
  - Create `services/data_feed/__init__.py` and `models.py`.
  - Implement `Bar` as a `@dataclass(frozen=True)` with exactly `timestamp: datetime`,
    `open/high/low/close/volume: Decimal`.
  - Implement `Quote` as a `@dataclass(frozen=True)` with exactly `timestamp: datetime`,
    `price: Decimal`.
  - _Requirements: 3.1_

- [x] 2. Implement normalizer, timeframes, and domain errors
  - [x] 2.1 Implement `timeframes.py` and `errors.py`
    - `Timeframe(str, Enum)` with `1Min/5Min/15Min/1Hour/1Day`, `SUPPORTED_TIMEFRAMES`
      frozenset, and `to_alpaca_timeframe(tf)` mapping to the alpaca-py TimeFrame.
    - `errors.py`: `DataFeedError` base, `InvalidTimeframeError`, `InvalidRangeError`.
    - _Requirements: 1.4, 1.5_

  - [x] 2.2 Implement `Normalizer` (`normalizer.py`)
    - `from_alpaca_bar(raw) -> Bar | None` and `from_alpaca_quote(raw) -> Quote | None`,
      reading each required field defensively, returning `None` on any missing/unparseable
      field, converting numbers to `Decimal` and timestamps to UTC-aware `datetime`.
    - Log the discard (symbol + reason, no secrets) when returning `None`.
    - Inline tests: a representative Alpaca bar normalizes to the correct `Bar`; a bar
      missing a required field returns `None` and is logged.
    - _Requirements: 3.2, 3.3_

- [x] 3. Extend `AlpacaClientFactory` with crypto data builders
  - Add `build_crypto_data_client()` and `build_crypto_data_stream()` to
    `services/alpaca_client/factory.py`, reusing the decrypted credentials and applying the
    existing `assert_paper_only` barrier; raise the reused `CredentialsRequiredError` when no
    credentials are configured.
  - Inline test: builders enforce paper-only and raise `CredentialsRequiredError` with an
    empty credential store (no client constructed).
  - _Requirements: 1.7, 2.1_

- [x] 4. Implement `HistoricalDataService.get_bars` (`historical.py`)
  - Validate timeframe (against `SUPPORTED_TIMEFRAMES`) and range (start present/parseable,
    end present, start <= end) BEFORE any Alpaca call, raising `InvalidTimeframeError` /
    `InvalidRangeError`.
  - Obtain the client via `factory.build_crypto_data_client()`; normalize results through
    `Normalizer`; return `[]` when no bars exist; paginate internally for >10,000 bars,
    deduplicate by timestamp and sort ascending into one list.
  - Reuse `CredentialsRequiredError` (no credentials) and `TransientAlpacaError`
    (timeout >10s / network) without interrupting the process.
  - Inline tests: invalid timeframe/range raises without calling Alpaca (factory spy asserts
    never called); empty store raises `CredentialsRequiredError` before any client build.
  - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7, 1.8, 1.9_

- [x] 5. Implement `MarketDataStreamer` (`streaming.py`)
  - Pub/sub: `subscribe`, `unsubscribe`, `_publish` fanning out normalized `Bar`/`Quote` to
    all callbacks.
  - `start()`: build the stream via factory, subscribe to BTC/USD, run the receive loop,
    normalize each update and discard/log malformed ones; on disconnect reconnect with
    exponential backoff (`delay = 1`, `delay = min(delay * 2, 30)`, reset on success)
    indefinitely while active without terminating the process.
  - `stop()`: clear the active flag, cancel the subscription, release the connection.
  - Inline tests: backoff schedule stays within the 1s→30s bounds while active; `stop()`
    releases the connection; two subscribers both receive a fed normalized update.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.2, 3.3_

- [x]* 6. Add optional historical-bars HTTP router (`api/market_data.py`)
  - `GET /market-data/bars?symbol&timeframe&start&end` returning `list[BarOut]`, mapping
    `InvalidTimeframeError`→400 `invalid_timeframe`, `InvalidRangeError`→400 `invalid_range`,
    `CredentialsRequiredError`→409 `no_credentials`, `TransientAlpacaError`→502
    `transient_error`; mount the router in `app/main.py`.
  - _Requirements: 1.1, 1.4, 1.5, 1.8, 1.9_

- [x]* 7. Write the property-based test suite (Hypothesis, Alpaca mocked)
  - Use `pytest` + `Hypothesis` + `pytest-asyncio`, min. 100 iterations each, Alpaca stubbed
    via `unittest.mock`; tag each test `Feature: 02-data-feed, Property {n}`.
  - **Property 1**: `get_bars` output is all `Bar` with exact fields and sorted ascending.
    **Validates: Requirements 1.1, 1.2, 3.1, 3.2**
  - **Property 2**: valid range with no data returns `[]` and raises nothing.
    **Validates: Requirements 1.3**
  - **Property 3**: invalid timeframe/range raises the right error without calling Alpaca.
    **Validates: Requirements 1.4, 1.5, 1.7**
  - **Property 4**: malformed datum → `Normalizer` returns `None`, nothing delivered,
    processing continues. **Validates: Requirements 3.2, 3.3**
  - **Property 5**: multi-page pagination assembles one ascending list with no duplicates.
    **Validates: Requirements 1.6, 1.2**
  - **Property 6**: reconnection backoff follows 1s→30s cap and loop continues while active.
    **Validates: Requirements 2.3**

## Notes

- Tasks marked with `*` are optional (the HTTP router is a convenience surface; the property
  suite groups the exhaustive checks — essential example tests already live inline in tasks
  2, 3, 4, and 5).
- Each task references specific requirements for traceability.
- Property tests validate universal correctness properties; inline example tests cover the
  Minimum Tests from requirements.md.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["4", "5"] },
    { "id": 4, "tasks": ["6", "7"] }
  ]
}
```
