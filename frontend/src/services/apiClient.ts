// Cliente REST hacia el backend (FastAPI).
// Los endpoints los define el spec 07-bot-api.

import type {
  AccountStatus,
  BacktestResult,
  BacktestRunRequest,
  BotStatus,
  CredentialMetadata,
  Mode,
} from "../types";

const DEFAULT_BASE_URL = "http://localhost:8000";

export interface HealthResponse {
  status: string;
  [key: string]: unknown;
}

/**
 * Error normalizado que expone el `error_code` estable del backend.
 * Permite a los componentes distinguir `no_credentials` de `invalid_mode`
 * o de fallos de red (`network`) sin depender del texto del mensaje.
 */
export class ApiError extends Error {
  readonly error_code: string;
  readonly status?: number;

  constructor(error_code: string, message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.error_code = error_code;
    this.status = status;
  }
}

/** Cuerpo de error esperado del backend: { error_code, detail }. */
interface BackendErrorBody {
  error_code?: string;
  detail?: string;
}

export class ApiClient {
  readonly baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl =
      baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL;
  }

  /** Prueba la conexión con el backend. GET /health */
  async health(): Promise<HealthResponse> {
    const res = await fetch(`${this.baseUrl}/health`);
    if (!res.ok) {
      throw new Error(`GET /health -> ${res.status} ${res.statusText}`);
    }
    return (await res.json()) as HealthResponse;
  }

  // --- Credentials (R1) ---

  /** GET /credentials -> metadatos no sensibles. */
  async getCredentials(): Promise<CredentialMetadata> {
    return this.request<CredentialMetadata>("/credentials", { method: "GET" });
  }

  /**
   * POST /credentials con { api_key, secret } -> metadatos.
   * El argumento `secret` no se retiene en ningún campo del cliente.
   */
  async saveCredentials(
    apiKey: string,
    secret: string,
  ): Promise<CredentialMetadata> {
    return this.request<CredentialMetadata>("/credentials", {
      method: "POST",
      body: { api_key: apiKey, secret },
    });
  }

  /** DELETE /credentials. */
  async deleteCredentials(): Promise<{ deleted: boolean; detail: string }> {
    return this.request<{ deleted: boolean; detail: string }>("/credentials", {
      method: "DELETE",
      hasBody: true,
    });
  }

  // --- Account (R2) ---

  /** GET /account -> snapshot de la cuenta paper. */
  async getAccount(): Promise<AccountStatus> {
    return this.request<AccountStatus>("/account", { method: "GET" });
  }

  // --- Bot control (R3) ---

  /** POST /bot/start con { mode } -> estado del bot. */
  async startBot(mode: Mode): Promise<BotStatus> {
    return this.request<BotStatus>("/bot/start", {
      method: "POST",
      body: { mode },
    });
  }

  /** POST /bot/stop -> estado del bot. */
  async stopBot(): Promise<BotStatus> {
    return this.request<BotStatus>("/bot/stop", {
      method: "POST",
      hasBody: true,
    });
  }

  /** GET /bot/status -> estado del bot. */
  async getBotStatus(): Promise<BotStatus> {
    return this.request<BotStatus>("/bot/status", { method: "GET" });
  }

  // --- Backtest (spec 05) ---

  /**
   * POST /backtest con { mode, start, end, symbol?, timeframe?, seed? } ->
   * resultado de la simulación (métricas + trades). El backtest es determinista:
   * con la misma seed y el mismo rango produce el mismo resultado.
   */
  async runBacktest(req: BacktestRunRequest): Promise<BacktestResult> {
    return this.request<BacktestResult>("/backtest", {
      method: "POST",
      body: req,
    });
  }

  /**
   * Helper privado con manejo de error uniforme.
   * - Hace el fetch contra `this.baseUrl`.
   * - Si !response.ok, intenta parsear el body JSON y extraer `error_code`/`detail`;
   *   lanza `ApiError(error_code ?? "unknown", detail ?? message, status)`.
   * - Si el fetch falla (red), lanza `ApiError("network", ...)`.
   */
  private async request<T>(
    path: string,
    options: {
      method: string;
      body?: unknown;
      /** Fuerza cabecera Content-Type en peticiones sin cuerpo JSON (DELETE/POST vacíos). */
      hasBody?: boolean;
    },
  ): Promise<T> {
    const { method, body, hasBody } = options;
    const init: RequestInit = { method };

    if (body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    } else if (hasBody) {
      init.headers = { "Content-Type": "application/json" };
    }

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, init);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      throw new ApiError("network", message);
    }

    if (!response.ok) {
      let errBody: BackendErrorBody | null = null;
      try {
        errBody = (await response.json()) as BackendErrorBody;
      } catch {
        errBody = null;
      }
      const fallback = `${method} ${path} -> ${response.status} ${response.statusText}`;
      throw new ApiError(
        errBody?.error_code ?? "unknown",
        errBody?.detail ?? fallback,
        response.status,
      );
    }

    return (await response.json()) as T;
  }
}

/** Instancia por defecto lista para usar. */
export const apiClient = new ApiClient();
