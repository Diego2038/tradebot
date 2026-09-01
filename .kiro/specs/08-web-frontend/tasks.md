# Implementation Plan: 08 Web Frontend

## Overview

Incremental build of the TradeBot web frontend (React + TypeScript + Vite) in `frontend/src/`.
This spec **extends** the existing skeleton (`App.tsx`, `services/apiClient.ts`,
`services/botStream.ts`) rather than starting fresh. Each task builds on the previous ones and
ends wired into `App.tsx`: first the test tooling and shared types, then the REST client and
the WebSocket stream + `useBotEvents` hook, then the presentation components, then the
`BotControls`, then the top-level composition in `App.tsx`, and finally a single closing task
with the essential fast-check property tests.

No production dependency is added; only test devDeps (`vitest`, `@testing-library/react`,
`@testing-library/jest-dom`, `jsdom`, `fast-check`). Testing is kept minimal and folded into
the implementation tasks as inline sub-bullets; the property-based tests are grouped into one
final task rather than one task per property. All Docker verification is run with `sudo`:

```
sudo docker run --rm -v "$PWD/frontend":/app -w /app node:20-alpine \
  sh -c "npm install && npm run build && npm test"
```

## Tasks

- [x] 1. Test tooling and shared types
  - Add test devDeps to `frontend/package.json`: `vitest`, `@testing-library/react`,
    `@testing-library/jest-dom`, `jsdom`, `fast-check`; add script `"test": "vitest run"`.
  - Add a `test` block to `frontend/vite.config.ts` (`environment: "jsdom"`, `globals: true`,
    a setup file that imports `@testing-library/jest-dom`).
  - Create `frontend/src/types.ts` with the shared contracts: `Mode`, `ConnectionStatus`,
    `EventType`, `CredentialMetadata`, `AccountStatus`, `BotStatus`, `BotEvent`, and the
    `ApiError` shape (mirroring the spec-07 surface).
  - _Requirements: 1.5, 2.2, 3.1, 3.5, 4.2, 4.5, 5.1_

- [x] 2. REST client (`services/apiClient.ts`, extended)
  - Add an `ApiError` class carrying a stable `error_code`, `message`, and optional `status`.
  - Add `getCredentials`, `saveCredentials(apiKey, secret)`, `deleteCredentials`, `getAccount`,
    `startBot(mode)`, `stopBot`, `getBotStatus`; every method is `async`.
  - On a non-OK response, read the JSON body, extract `error_code` when present, and throw
    `ApiError(error_code, message, status)`; a network/parse failure throws
    `ApiError("network", ...)`. `saveCredentials` sends `{ api_key, secret }` and returns only
    metadata (the Secret argument is never retained).
  - Inline tests (`fetch` mocked): `saveCredentials` issues `POST /credentials` with
    `{ api_key, secret }`; a `409` `no_credentials` response produces an `ApiError` with
    `error_code === "no_credentials"`.
  - _Requirements: 1.2, 1.4, 1.6, 1.7, 2.1, 2.3, 3.2, 3.3, 3.4, 3.6, 3.7_

- [x] 3. WebSocket stream + `useBotEvents` hook (`services/botStream.ts`, `hooks/useBotEvents.ts`)
  - Extend `BotStream` with `connect(onEvent, onStatus)` and `disconnect()`: emit
    `"connecting"` on connect, `"connected"` on open, `JSON.parse` each message into a
    `BotEvent` passed to `onEvent` (a malformed message is logged and ignored), and on
    close/error (while not explicitly disconnected) emit `"disconnected"` and schedule a
    reconnect with capped exponential backoff (`1s → 2s → 4s → 8s`, cap `30s`, reset on open).
    `disconnect()` cancels any pending timer and closes without reconnecting.
  - Create `hooks/useBotEvents.ts`: connect on mount, prepend incoming events (most-recent-first),
    expose `events` and `connectionStatus`, and `disconnect` on unmount; accept an optional
    injected `BotStream` for tests.
  - Inline tests (`WebSocket` mocked): a received message reaches `onEvent` as a parsed
    `BotEvent`; a simulated close emits `"disconnected"` and schedules a reconnection attempt.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 4. Presentation components
  - [x] 4.1 `PaperTradingBanner.tsx`
    - Render a persistent notice that the app runs in paper trading with no real money.
    - _Requirements: 5.1, 5.2_

  - [x] 4.2 `CredentialsForm.tsx`
    - Render an API Key ID text input and a **masked** Secret input (`type="password"`); read
      the Secret at submit time and pass it to `onSave` — never store it in state nor render it.
      When `metadata.exists`, show `key_id_last4` and `validation_status` plus a delete action;
      never show the Secret. On error, show the error while keeping current metadata visible.
    - _Requirements: 1.1, 1.3, 1.5, 1.6, 1.7_

  - [x] 4.3 `AccountPanel.tsx`
    - Render `cash`/`buying_power` and `status` when `account` is present; otherwise show the
      load error.
    - _Requirements: 2.2, 2.3_

  - [x] 4.4 `ConnectionStatus.tsx`
    - Render the current `ConnectionStatus` (`connected`/`connecting`/`disconnected`).
    - _Requirements: 4.5_

  - [x] 4.5 `Dashboard.tsx`
    - Map `events` (already most-recent-first) to rows showing `event_type`, `symbol`, `side`,
      `qty`, `price`, and `timestamp`.
    - _Requirements: 4.2, 4.3_

  - [x]* 4.6 Inline component tests
    - The Secret input is `type="password"` and the submitted Secret does not appear in the DOM;
      existing metadata shows only non-sensitive fields; the Dashboard renders one event with all
      required fields; the `PaperTradingBanner` is present.
    - _Requirements: 1.3, 1.5, 4.2, 5.1_

- [x] 5. Bot controls (`components/BotControls.tsx`)
  - Render a `random`/`predictive` selector, Start and Stop buttons (both disabled while
    `busy`), and the current `state`, `mode`, and `symbol`; call `onStart(mode)` / `onStop()`.
    Branch on `error_code` to show distinct guidance for `no_credentials` and `invalid_mode`.
  - Inline tests: selecting a mode and starting calls `onStart(mode)`; a `no_credentials` error
    shows the configure-credentials message and keeps the displayed state `stopped`.
  - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 3.7, 3.8_

- [x] 6. App composition and top-level state (`App.tsx`)
  - Replace `App.tsx` with the real composition: on mount call `getCredentials()`, and if
    credentials exist also call `getAccount()` and `getBotStatus()`; compose
    `PaperTradingBanner`, `CredentialsForm`, `AccountPanel`, `BotControls`, `ConnectionStatus`,
    and `Dashboard`; wire `onSave`/`onDelete`/`onStart`/`onStop` to `apiClient`; use
    `useBotEvents` for `events` and `connectionStatus`; manage a `busy` flag and per-section
    error state. Render `PaperTradingBanner` unconditionally.
  - Inline tests (`fetch`/`WebSocket` mocked): on load the app issues `GET /credentials`; the
    `PaperTradingBanner` is visible.
  - _Requirements: 1.4, 2.1, 3.4, 3.8, 4.1, 4.5, 5.1_

- [x] 7. Essential property-based tests (fast-check)
  - Add one fast-check + Vitest + Testing Library (jsdom) test suite grouping the six essential
    properties from the design (min. 100 iterations each; `fetch`/`WebSocket` mocked). Tag each
    test `// Feature: 08-web-frontend, Property {n}: {property text}`.
    - **Property 1: The submitted Secret never appears in the DOM** — **Validates: Requirements 1.3**
    - **Property 2: Existing metadata renders only non-sensitive fields** — **Validates: Requirements 1.5**
    - **Property 3: A received Bot_Event renders with all required fields** — **Validates: Requirements 4.2**
    - **Property 4: Multiple events render most-recent-first** — **Validates: Requirements 4.3**
    - **Property 5: A disconnect sets status to disconnected and triggers reconnection** — **Validates: Requirements 4.4, 4.5**
    - **Property 6: The paper-trading indicator is always present** — **Validates: Requirements 5.1, 5.2**
  - _Requirements: 1.3, 1.5, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; core implementation
  tasks are never optional.
- Each task references specific requirement clauses for traceability.
- The spec extends the existing skeleton: `apiClient.ts` and `botStream.ts` are extended,
  `App.tsx` is replaced, and new component/hook/type files are added under `frontend/src/`.
- Critical inline tests are folded into their implementation tasks; task 7 groups the six
  mandatory property-based tests instead of one task per property.
- All Docker verification uses `sudo docker run ... node:20-alpine ... npm install && npm run build && npm test`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2", "3", "5"] },
    { "id": 2, "tasks": ["4.1", "4.2", "4.3", "4.4", "4.5"] },
    { "id": 3, "tasks": ["4.6", "6"] },
    { "id": 4, "tasks": ["7"] }
  ]
}
```
