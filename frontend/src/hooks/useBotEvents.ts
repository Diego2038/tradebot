// Hook que administra el ciclo de vida del BotStream para un componente:
// conecta al montar, va acumulando eventos (más reciente primero) y expone el
// estado de conexión; desconecta al desmontar (R4.1, R4.3, R4.5).

import { useEffect, useRef, useState } from "react";
import type { BotEvent, ConnectionStatus } from "../types";
import { BotStream } from "../services/botStream";

export interface UseBotEvents {
  events: BotEvent[]; // más reciente primero (R4.3)
  connectionStatus: ConnectionStatus;
}

/**
 * Posee un BotStream durante la vida del componente. El parámetro opcional
 * `stream` permite inyectar un doble en los tests.
 */
export function useBotEvents(stream?: BotStream): UseBotEvents {
  const [events, setEvents] = useState<BotEvent[]>([]);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");

  // Mantiene una referencia estable al stream durante la vida del componente.
  const streamRef = useRef<BotStream | null>(null);
  if (streamRef.current === null) {
    streamRef.current = stream ?? new BotStream();
  }

  useEffect(() => {
    const current = streamRef.current;
    if (!current) {
      return;
    }
    current.connect(
      (event) => setEvents((prev) => [event, ...prev]), // prepend: newest first
      (status) => setConnectionStatus(status),
    );
    return () => {
      current.disconnect();
    };
    // Solo al montar/desmontar; el stream se fija una vez.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { events, connectionStatus };
}
