// Cliente WebSocket para el feed en tiempo real del bot (spec 07-bot-api + 08-web-frontend).
// Abre la conexión a /ws/bot, entrega cada OrderEvent parseado y reconecta con
// backoff exponencial acotado al perder la conexión (R4.1, R4.2, R4.4, R4.5).

import type { BotEvent, ConnectionStatus } from "../types";

const DEFAULT_WS_URL = "ws://localhost:8000/ws/bot";

/** Backoff exponencial acotado (R4.4): 1s → 2s → 4s → 8s … tope 30s. */
export const INITIAL_BACKOFF_MS = 1000;
export const MAX_BACKOFF_MS = 30000;

/** Próximo delay de reconexión, duplicando el actual sin superar el tope. */
export function nextBackoff(current: number): number {
  return Math.min(current * 2, MAX_BACKOFF_MS);
}

export type BotEventHandler = (event: BotEvent) => void;
export type ConnectionStatusHandler = (status: ConnectionStatus) => void;

/**
 * Subconjunto mínimo de la API WebSocket que usamos. Permite inyectar un doble
 * de prueba (FakeWebSocket) sin necesidad de red.
 */
export interface WebSocketLike {
  onopen: ((ev?: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev?: unknown) => void) | null;
  onerror: ((ev?: unknown) => void) | null;
  close(): void;
}

export type WebSocketFactory = (url: string) => WebSocketLike;

/** Scheduler inyectable para poder testear el backoff con timers falsos. */
export interface Scheduler {
  setTimeout(handler: () => void, ms: number): ReturnType<typeof setTimeout>;
  clearTimeout(id: ReturnType<typeof setTimeout>): void;
}

const defaultScheduler: Scheduler = {
  setTimeout: (handler, ms) => setTimeout(handler, ms),
  clearTimeout: (id) => clearTimeout(id),
};

const defaultWebSocketFactory: WebSocketFactory = (url) =>
  new WebSocket(url) as unknown as WebSocketLike;

export class BotStream {
  readonly url: string;

  private readonly websocketFactory: WebSocketFactory;
  private readonly scheduler: Scheduler;

  private socket: WebSocketLike | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private currentBackoff = INITIAL_BACKOFF_MS;
  private closedByUser = false;

  private onEvent: BotEventHandler | null = null;
  private onStatus: ConnectionStatusHandler | null = null;

  constructor(
    url?: string,
    websocketFactory: WebSocketFactory = defaultWebSocketFactory,
    scheduler: Scheduler = defaultScheduler,
  ) {
    this.url = url ?? import.meta.env.VITE_WS_BASE_URL ?? DEFAULT_WS_URL;
    this.websocketFactory = websocketFactory;
    this.scheduler = scheduler;
  }

  /**
   * Abre la conexión y transmite eventos; reconecta con backoff acotado (R4.1, R4.4).
   * Emite "connecting" de inmediato y "connected" al abrir el socket (R4.5).
   */
  connect(onEvent: BotEventHandler, onStatus: ConnectionStatusHandler): void {
    this.onEvent = onEvent;
    this.onStatus = onStatus;
    this.closedByUser = false;
    this.openSocket();
  }

  private openSocket(): void {
    this.onStatus?.("connecting");

    const socket = this.websocketFactory(this.url);
    this.socket = socket;

    socket.onopen = () => {
      // Conexión establecida: resetea el backoff a 1s (R4.4).
      this.currentBackoff = INITIAL_BACKOFF_MS;
      this.onStatus?.("connected");
    };

    socket.onmessage = (ev: { data: unknown }) => {
      try {
        const event = JSON.parse(String(ev.data)) as BotEvent;
        this.onEvent?.(event);
      } catch (err) {
        // Un mensaje malformado se ignora sin romper el stream (R4 resiliencia).
        console.warn("BotStream: mensaje WebSocket no parseable, ignorado", err);
      }
    };

    socket.onclose = () => this.handleDrop();
    socket.onerror = () => this.handleDrop();
  }

  /** Cierre/error no provocado por el usuario: notifica y agenda reconexión. */
  private handleDrop(): void {
    if (this.closedByUser) {
      return;
    }
    this.onStatus?.("disconnected");
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) {
      return;
    }
    const delay = this.currentBackoff;
    this.reconnectTimer = this.scheduler.setTimeout(() => {
      this.reconnectTimer = null;
      // Prepara el siguiente delay antes de reintentar (1s → 2s → 4s …, tope 30s).
      this.currentBackoff = nextBackoff(this.currentBackoff);
      if (!this.closedByUser) {
        this.openSocket();
      }
    }, delay);
  }

  /** Cierra la conexión y detiene los reintentos de reconexión. */
  disconnect(): void {
    this.closedByUser = true;
    if (this.reconnectTimer !== null) {
      this.scheduler.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  }
}
