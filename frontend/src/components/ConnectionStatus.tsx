// ConnectionStatus (R4.5): renders the current WebSocket connection status in a
// visible way (text + color) so the user always knows whether the real-time
// stream is connected, connecting, or disconnected.
import type { ConnectionStatus as ConnectionStatusValue } from "../types";

export interface ConnectionStatusProps {
  status: ConnectionStatusValue;
}

const LABELS: Record<ConnectionStatusValue, string> = {
  connected: "Conectado",
  connecting: "Conectando…",
  disconnected: "Desconectado",
};

const COLORS: Record<ConnectionStatusValue, string> = {
  connected: "#0f5132", // green
  connecting: "#664d03", // amber
  disconnected: "#842029", // red
};

export function ConnectionStatus(props: ConnectionStatusProps): JSX.Element {
  const { status } = props;

  return (
    <span
      data-testid="connection-status"
      data-status={status}
      role="status"
      aria-live="polite"
      style={{ color: COLORS[status], fontWeight: 600 }}
    >
      {LABELS[status]}
    </span>
  );
}
