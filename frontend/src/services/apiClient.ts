// Cliente REST hacia el backend (FastAPI).
// Los endpoints futuros los define el spec 07-bot-api.

const DEFAULT_BASE_URL = "http://localhost:8000";

export interface HealthResponse {
  status: string;
  [key: string]: unknown;
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

  // --- Endpoints futuros (spec 07-bot-api) ---
  // TODO: saveCredentials(apiKey, apiSecret) -> POST /credentials
  //       El backend cifra el secreto; nunca se devuelve descifrado.
  // TODO: getCredentialsInfo() -> GET /credentials
  //       Solo metadatos no sensibles (existe?, últimos 4 caracteres).
  // TODO: startBot(mode) -> POST /bot/start   (mode: "random" | "predictive")
  // TODO: stopBot() -> POST /bot/stop
  // TODO: getBotStatus() -> GET /bot/status   (activo/inactivo, modo, símbolo)
  // TODO: setMode(mode) -> PUT /bot/mode
}

/** Instancia por defecto lista para usar. */
export const apiClient = new ApiClient();
