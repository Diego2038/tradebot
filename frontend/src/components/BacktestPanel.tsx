// BacktestPanel (spec 05 UI): runs a strategy simulation over historical BTC/USD
// data without trading for real. This is a presentation component: it owns no
// domain logic. It gathers the run parameters (mode, timeframe, date range and an
// optional seed) into a BacktestRunRequest and forwards user intent through the
// onRun callback. Metrics, the trades table and any error text are handed down by
// the parent (App), which translates backend error_codes into clear messages.
import { useState } from "react";
import type {
  BacktestResult,
  BacktestRunRequest,
  Mode,
  Timeframe,
} from "../types";

export interface BacktestPanelProps {
  onRun: (req: BacktestRunRequest) => Promise<void>;
  result: BacktestResult | null;
  busy: boolean;
  error?: string | null;
}

const MODES: Mode[] = ["random", "predictive"];
const TIMEFRAMES: Timeframe[] = ["1Min", "5Min", "15Min", "1Hour", "1Day"];

// Renders a possibly-null field value with a dash placeholder when absent
// (same pattern as Dashboard.tsx).
function cell(value: string | null): string {
  return value == null || value === "" ? "—" : value;
}

/**
 * Converts a value from an <input type="datetime-local"> (a local, timezone-less
 * string like "2024-01-01T00:00") into an ISO 8601 UTC string. We use
 * datetime-local for a robust, native date/time picker and normalize to UTC at
 * submit time so the backend always receives an unambiguous instant. Empty input
 * yields an empty string so the parent can surface the resulting range error.
 */
function toIsoUtc(local: string): string {
  if (!local) {
    return "";
  }
  const parsed = new Date(local);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return parsed.toISOString();
}

export function BacktestPanel(props: BacktestPanelProps): JSX.Element {
  const { onRun, result, busy, error } = props;

  const [mode, setMode] = useState<Mode>("random");
  const [timeframe, setTimeframe] = useState<Timeframe>("1Min");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [seed, setSeed] = useState("");
  const [qtyStr, setQtyStr] = useState("");

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
    e.preventDefault();
    const req: BacktestRunRequest = {
      mode,
      start: toIsoUtc(start),
      end: toIsoUtc(end),
      symbol: "BTC/USD",
      timeframe,
      // Optional seed: only send a number when provided; otherwise null lets the
      // backend pick its own default.
      seed: seed.trim() === "" ? null : Number(seed),
      // Optional position size: null means "use the engine default" (0.001 BTC).
      qty: qtyStr.trim() === "" ? null : Number(qtyStr),
    };
    void onRun(req);
  };

  return (
    <section aria-label="Backtest" style={{ marginTop: "1.5rem" }}>
      <h2>Backtest</h2>
      <p style={{ color: "#6c757d", marginTop: "-0.5rem" }}>
        Simula una estrategia sobre datos históricos de BTC/USD sin operar en
        real.
      </p>

      <form onSubmit={handleSubmit}>
        {/* Mode selector between "random" and "predictive". */}
        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="backtest-mode-select">Modo</label>{" "}
          <select
            id="backtest-mode-select"
            aria-label="Modo de backtest"
            value={mode}
            disabled={busy}
            onChange={(e) => setMode(e.target.value as Mode)}
          >
            {MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>

        {/* Timeframe selector (5 valid values). */}
        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="backtest-timeframe-select">Timeframe</label>{" "}
          <select
            id="backtest-timeframe-select"
            aria-label="Timeframe"
            value={timeframe}
            disabled={busy}
            onChange={(e) => setTimeframe(e.target.value as Timeframe)}
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </div>

        {/* Date range: datetime-local inputs, normalized to ISO 8601 UTC on submit. */}
        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="backtest-start">Inicio</label>{" "}
          <input
            id="backtest-start"
            type="datetime-local"
            value={start}
            disabled={busy}
            onChange={(e) => setStart(e.target.value)}
          />
        </div>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="backtest-end">Fin</label>{" "}
          <input
            id="backtest-end"
            type="datetime-local"
            value={end}
            disabled={busy}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>

        {/* Optional position size: drives how meaningful the percentages are. */}
        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="backtest-qty">Tamaño de posición (BTC)</label>{" "}
          <input
            id="backtest-qty"
            type="number"
            step="0.001"
            min="0"
            value={qtyStr}
            disabled={busy}
            onChange={(e) => setQtyStr(e.target.value)}
          />
          <p
            style={{
              color: "#6c757d",
              fontSize: "0.85rem",
              margin: "0.25rem 0 0",
            }}
          >
            Por defecto 0.001 BTC (~0,08% del capital simulado de 100.000), por lo
            que los porcentajes salen muy pequeños. Un valor mayor (p.ej. 1) da
            métricas con significado.
          </p>
        </div>

        {/* Optional seed for deterministic reproducibility. */}
        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="backtest-seed">Seed (opcional)</label>{" "}
          <input
            id="backtest-seed"
            type="number"
            value={seed}
            disabled={busy}
            onChange={(e) => setSeed(e.target.value)}
          />
        </div>

        <button type="submit" aria-label="Ejecutar backtest" disabled={busy}>
          Ejecutar backtest
        </button>
      </form>

      {/* Discreet in-flight indicator. */}
      {busy && (
        <p data-testid="backtest-busy" style={{ color: "#6c757d" }}>
          Ejecutando backtest…
        </p>
      )}

      {/* Metrics summary + trades table when a result is available. */}
      {result && (
        <div data-testid="backtest-result" style={{ marginTop: "1rem" }}>
          <div style={{ marginBottom: "1rem" }}>
            <span data-testid="bt-total-return">
              Retorno total: {result.total_return}
            </span>
            {" · "}
            <span data-testid="bt-trade-count">
              Operaciones: {result.trade_count}
            </span>
            {" · "}
            <span data-testid="bt-win-rate">Win rate: {result.win_rate}</span>
            {" · "}
            <span data-testid="bt-max-drawdown">
              Drawdown máx.: {result.max_drawdown}
            </span>
            {" · "}
            <span data-testid="bt-bars-evaluated">
              Barras evaluadas: {result.bars_evaluated}
            </span>
          </div>

          {/* Absolute figures: the same result read in money instead of ratios. */}
          <div style={{ marginBottom: "1rem" }}>
            <span data-testid="bt-net-profit">
              P&amp;L neto: {result.net_profit}
            </span>
            {" · "}
            <span data-testid="bt-final-equity">
              Equity final: {result.final_equity}
            </span>
            {" · "}
            <span data-testid="bt-starting-equity">
              Equity inicial: {result.starting_equity}
            </span>
          </div>

          {result.trades.length === 0 ? (
            // Discreet empty state.
            <p data-testid="bt-trades-empty" style={{ color: "#6c757d" }}>
              Sin operaciones simuladas
            </p>
          ) : (
            <table data-testid="bt-trades-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th scope="col">Lado</th>
                  <th scope="col">Cantidad</th>
                  <th scope="col">Precio</th>
                  <th scope="col">Timestamp</th>
                  <th scope="col">P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {result.trades.map((trade, index) => (
                  <tr
                    key={`${trade.timestamp}-${index}`}
                    data-testid="bt-trade-row"
                  >
                    <td data-testid="bt-trade-side">{cell(trade.side)}</td>
                    <td data-testid="bt-trade-qty">{cell(trade.qty)}</td>
                    <td data-testid="bt-trade-price">{cell(trade.price)}</td>
                    <td data-testid="bt-trade-timestamp">
                      {cell(trade.timestamp)}
                    </td>
                    <td data-testid="bt-trade-pnl">
                      {cell(trade.realized_profit)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Error message provided by the parent. */}
      {error && (
        <p role="alert" style={{ color: "#842029", marginTop: "1rem" }}>
          {error}
        </p>
      )}
    </section>
  );
}
