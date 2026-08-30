# Requirements Document

## Introduction

This spec defines the Risk Manager of TradeBot: the set of protection rules that are applied
**before** any order is executed. It is the last barrier before an order is sent to the Alpaca
**paper trading** account (`https://paper-api.alpaca.markets`) for the single asset `BTC/USD`.
It operates **exclusively in paper trading mode**; no real money is ever at risk in this phase.

This spec is the concrete implementation of the risk port that spec `04-order-execution`
already defined and depends on. Spec `04` today wires an interim pass-through
`AllowAllRiskManager`; this spec `06` provides the real `RiskManager` class that implements
that port. The interface is defined by spec `04` and is **not changed here**:

- `RiskPort` (a `Protocol`) with a single method `evaluate(proposed_order: ProposedOrder) -> RiskDecision`.
- `ProposedOrder(symbol: str, side: str, qty: Decimal)`.
- `RiskDecision(approved: bool, reason: str)`.

The Risk Manager enforces two rules: a configurable **daily loss limit** and a configurable
**maximum lot size** (position size). When a rule blocks an order, the System emits a
`RISK_BLOCK` domain event, reusing the `Event_Publisher` pattern established by spec `04`.
Mapping that domain event onto the frontend WebSocket is the responsibility of spec
`07-bot-api` and is out of scope here.

The scope is intentionally minimal, matching the same bounded criteria as specs `01`, `02`,
`03`, and `04`: paper trading only, single asset `BTC/USD`, and only the essential
capabilities described below.

## Glossary

- **System**: The Risk Manager component implemented by this spec.
- **RiskManager**: The concrete class provided by this spec that implements `RiskPort`.
- **RiskPort**: The interface (a `Protocol`) defined by spec `04-order-execution` with the
  single method `evaluate(proposed_order: ProposedOrder) -> RiskDecision`. This spec provides
  its real implementation, replacing the interim `AllowAllRiskManager` used by spec `04`.
- **ProposedOrder**: The input to `evaluate`, a structure `ProposedOrder(symbol: str,
  side: str, qty: Decimal)` describing the order spec `04` intends to send to Alpaca.
- **RiskDecision**: The output of `evaluate`, a structure `RiskDecision(approved: bool,
  reason: str)` indicating whether the order is allowed and, when blocked, why.
- **Opening_Order**: A proposed order that opens or increases a new position, as opposed to a
  protective close.
- **Protective_Close**: An order that closes an existing position for protection, such as a
  Stop-Loss or Take-Profit close managed by spec `04`. Protective closes are always allowed.
- **Daily_Loss_Limit**: The configured positive amount of accumulated realized loss for the
  current UTC day at which the System blocks new opening orders.
- **Daily_Realized_PnL**: The current UTC day's accumulated realized profit and loss reported
  to the System, from which the day's accumulated loss is derived.
- **Max_Qty**: The configured maximum order quantity as a `Decimal` greater than 0.
- **Max_Equity_Pct**: An optional configured maximum expressed as a percentage of current
  account equity, greater than 0 and less than or equal to 100.
- **Account_Equity**: The current equity of the Alpaca paper account, used to derive the
  quantity equivalent of `Max_Equity_Pct`.
- **Effective_Allowed_Max**: The quantity used to validate a proposed order: `Max_Qty` when no
  `Max_Equity_Pct` is configured, otherwise the lesser of `Max_Qty` and the quantity
  equivalent to `Max_Equity_Pct` of current `Account_Equity`.
- **Event_Publisher**: The publisher to which the System emits domain events, following the
  pattern established by spec `04-order-execution`.
- **RISK_BLOCK**: The domain event emitted when a proposed order is blocked by a risk rule,
  carrying the reason. Spec `07-bot-api` maps this event to the frontend WebSocket.
- **UTC_Day**: The calendar day evaluated in UTC, used as the reset boundary for
  `Daily_Realized_PnL`.

## Requirements

### Requirement 1: Daily loss limit

**User Story:** As a user, I want a daily loss cap, so that the bot stops trading on a bad day.

#### Acceptance Criteria

1. THE System SHALL provide a configurable Daily_Loss_Limit expressed as a positive amount.
2. IF the configured Daily_Loss_Limit is not a positive amount, THEN THE System SHALL reject
   the configuration with a clear error.
3. THE System SHALL track the current UTC_Day's accumulated realized loss derived from the
   Daily_Realized_PnL reported and updated to the System.
4. WHEN the current UTC_Day's accumulated loss reaches or exceeds the configured
   Daily_Loss_Limit, THE System SHALL block the proposed Opening_Order by returning a
   RiskDecision with `approved=False` and a reason indicating a daily-loss block.
5. WHILE the current UTC_Day's accumulated loss is below the configured Daily_Loss_Limit, THE
   System SHALL allow the proposed order with respect to this rule.
6. WHEN the UTC_Day changes, THE System SHALL reset the accumulated realized loss to zero.
7. WHEN a block occurs due to the Daily_Loss_Limit, THE System SHALL emit a RISK_BLOCK domain
   event to the Event_Publisher including the reason, where mapping that event to the frontend
   WebSocket is the responsibility of spec `07-bot-api`.
8. THE System SHALL apply the Daily_Loss_Limit block only to Opening_Orders, and SHALL allow
   Protective_Closes regardless of the accumulated daily loss.

### Requirement 2: Position size (lot)

**User Story:** As the bot operator, I want each proposed order validated against a
configurable maximum lot size before it is sent to Alpaca, so that the bot never opens
positions larger than I authorized, even in paper trading.

#### Acceptance Criteria

1. THE System SHALL provide a configured maximum order size as a `Decimal` Max_Qty greater
   than 0.
2. WHERE a Max_Equity_Pct greater than 0 and less than or equal to 100 is configured, THE
   System SHALL compute the Effective_Allowed_Max as the lesser of Max_Qty and the quantity
   equivalent to Max_Equity_Pct of the current Account_Equity.
3. WHEN the RiskManager evaluates a ProposedOrder, THE System SHALL compare the requested
   `qty` against the Effective_Allowed_Max before returning the RiskDecision.
4. IF the requested `qty` is less than or equal to the Effective_Allowed_Max, THEN THE System
   SHALL return, for this rule, a RiskDecision with `approved=True`.
5. IF the requested `qty` exceeds the Effective_Allowed_Max, THEN THE System SHALL return a
   RiskDecision with `approved=False` and a reason indicating the maximum lot size is
   exceeded.
6. IF the requested `qty` is less than or equal to 0 or is not a valid `Decimal`, THEN THE
   System SHALL return a RiskDecision with `approved=False` and a reason indicating the
   quantity is invalid, without comparing the `qty` against the Effective_Allowed_Max.
7. IF a Max_Equity_Pct is configured and the current Account_Equity is unavailable or not
   positive, THEN THE System SHALL return a RiskDecision with `approved=False` and a reason
   indicating the equity-based limit could not be determined.

### Requirement 3: Pre-order evaluation (RiskPort implementation)

**User Story:** As the order-execution component (spec `04`), I want to consult a single
risk-evaluation gate before sending each order, so that no order violating the risk rules
(daily loss and lot size) reaches Alpaca.

#### Acceptance Criteria

1. THE System SHALL provide a RiskPort implementation, the RiskManager class, whose
   `evaluate(proposed_order) -> RiskDecision` method is the single gate spec `04` consults
   before sending any order.
2. WHEN `evaluate` is invoked with a ProposedOrder, THE System SHALL apply all risk rules
   defined in Requirement 1 (daily loss limit) and Requirement 2 (maximum lot size) to that
   order.
3. WHEN all risk rules have been applied and none is violated, THE System SHALL return a
   RiskDecision with `approved=True`.
4. IF at least one risk rule is violated, THEN THE System SHALL return a RiskDecision with
   `approved=False` and a readable reason identifying which rule blocked the order.
5. WHEN `evaluate` is invoked twice with the same risk state and the same ProposedOrder, THE
   System SHALL return identical RiskDecisions.
6. IF a risk rule is violated during evaluation, THEN THE System SHALL return a RiskDecision
   describing the violation without raising an exception for that violation.

## Minimum Tests

- **Loss below the limit allows the order**: with the accumulated daily loss below the
  Daily_Loss_Limit, an Opening_Order is allowed (`approved=True`).
- **Loss at or above the limit blocks the order**: when the accumulated daily loss reaches or
  exceeds the Daily_Loss_Limit, the Opening_Order is blocked (`approved=False`) with a
  daily-loss reason.
- **Lot size within the max allowed**: a ProposedOrder whose `qty` is within the
  Effective_Allowed_Max is allowed.
- **Lot size above the max rejected**: a ProposedOrder whose `qty` exceeds the
  Effective_Allowed_Max is rejected (`approved=False`) with a max-lot reason.
- **Invalid quantity rejected**: a ProposedOrder with `qty` less than or equal to 0 is
  rejected as invalid without comparing against the max.
- **Block emits RISK_BLOCK**: a block due to a risk rule emits a RISK_BLOCK domain event to
  the Event_Publisher carrying the reason.
- **UTC day change resets loss**: when the UTC_Day changes, the accumulated realized loss is
  reset to zero.
- **Deterministic evaluation**: `evaluate` returns identical RiskDecisions for the same risk
  state and the same ProposedOrder.
- **No exception on violation**: `evaluate` returns a RiskDecision without raising when a risk
  rule is violated.
- **Satisfies the spec-04 RiskPort**: the RiskManager satisfies the spec `04` RiskPort
  interface (structural / `isinstance` check against the `Protocol`).
