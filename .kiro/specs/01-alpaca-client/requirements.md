# Requirements Document

## Introduction

This spec defines the base connection layer between TradeBot and the official Alpaca API, operating **exclusively in paper trading mode** (`https://paper-api.alpaca.markets`) with an initial focus on the `BTC/USD` asset. It encapsulates the secure storage of Alpaca credentials, their validation against Alpaca, on-demand construction of an authenticated client, account and balance queries, a hard paper-trading-only safety barrier, and inspection/removal of stored credentials.

This layer is the foundation on which later specs (data feed, order execution, risk management, bot API) depend. Alpaca API keys and secrets are encrypted at rest using Fernet with the key provided in `APP_ENCRYPTION_KEY`. The existing helpers in `backend/app/core/security.py` (`encrypt_secret` / `decrypt_secret`) and the configuration in `backend/app/core/config.py` (`alpaca_paper_base_url`, `alpaca_paper_only`) provide the cryptographic and configuration primitives referenced here.

## Glossary

- **System**: The TradeBot backend (FastAPI) component that implements this Alpaca client layer, including its credential store, validation logic, and client factory.
- **User**: A person interacting with TradeBot through the frontend to configure and monitor the bot.
- **API Key**: The Alpaca API Key ID submitted by the User.
- **Secret**: The Alpaca API Secret Key submitted by the User.
- **Credential_Store**: The PostgreSQL-backed storage that holds Alpaca credentials as Fernet-encrypted values, along with non-sensitive metadata (last-4 of the API Key ID, last validation status).
- **Fernet_Key**: The symmetric encryption key read from the `APP_ENCRYPTION_KEY` environment variable, used to encrypt and decrypt credentials.
- **Alpaca_Paper_Endpoint**: The Alpaca paper trading account endpoint reachable under base URL `https://paper-api.alpaca.markets`.
- **Client_Factory**: The single factory in the System that returns an authenticated `alpaca-py` client configured for paper trading.
- **Transient_Error**: An error caused by a network failure or timeout (no response within the configured timeout), as distinct from an authentication failure.
- **Invalid_Credentials_Error**: An error caused by Alpaca rejecting credentials with an authentication failure (HTTP 401 or 403).
- **Validation_Timeout**: The maximum time of 10 seconds the System waits for a response from Alpaca before treating the attempt as a Transient_Error.
- **Active_Mode**: The trading mode reported to the frontend, which in this phase is always `paper`.

## Requirements

### Requirement 1: Securely store Alpaca credentials

**User Story:** As a User, I want to submit my Alpaca API Key and Secret from the frontend, so that the bot can operate on my paper account without ever exposing my credentials.

#### Acceptance Criteria

1. WHEN the User submits a non-empty API Key and a non-empty Secret, THE System SHALL encrypt each value with the Fernet_Key from `APP_ENCRYPTION_KEY` before writing to the Credential_Store and SHALL confirm that the credentials were saved.
2. THE System SHALL store the API Key and Secret only as Fernet-encrypted values and SHALL persist those values solely in encrypted form.
3. WHEN stored credential information is requested, THE System SHALL return credential metadata that excludes the decrypted Secret.
4. THE System SHALL exclude the plaintext API Key and plaintext Secret from all log output and error output.
5. WHEN valid credentials are submitted and a previous credential set already exists in the Credential_Store, THE System SHALL replace the previous set so that exactly one active credential set remains.
6. IF `APP_ENCRYPTION_KEY` is missing or is not a valid Fernet_Key at submission time, THEN THE System SHALL reject the submission with an error indicating that the encryption key is unavailable or invalid and SHALL leave the Credential_Store unchanged.
7. IF the submitted API Key or Secret is empty or contains only whitespace, THEN THE System SHALL reject the submission with an error indicating that the field is required and SHALL leave the Credential_Store unchanged.

### Requirement 2: Validate credentials against Alpaca

**User Story:** As a User, I want to know whether my credentials are valid, so that I can trust the bot will operate before I start it.

#### Acceptance Criteria

1. WHEN new credentials are submitted, THE System SHALL validate the credentials by calling the Alpaca_Paper_Endpoint before treating the credentials as usable.
2. IF validation returns an authentication failure with HTTP status 401 or 403, THEN THE System SHALL respond with an Invalid_Credentials_Error and SHALL leave the Credential_Store unchanged.
3. IF validation receives no response within the Validation_Timeout of 10 seconds or fails due to a network error, THEN THE System SHALL respond with a Transient_Error that is distinguishable from an Invalid_Credentials_Error and SHALL leave the Credential_Store unchanged.
4. WHEN validation succeeds, THE System SHALL persist the encrypted credentials and record the last validation status as `valid`.

### Requirement 3: Query account and balance

**User Story:** As a User, I want to see my paper account balance and status, so that I can confirm the connection works and monitor available funds.

#### Acceptance Criteria

1. WHEN the account status is requested and valid credentials exist in the Credential_Store, THE System SHALL return from the Alpaca_Paper_Endpoint the cash balance as a numeric monetary value, the buying power as a numeric monetary value, and the account status reported by Alpaca.
2. IF the account status is requested and no credentials are configured in the Credential_Store, THEN THE System SHALL reject the request without calling Alpaca and SHALL respond with a "no credentials configured" error.
3. IF Alpaca returns an error or the account query receives no response within the Validation_Timeout of 10 seconds, THEN THE System SHALL respond with an account-query-failure error, SHALL keep the backend process running, and SHALL leave the stored credentials unchanged.

### Requirement 4: Build an authenticated client on demand

**User Story:** As a developer of other features, I want a single factory that returns an authenticated Alpaca client, so that the data feed, execution, and risk components do not each reimplement authentication.

#### Acceptance Criteria

1. WHEN an authenticated client is requested and valid credentials exist in the Credential_Store, THE Client_Factory SHALL decrypt the credentials in memory and build an `alpaca-py` client configured for paper trading.
2. WHEN the client has been built, THE Client_Factory SHALL discard the decrypted Secret from memory and SHALL retain the decrypted Secret only for the duration of client construction.
3. IF no valid credentials exist when a client is requested, THEN THE Client_Factory SHALL raise a clear error instead of returning an unauthenticated client.

### Requirement 5: Enforce paper-trading-only barrier

**User Story:** As a User, I want a hard guarantee that the bot only ever touches paper trading, so that I never risk real money in this phase.

#### Acceptance Criteria

1. THE System SHALL build the client against the base URL `https://paper-api.alpaca.markets`.
2. WHILE `ALPACA_PAPER_ONLY` is true, IF the configuration attempts to target a non-paper base URL, THEN THE System SHALL refuse to start and SHALL report the misconfiguration with an observable indication.
3. WHEN the account status response is returned, THE System SHALL include the Active_Mode value `paper` so that the mode is visible in the frontend.

### Requirement 6: Inspect and remove stored credentials

**User Story:** As a User, I want to see whether credentials are configured and be able to remove them, so that I can rotate or revoke access.

#### Acceptance Criteria

1. WHEN stored credentials are inspected and credentials exist in the Credential_Store, THE System SHALL return only non-sensitive metadata consisting of the fact that credentials exist, the last 4 characters of the API Key ID, and the last validation status.
2. IF stored credentials are inspected and no credentials exist, THEN THE System SHALL respond indicating that no credentials are configured, without raising a fatal error.
3. WHEN the User requests deletion and credentials exist in the Credential_Store, THE System SHALL remove the credentials from the Credential_Store and SHALL confirm the deletion.
4. IF deletion is requested and no credentials exist, THEN THE System SHALL respond indicating that there were no credentials to delete, without raising a fatal error.
5. WHEN credentials are deleted and the bot is running, THE System SHALL report that the deletion affects the running bot, where detailed handling of the running bot belongs to spec `07-bot-api`.

## Non-Functional Requirements

### Security
1. THE System SHALL encrypt Alpaca credentials at rest using Fernet with the Fernet_Key from `APP_ENCRYPTION_KEY`.
2. WHEN a decrypted Secret is held in memory for client construction, THE System SHALL retain the decrypted Secret only transiently and SHALL discard it after use.

### Resilience
1. WHEN the System calls Alpaca, THE System SHALL apply a request timeout of 10 seconds.
2. WHEN a call to Alpaca fails, THE System SHALL classify the failure as either a Transient_Error or an Invalid_Credentials_Error so that callers can distinguish network/timeout failures from authentication failures.

### Isolation
1. THE System SHALL restrict access to the Credential_Store to this Alpaca client layer, so that other components obtain authenticated access only through the Client_Factory.

## Minimum Tests

- **Encryption round-trip**: encrypting then decrypting a credential returns the original value and the persisted value is not plaintext (started in `backend/tests/test_security.py`).
- **Invalid credentials not persisted**: a mocked Alpaca response of HTTP 401/403 yields an Invalid_Credentials_Error and leaves the Credential_Store unchanged.
- **Transient failure handling**: a mocked network error or a timeout beyond 10 seconds is reported as a Transient_Error distinguishable from an Invalid_Credentials_Error, and no credentials are persisted.
- **Inspection returns metadata only**: inspecting stored credentials returns existence, last-4 of the API Key ID, and last validation status, and never the decrypted Secret.
- **Factory uses paper base URL**: the Client_Factory builds a client against `https://paper-api.alpaca.markets` (Alpaca client mocked).
- **Account query without credentials**: requesting account status with no configured credentials returns a clear "no credentials configured" error without calling Alpaca.
