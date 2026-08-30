// Cliente WebSocket para el feed en tiempo real del bot.
// El protocolo y los eventos los definen los specs 07-bot-api y 08-web-frontend
// (señales, órdenes, fills, bloqueos de riesgo, errores, cambios de estado).

const DEFAULT_WS_URL = "ws://localhost:8000/ws/bot";

export type BotStreamHandler = (event: MessageEvent) => void;

export class BotStream {
  readonly url: string;
  private socket: WebSocket | null = null;

  constructor(url?: string) {
    this.url = url ?? import.meta.env.VITE_WS_BASE_URL ?? DEFAULT_WS_URL;
  }

  /** Abre la conexión WebSocket y registra un handler para los mensajes. */
  connect(onMessage?: BotStreamHandler): void {
    if (this.socket) {
      return;
    }
    this.socket = new WebSocket(this.url);
    if (onMessage) {
      this.socket.addEventListener("message", onMessage);
    }
    // TODO (spec 07/08): reconexión automática al perder la conexión e
    //       indicar el estado de conexión al usuario en el dashboard.
  }

  /** Cierra la conexión WebSocket si está abierta. */
  disconnect(): void {
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  }
}
