// BotControls (R3): mode selector + Start/Stop control with in-flight disabling
// and current Bot_Status display. This component owns no domain logic: it renders
// the status handed down by the parent (App) and forwards user intent via the
// onStart/onStop callbacks. Error text is provided by the parent (which translates
// backend error_codes such as no_credentials / invalid_mode into clear messages);
// BotControls only renders it (R3.6, R3.7).
import { useState } from "react";
import type { BotStatus, Mode } from "../types";

export interface BotControlsProps {
  status: BotStatus;
  /** Disables Start/Stop while a request is in flight (R3.8). */
  busy: boolean;
  /** Disables the Start button while a start request is in flight. */
  starting?: boolean;
  /** Disables the Stop button while a stop request is in flight. */
  stopping?: boolean;
  onStart: (mode: Mode) => Promise<void>;
  onStop: () => Promise<void>;
  error?: string | null;
}

const MODES: Mode[] = ["random", "predictive"];

export function BotControls(props: BotControlsProps): JSX.Element {
  const { status, busy, starting, stopping, onStart, onStop, error } = props;

  // Local state for the selected mode; initialized from the current status
  // mode, falling back to "random" (R3.1).
  const [selectedMode, setSelectedMode] = useState<Mode>(
    status.mode ?? "random",
  );

  return (
    <section aria-label="Bot controls" style={{ marginTop: "1.5rem" }}>
      <h2>Control del bot</h2>

      {/* Current Bot_Status: state / mode / symbol (R3.5). */}
      <div style={{ marginBottom: "1rem" }}>
        <span data-testid="bot-state">Estado: {status.state}</span>
        {" · "}
        <span data-testid="bot-mode">Modo: {status.mode}</span>
        {" · "}
        <span data-testid="bot-symbol">Símbolo: {status.symbol}</span>
      </div>

      {/* Mode selector between "random" and "predictive" (R3.1). */}
      <div style={{ marginBottom: "1rem" }}>
        <label htmlFor="bot-mode-select">Modo de operación</label>{" "}
        <select
          id="bot-mode-select"
          aria-label="Modo de operación"
          value={selectedMode}
          disabled={busy || starting}
          onChange={(e) => setSelectedMode(e.target.value as Mode)}
        >
          {MODES.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
      </div>

      {/* Start / Stop — each button disables only while its own operation is in
          flight (R3.8). Stop must never depend on Start's in-flight state so a
          hung start request can never block the user from stopping the bot
          (product principle: reversibility and control). */}
      <div style={{ display: "flex", gap: "0.5rem" }}>
        <button
          type="button"
          disabled={busy || starting}
          onClick={() => {
            void onStart(selectedMode);
          }}
        >
          Start
        </button>
        <button
          type="button"
          disabled={stopping}
          onClick={() => {
            void onStop();
          }}
        >
          Stop
        </button>
      </div>

      {/* Error message provided by the parent (R3.6, R3.7). */}
      {error && (
        <p role="alert" style={{ color: "#842029", marginTop: "1rem" }}>
          {error}
        </p>
      )}
    </section>
  );
}
