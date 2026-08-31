import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  BotStream,
  nextBackoff,
  INITIAL_BACKOFF_MS,
  MAX_BACKOFF_MS,
  type WebSocketLike,
  type Scheduler,
} from "./botStream";
import { useBotEvents } from "../hooks/useBotEvents";
import type { BotEvent, ConnectionStatus } from "../types";

/**
 * Doble de prueba de WebSocket: permite disparar manualmente open/message/close/error
 * sin abrir ninguna conexión de red.
 */
class FakeWebSocket implements WebSocketLike {
  onopen: ((ev?: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev?: unknown) => void) | null = null;
  onerror: ((ev?: unknown) => void) | null = null;
  closed = false;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
  }

  send(_data: unknown): void {
    /* no-op */
  }

  close(): void {
    this.closed = true;
  }

  // Helpers para los tests.
  emitOpen(): void {
    this.onopen?.();
  }
  emitMessage(data: unknown): void {
    this.onmessage?.({ data });
  }
  emitClose(): void {
    this.onclose?.();
  }
  emitError(): void {
    this.onerror?.();
  }
}

function sampleEvent(): BotEvent {
  return {
    event_type: "FILLED",
    symbol: "BTC/USD",
    side: "buy",
    qty: "0.01",
    price: "50000",
    order_id: "abc-123",
    reason: null,
    timestamp: "2024-01-01T00:00:00Z",
  };
}

describe("nextBackoff", () => {
  it("dobla el valor actual", () => {
    expect(nextBackoff(INITIAL_BACKOFF_MS)).toBe(2000);
    expect(nextBackoff(2000)).toBe(4000);
    expect(nextBackoff(4000)).toBe(8000);
  });

  it("respeta el tope de 30000ms", () => {
    expect(nextBackoff(16000)).toBe(30000);
    expect(nextBackoff(MAX_BACKOFF_MS)).toBe(MAX_BACKOFF_MS);
    expect(nextBackoff(100000)).toBe(MAX_BACKOFF_MS);
  });
});

describe("BotStream", () => {
  let sockets: FakeWebSocket[];
  let factory: (url: string) => WebSocketLike;

  beforeEach(() => {
    sockets = [];
    factory = (url: string) => {
      const ws = new FakeWebSocket(url);
      sockets.push(ws);
      return ws;
    };
  });

  it("(a) emite 'connecting' al conectar y 'connected' al abrir", () => {
    const stream = new BotStream("ws://test/ws/bot", factory);
    const statuses: ConnectionStatus[] = [];
    stream.connect(
      () => {},
      (s) => statuses.push(s),
    );

    expect(statuses).toEqual(["connecting"]);
    sockets[0].emitOpen();
    expect(statuses).toEqual(["connecting", "connected"]);
  });

  it("(b) entrega un mensaje JSON parseado a onEvent", () => {
    const stream = new BotStream("ws://test/ws/bot", factory);
    const received: BotEvent[] = [];
    stream.connect(
      (e) => received.push(e),
      () => {},
    );

    const event = sampleEvent();
    sockets[0].emitOpen();
    sockets[0].emitMessage(JSON.stringify(event));

    expect(received).toHaveLength(1);
    expect(received[0]).toEqual(event);
  });

  it("(b') ignora un mensaje malformado sin romper el stream", () => {
    const stream = new BotStream("ws://test/ws/bot", factory);
    const received: BotEvent[] = [];
    stream.connect(
      (e) => received.push(e),
      () => {},
    );

    sockets[0].emitOpen();
    // Mensaje no-JSON: se ignora.
    expect(() => sockets[0].emitMessage("no-es-json {{{")).not.toThrow();
    expect(received).toHaveLength(0);
    // El stream sigue funcionando tras el mensaje malformado.
    const event = sampleEvent();
    sockets[0].emitMessage(JSON.stringify(event));
    expect(received).toEqual([event]);
  });

  it("(c) al cerrar sin disconnect emite 'disconnected' y agenda reconexión", () => {
    const scheduledDelays: number[] = [];
    const scheduler: Scheduler = {
      setTimeout: (_handler, ms) => {
        scheduledDelays.push(ms);
        // Devuelve un id ficticio sin ejecutar el handler.
        return 1 as unknown as ReturnType<typeof setTimeout>;
      },
      clearTimeout: () => {},
    };
    const stream = new BotStream("ws://test/ws/bot", factory, scheduler);
    const statuses: ConnectionStatus[] = [];
    stream.connect(
      () => {},
      (s) => statuses.push(s),
    );

    sockets[0].emitOpen();
    sockets[0].emitClose();

    expect(statuses).toEqual(["connecting", "connected", "disconnected"]);
    // Se programó una reconexión con el delay inicial (1s).
    expect(scheduledDelays).toEqual([INITIAL_BACKOFF_MS]);
  });

  it("(c') reintenta la conexión con backoff creciente usando timers falsos", () => {
    vi.useFakeTimers();
    const stream = new BotStream("ws://test/ws/bot", factory);
    const statuses: ConnectionStatus[] = [];
    stream.connect(
      () => {},
      (s) => statuses.push(s),
    );

    // Primer socket: se abre y luego se cae.
    sockets[0].emitOpen();
    sockets[0].emitClose();
    expect(statuses).toEqual(["connecting", "connected", "disconnected"]);

    // Avanza el primer backoff (1s): abre un nuevo socket y re-emite "connecting".
    act(() => {
      vi.advanceTimersByTime(INITIAL_BACKOFF_MS);
    });
    expect(sockets).toHaveLength(2);
    expect(statuses[statuses.length - 1]).toBe("connecting");

    // Nueva caída (sin open): el siguiente backoff debe ser 2s.
    sockets[1].emitClose();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(sockets).toHaveLength(2); // aún no venció el delay de 2s
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(sockets).toHaveLength(3); // venció a los 2s

    vi.useRealTimers();
  });

  it("disconnect cancela el timer pendiente y cierra sin reconectar", () => {
    let clearedId: unknown = null;
    const scheduler: Scheduler = {
      setTimeout: () => 42 as unknown as ReturnType<typeof setTimeout>,
      clearTimeout: (id) => {
        clearedId = id;
      },
    };
    const stream = new BotStream("ws://test/ws/bot", factory, scheduler);
    stream.connect(
      () => {},
      () => {},
    );

    sockets[0].emitOpen();
    sockets[0].emitClose(); // agenda reconexión
    stream.disconnect();

    expect(clearedId).toBe(42);
    expect(sockets[0].closed).toBe(true);
    // Un cierre posterior no debe agendar nada nuevo ni crear sockets.
    sockets[0].emitClose();
    expect(sockets).toHaveLength(1);
  });
});

describe("useBotEvents", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("expone eventos (más reciente primero) y refleja el estado de conexión", () => {
    // Stream fake que captura los handlers para dispararlos manualmente.
    let onEvent: ((e: BotEvent) => void) | null = null;
    let onStatus: ((s: ConnectionStatus) => void) | null = null;
    const fakeStream = {
      connect: (e: (ev: BotEvent) => void, s: (st: ConnectionStatus) => void) => {
        onEvent = e;
        onStatus = s;
      },
      disconnect: vi.fn(),
    } as unknown as BotStream;

    const { result } = renderHook(() => useBotEvents(fakeStream));

    expect(result.current.events).toEqual([]);
    expect(result.current.connectionStatus).toBe("connecting");

    act(() => {
      onStatus?.("connected");
    });
    expect(result.current.connectionStatus).toBe("connected");

    const first = sampleEvent();
    const second = { ...sampleEvent(), order_id: "second" };
    act(() => {
      onEvent?.(first);
      onEvent?.(second);
    });

    // Más reciente primero.
    expect(result.current.events).toEqual([second, first]);
  });

  it("llama disconnect al desmontar", () => {
    const fakeStream = {
      connect: vi.fn(),
      disconnect: vi.fn(),
    } as unknown as BotStream;

    const { unmount } = renderHook(() => useBotEvents(fakeStream));
    unmount();
    expect(fakeStream.disconnect).toHaveBeenCalledTimes(1);
  });
});
