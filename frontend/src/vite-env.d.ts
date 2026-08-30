/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL del backend REST (FastAPI). Ej: http://localhost:8000 */
  readonly VITE_API_BASE_URL?: string;
  /** URL del WebSocket del feed del bot. Ej: ws://localhost:8000/ws/bot */
  readonly VITE_WS_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
