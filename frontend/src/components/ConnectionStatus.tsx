// ConnectionStatus (R4.5): renders the current WebSocket connection status in a
// visible way (text + color) so the user always knows whether the real-time
// stream is connected, connecting, or disconnected.
//
// Presentation only: the colour now comes from a CSS pill variant instead of an
// inline hex value. The labels, role, test id and `data-status` are unchanged.
import type { ConnectionStatus as ConnectionStatusValue } from "../types";

export interface ConnectionStatusProps {
  status: ConnectionStatusValue;
}

const LABELS: Record<ConnectionStatusValue, string> = {
  connected: "Conectado",
  connecting: "Conectando…",
  disconnected: "Desconectado",
};

const VARIANTS: Record<ConnectionStatusValue, string> = {
  connected: "pill--ok",
  connecting: "pill--warn",
  disconnected: "pill--danger",
};

export function ConnectionStatus(props: ConnectionStatusProps): JSX.Element {
  const { status } = props;

  return (
    <span
      data-testid="connection-status"
      data-status={status}
      role="status"
      aria-live="polite"
      className={`pill ${VARIANTS[status]}`}
    >
      <span className="pill__dot" aria-hidden="true" />
      {LABELS[status]}
    </span>
  );
}
