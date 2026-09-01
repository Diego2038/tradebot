// BacktestPanel (spec 05 UI): runs a strategy simulation over historical BTC/USD
// data without trading for real. This is a presentation component: it owns no
// domain logic. It gathers the run parameters (mode, timeframe, date range and an
// optional seed) into a BacktestRunRequest and forwards user intent through the
// onRun callback. Metrics, the trades table and any error text are handed down by
// the parent (App), which translates backend error_codes into clear messages.
//
// Presentation only: the form is laid out on a responsive grid, the metrics are
// KPI tiles and the equity curve is drawn above the trades table. Every test id,
// label and value text is unchanged.
import { useState } from "react";
import type {
  BacktestResult,
  BacktestRunRequest,
  Mode,
  Timeframe,
} from "../types";
import { EquityChart } from "./EquityChart";

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

// Badge colour variant for a trade side; unknown values stay neutral.
function sideVariant(value: string): string {
  const normalized = value.toUpperCase();
  if (normalized === "BUY") {
    return "badge--buy";
  }
  if (normalized === "SELL") {
    return "badge--sell";
  }
  return "badge--neutral";
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
    <section aria-label="Backtest" className="card">
      <div className="card__header">
        <div className="card__heading">
          <h2 className="card__title">Backtest</h2>
          <p className="card__subtitle">
            Simula una estrategia sobre datos históricos de BTC/USD sin operar
            en real.
          </p>
        </div>
      </div>

      <div className="card__body">
        <form onSubmit={handleSubmit} className="card__body-form">
          <div className="grid grid--3col">
            {/* Mode selector between "random" and "predictive". */}
            <div className="field">
              <label className="field__label" htmlFor="backtest-mode-select">
                Modo
              </label>
              <select
                id="backtest-mode-select"
                className="select"
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
            <div className="field">
              <label
                className="field__label"
                htmlFor="backtest-timeframe-select"
              >
                Timeframe
              </label>
              <select
                id="backtest-timeframe-select"
                className="select"
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

            {/* Optional seed for deterministic reproducibility. */}
            <div className="field">
              <label className="field__label" htmlFor="backtest-seed">
                Seed (opcional)
              </label>
              <input
                id="backtest-seed"
                className="input"
                type="number"
                value={seed}
                disabled={busy}
                onChange={(e) => setSeed(e.target.value)}
              />
            </div>

            {/* Date range: datetime-local inputs, normalized to ISO 8601 UTC on submit. */}
            <div className="field">
              <label className="field__label" htmlFor="backtest-start">
                Inicio
              </label>
              <input
                id="backtest-start"
                className="input"
                type="datetime-local"
                value={start}
                disabled={busy}
                onChange={(e) => setStart(e.target.value)}
              />
            </div>

            <div className="field">
              <label className="field__label" htmlFor="backtest-end">
                Fin
              </label>
              <input
                id="backtest-end"
                className="input"
                type="datetime-local"
                value={end}
                disabled={busy}
                onChange={(e) => setEnd(e.target.value)}
              />
            </div>

            {/* Optional position size: drives how meaningful the percentages are. */}
            <div className="field">
              <label className="field__label" htmlFor="backtest-qty">
                Tamaño de posición (BTC)
              </label>
              <input
                id="backtest-qty"
                className="input"
                type="number"
                step="0.001"
                min="0"
                value={qtyStr}
                disabled={busy}
                onChange={(e) => setQtyStr(e.target.value)}
              />
              <p className="help-text">
                Por defecto 0.001 BTC (~0,08% del capital simulado de 100.000),
                por lo que los porcentajes salen muy pequeños. Un valor mayor
                (p.ej. 1) da métricas con significado.
              </p>
            </div>
          </div>

          <div className="form-actions">
            <button
              type="submit"
              className="btn btn--primary"
              aria-label="Ejecutar backtest"
              disabled={busy}
            >
              Ejecutar backtest
            </button>
          </div>
        </form>

        {/* Discreet in-flight indicator. */}
        {busy && (
          <p data-testid="backtest-busy" className="busy-text">
            Ejecutando backtest…
          </p>
        )}

        {/* Metrics summary + trades table when a result is available. */}
        {result && (
          <div data-testid="backtest-result" className="backtest-result">
            <div className="kpi-row">
              <div className="kpi">
                <span data-testid="bt-total-return" className="kpi__value">
                  <span className="kpi__inline-label">Retorno total: </span>
                  {result.total_return}
                </span>
              </div>
              <div className="kpi">
                <span data-testid="bt-trade-count" className="kpi__value">
                  <span className="kpi__inline-label">Operaciones: </span>
                  {result.trade_count}
                </span>
              </div>
              <div className="kpi">
                <span data-testid="bt-win-rate" className="kpi__value">
                  <span className="kpi__inline-label">Win rate: </span>
                  {result.win_rate}
                </span>
              </div>
              <div className="kpi">
                <span data-testid="bt-max-drawdown" className="kpi__value">
                  <span className="kpi__inline-label">Drawdown máx.: </span>
                  {result.max_drawdown}
                </span>
              </div>
              <div className="kpi">
                <span data-testid="bt-bars-evaluated" className="kpi__value">
                  <span className="kpi__inline-label">Barras evaluadas: </span>
                  {result.bars_evaluated}
                </span>
              </div>
            </div>

            {/* Absolute figures: the same result read in money instead of ratios. */}
            <div className="kpi-row">
              <div className="kpi">
                <span data-testid="bt-net-profit" className="kpi__value">
                  <span className="kpi__inline-label">P&amp;L neto: </span>
                  {result.net_profit}
                </span>
              </div>
              <div className="kpi">
                <span data-testid="bt-final-equity" className="kpi__value">
                  <span className="kpi__inline-label">Equity final: </span>
                  {result.final_equity}
                </span>
              </div>
              <div className="kpi">
                <span data-testid="bt-starting-equity" className="kpi__value">
                  <span className="kpi__inline-label">Equity inicial: </span>
                  {result.starting_equity}
                </span>
              </div>
            </div>

            {/* Equity curve for this run (presentation of the same trades). */}
            <h3 className="section-title">Curva de equity</h3>
            <EquityChart result={result} />

            <h3 className="section-title">Operaciones simuladas</h3>

            {result.trades.length === 0 ? (
              // Discreet empty state.
              <p data-testid="bt-trades-empty" className="empty-state">
                Sin operaciones simuladas
              </p>
            ) : (
              <div className="table-wrap">
                <table data-testid="bt-trades-table" className="table">
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
                        <td data-testid="bt-trade-side">
                          {cell(trade.side) === "—" ? (
                            <span className="cell--muted">—</span>
                          ) : (
                            <span
                              className={`badge ${sideVariant(cell(trade.side))}`}
                            >
                              {cell(trade.side)}
                            </span>
                          )}
                        </td>
                        <td data-testid="bt-trade-qty" className="cell--num">
                          {cell(trade.qty)}
                        </td>
                        <td data-testid="bt-trade-price" className="cell--num">
                          {cell(trade.price)}
                        </td>
                        <td
                          data-testid="bt-trade-timestamp"
                          className="cell--muted"
                        >
                          {cell(trade.timestamp)}
                        </td>
                        <td data-testid="bt-trade-pnl" className="cell--num">
                          {cell(trade.realized_profit)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Error message provided by the parent. */}
        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
