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
