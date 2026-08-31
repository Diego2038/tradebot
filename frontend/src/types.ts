// Shared TypeScript types for the TradeBot frontend.
// These mirror the contract of spec 07-bot-api (client-side only; no persistence).

export type Mode = "random" | "predictive";

export type ConnectionStatus = "connected" | "connecting" | "disconnected";

export type EventType =
  | "SUBMITTED"
  | "FILLED"
  | "REJECTED"
  | "ERROR"
  | "RISK_BLOCK"
  | "STOP_LOSS_CLOSE"
  | "TAKE_PROFIT_CLOSE";

/** Non-sensitive metadata from GET /credentials — never includes the Secret (R1.5). */
export interface CredentialMetadata {
  exists: boolean;
  key_id_last4: string | null;
  validation_status: string | null;
  updated_at: string | null;
}

/** GET /account snapshot (R2.2). */
export interface AccountStatus {
  cash: string;
  buying_power: string;
  status: string;
  mode: "paper";
}

/** GET /bot/status snapshot (R3.5). */
export interface BotStatus {
  state: "running" | "stopped";
  mode: Mode;
  symbol: string;
}

/** Valid bar timeframes accepted by the backtest endpoint (spec 05). */
export type Timeframe = "1Min" | "5Min" | "15Min" | "1Hour" | "1Day";

/** Request body for POST /backtest. */
export interface BacktestRunRequest {
  mode: Mode;
  start: string; // ISO 8601
  end: string; // ISO 8601
  symbol?: string; // default "BTC/USD"
  timeframe?: Timeframe; // default "1Min"
  seed?: number | null;
}

/** A single simulated trade returned by the backtest engine. */
export interface SimulatedTrade {
  side: string;
  qty: string;
  price: string;
  timestamp: string;
  reason: string;
  realized_profit: string | null;
}

/** Result payload from POST /backtest. Decimals travel as strings. */
export interface BacktestResult {
  total_return: string;
  trade_count: number;
  win_rate: string;
  max_drawdown: string;
  trades: SimulatedTrade[];
  bars_evaluated: number;
}

/** A JSON-serialized OrderEvent received over the WebSocket (R4.2). */
export interface BotEvent {
  event_type: EventType;
  symbol: string;
  side: string | null;
  qty: string | null;
  price: string | null;
  order_id: string | null;
  reason: string | null;
  timestamp: string;
}

/**
 * Normalized error surface carrying the Backend's stable error_code.
 * NOTE: the concrete `ApiError` CLASS is defined in `services/apiClient.ts`
 * (task 2). This interface documents the data shape only.
 */
export interface ApiError {
  error_code: string; // e.g. "no_credentials", "invalid_mode", "network", "unknown"
  message: string;
  status?: number;
}
