import { useState } from "react";
import { apiClient } from "./services/apiClient";

type ConnectionState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; detail: string }
  | { kind: "error"; detail: string };

export function App() {
  const [state, setState] = useState<ConnectionState>({ kind: "idle" });

  async function testConnection() {
    setState({ kind: "loading" });
    try {
      const health = await apiClient.health();
      setState({ kind: "ok", detail: JSON.stringify(health) });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setState({ kind: "error", detail: message });
    }
  }

  return (
    <main
      style={{
        fontFamily: "system-ui, sans-serif",
        maxWidth: 640,
        margin: "0 auto",
        padding: "2rem",
      }}
    >
      <h1>TradeBot</h1>

      {/* Indicador de entorno: siempre visible (R4). */}
      <p
        style={{
          display: "inline-block",
          background: "#fff3cd",
          color: "#664d03",
          border: "1px solid #ffe69c",
          borderRadius: 6,
          padding: "0.35rem 0.75rem",
          fontWeight: 600,
        }}
      >
        Paper Trading (dinero ficticio)
      </p>

      <section style={{ marginTop: "2rem" }}>
        <button onClick={testConnection} disabled={state.kind === "loading"}>
          Probar conexión con el backend
        </button>

        <div style={{ marginTop: "1rem" }}>
          {state.kind === "idle" && (
            <span>Pulsa el botón para comprobar el backend.</span>
          )}
          {state.kind === "loading" && <span>Comprobando…</span>}
          {state.kind === "ok" && (
            <span style={{ color: "#0f5132" }}>
              Conexión OK: {state.detail}
            </span>
          )}
          {state.kind === "error" && (
            <span style={{ color: "#842029" }}>
              Error de conexión: {state.detail}
            </span>
          )}
        </div>
      </section>
    </main>
  );
}
