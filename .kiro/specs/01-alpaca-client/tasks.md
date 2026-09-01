# Implementation Plan: 01 Alpaca Client

## Overview

Incremental build of the Alpaca paper-trading connection layer for the FastAPI backend (Python). Each task builds on the previous one and ends wired into the app: persistence and schemas first, then the paper-only barrier and startup hook, then the repository, factory, and services, and finally the REST router mounted in `main.py`. A single closing task adds the critical property-based tests (Hypothesis) plus the few minimum tests from the design not already covered inline.

Testing is kept minimal and, where possible, folded into the implementation task that produces the code, rather than living in separate test epics. Sub-tasks marked with `*` are optional for a first working version.

## Tasks

- [x] 1. Persistence foundation: base, model, and startup table creation
  - Create `app/db/base.py` with a shared `Base(DeclarativeBase)`.
  - Create `app/db/models/alpaca_credential.py` with the `AlpacaCredential` model (encrypted key/secret, `key_id_last4`, `validation_status`, timestamps); tokens only, never plaintext.
  - Call `Base.metadata.create_all(bind=engine)` at startup in `app/main.py`.
  - _Requirements: 1.2, 1.5_

- [x] 2. Pydantic schemas in `app/schemas/alpaca.py`
  - `CredentialSubmit` (api_key/secret, `min_length=1` + whitespace-only validator that rejects blank fields).
  - `CredentialMetadata` (exists, key_id_last4, validation_status, updated_at) with no secret field anywhere.
  - `DeletionResult` (deleted, detail) and `AccountStatus` (cash, buying_power, status, `mode` fixed to `paper`).
  - _Requirements: 1.3, 1.7, 3.1, 6.1, 5.3_

- [x] 3. Domain errors, paper-only barrier, and startup enforcement
  - Create `app/services/alpaca_client/errors.py` with the error hierarchy (`AlpacaClientError`, `CredentialsRequiredError`, `InvalidCredentialsError`, `TransientAlpacaError`, `AccountQueryError`, `PaperOnlyViolationError`).
  - Create `app/services/alpaca_client/barrier.py` with `assert_paper_only(settings)` raising `PaperOnlyViolationError` on a non-paper base URL while paper-only is on.
  - Add the startup hook in `app/main.py` that calls `assert_paper_only(get_settings())` so misconfiguration refuses to start.
  - Unit test: paper URL passes, non-paper URL raises `PaperOnlyViolationError` (Property 8).
  - _Requirements: 5.1, 5.2_

- [x] 4. `CredentialRepository` in `app/services/alpaca_client/repository.py`
  - Implement `get_active`, `replace_active` (delete-then-insert in one transaction so exactly one active set remains), and `delete_active` (returns True when a row was removed).
  - Repository stores/returns already-encrypted values; it never encrypts or decrypts.
  - _Requirements: 1.5, 6.3, 6.4_

- [x] 5. `AlpacaClientFactory` in `app/services/alpaca_client/factory.py`
  - `build_trading_client`: enforce the barrier, decrypt stored credentials into locals, build `TradingClient(..., paper=True)`, discard the secret on return (never assigned to `self`); raise `CredentialsRequiredError` when no credentials exist.
  - `validate(api_key, secret)`: build an ephemeral paper client with a 10s timeout and probe `get_account()`; map 401/403 to `InvalidCredentialsError`, timeout/network to `TransientAlpacaError`, other API errors to `AccountQueryError`.
  - Unit test with a mocked SDK: client built with `paper=True`; 401/403 vs timeout map to distinct errors; secret not retained on the factory instance (Properties 7, 4, 5, 12).
  - _Requirements: 2.1, 2.2, 2.3, 4.1, 4.2, 4.3, 5.1_

- [x] 6. `CredentialService` in `app/services/alpaca_client/credential_service.py`
  - `store`: reject blank/whitespace fields, encrypt via `security.encrypt_secret` (surface `EncryptionError`), validate through `factory.validate` before any write, then `replace_active` with `key_id_last4` and `validation_status="valid"`; on any failure leave the store unchanged.
  - `inspect`: return metadata only (exists, key_id_last4, validation_status), never decrypting the secret.
  - `delete`: remove the active set if present and report the outcome.
  - _Requirements: 1.1, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 6.1, 6.2, 6.3, 6.4_

- [x] 7. `AccountService` in `app/services/alpaca_client/account_service.py`
  - `get_account`: if no active credentials, raise `CredentialsRequiredError` without building a client or calling Alpaca; otherwise build via the factory and map `cash`, `buying_power`, `status` into `AccountStatus` with `mode="paper"`.
  - Classify Alpaca errors/timeouts as `AccountQueryError`/`TransientAlpacaError` so the backend stays up and the store is untouched.
  - Unit test: empty store raises `CredentialsRequiredError` and the factory/client is never called (mock spy) (R3.2).
  - _Requirements: 3.1, 3.2, 3.3, 5.3_

- [x] 8. REST router and exception handlers wired into `main.py`
  - Create `app/api/credentials.py` with `POST/GET/DELETE /credentials` and `GET /account`, wiring repository/services per request via `Depends(get_db)`.
  - Register FastAPI exception handlers mapping each `AlpacaClientError` subclass to its distinct HTTP status and stable `error_code` (401 invalid vs 502 transient are distinguishable; 409 no-credentials; 503 encryption); ensure no plaintext secret appears in any response.
  - Include both routers in `app/main.py`.
  - _Requirements: 1.1, 1.3, 1.4, 2.2, 2.3, 3.1, 3.2, 3.3, 6.1, 6.2, 6.3, 6.4_

- [x] 9. Critical property-based tests (Hypothesis) and remaining minimum tests
  - [x] 9.1 Add Hypothesis property tests for the critical properties (min. 100 iterations each), Alpaca SDK mocked:
    - **Property 1: Encryption round-trip never exposes plaintext** (extends `backend/tests/test_security.py`) — **Validates: Requirements 1.1, 1.2**
    - **Property 3: Metadata output never contains the secret** — **Validates: Requirements 1.3, 6.1**
    - **Property 4: 401/403 → InvalidCredentialsError, store unchanged** — **Validates: Requirements 2.2**
    - **Property 5: Timeout/network → distinguishable TransientAlpacaError, store unchanged** — **Validates: Requirements 2.3**
    - **Property 7: Every built client targets the paper endpoint (`paper=True`)** — **Validates: Requirements 4.1, 5.1**
  - [x]* 9.2 Add the remaining minimum tests from the design not covered inline
    - Validate-before-persist ordering (R2.1); encryption key missing/invalid → `EncryptionError`, store unchanged (R1.6); inspect with none → `exists=False`, no exception (R6.2); no secret in logs/error messages across error paths (R1.4); router wiring smoke test via `TestClient` asserting status codes and `error_code` values.
    - _Requirements: 1.4, 1.6, 2.1, 6.2_

## Notes

- Sub-tasks marked with `*` are optional and can be skipped for a first working version.
- Critical tests are folded into their implementation tasks (tasks 3, 5, 7); task 9 groups the mandatory property-based tests instead of one task per property.
- Each task references specific requirement clauses for traceability.
- Validation always runs before persistence, so failed submissions leave the Credential_Store unchanged.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2", "3"] },
    { "id": 1, "tasks": ["4"] },
    { "id": 2, "tasks": ["5"] },
    { "id": 3, "tasks": ["6", "7"] },
    { "id": 4, "tasks": ["8"] },
    { "id": 5, "tasks": ["9.1"] },
    { "id": 6, "tasks": ["9.2"] }
  ]
}
```
