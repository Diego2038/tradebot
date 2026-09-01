// EquityChart: purely presentational chart of the simulated equity curve for a
// backtest result. It derives nothing that the backend does not already send —
// the running equity is just the cumulative sum of the realized P&L of each
// trade on top of `starting_equity`, which is a presentation concern (drawing
// the same numbers the trades table already shows, in order).
//
// No domain logic, no I/O, no state: props in, SVG out.
import {
  Area,
  CartesianGrid,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import type { BacktestResult } from "../types";
import { CHART_COLORS, canRenderCharts } from "./chartTheme";

export interface EquityChartProps {
  result: BacktestResult;
}

/** A single point of the equity curve. */
interface EquityPoint {
  index: number;
  equity: number;
  timeLabel: string;
  timestamp: string | null;
  side: string | null;
  price: string | null;
  pnl: string | null;
  /** Equity at this point when the trade was a buy, otherwise null. */
  buyEquity: number | null;
  /** Equity at this point when the trade was a sell, otherwise null. */
  sellEquity: number | null;
}

/** Parses a decimal-as-string safely; non-numeric values count as zero. */
function toNumber(value: string | null | undefined): number {
  if (value == null || value === "") {
    return 0;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Short, locale-independent time label for the X axis. */
function timeLabelOf(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return timestamp;
  }
  const day = String(parsed.getUTCDate()).padStart(2, "0");
  const month = String(parsed.getUTCMonth() + 1).padStart(2, "0");
  const hours = String(parsed.getUTCHours()).padStart(2, "0");
  const minutes = String(parsed.getUTCMinutes()).padStart(2, "0");
  return `${day}/${month} ${hours}:${minutes}`;
}

/** Compact money formatting for the Y axis (e.g. 101.2k). */
function compactMoney(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(2)}M`;
  }
  if (abs >= 1_000) {
    return `${(value / 1_000).toFixed(1)}k`;
  }
  return value.toFixed(0);
}

/** Full money formatting for the tooltip. */
function fullMoney(value: number): string {
  return value.toLocaleString("es-ES", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Human label for a trade side. */
function sideLabel(side: string | null): string {
  const normalized = (side ?? "").toLowerCase();
  if (normalized === "buy") {
    return "compra";
  }
  if (normalized === "sell") {
    return "venta";
  }
  return side ?? "—";
}

/** Builds the equity series: starting equity, then cumulative realized P&L. */
function buildSeries(result: BacktestResult): EquityPoint[] {
  const startingEquity = toNumber(result.starting_equity);
  const points: EquityPoint[] = [
    {
      index: 0,
      equity: startingEquity,
      timeLabel: "inicio",
      timestamp: null,
      side: null,
      price: null,
      pnl: null,
      buyEquity: null,
      sellEquity: null,
    },
  ];

  let equity = startingEquity;
  result.trades.forEach((trade, i) => {
    equity += toNumber(trade.realized_profit);
    const normalizedSide = (trade.side ?? "").toLowerCase();
    points.push({
      index: i + 1,
      equity,
      timeLabel: timeLabelOf(trade.timestamp),
      timestamp: trade.timestamp,
      side: trade.side,
      price: trade.price,
      pnl: trade.realized_profit,
      buyEquity: normalizedSide === "buy" ? equity : null,
      sellEquity: normalizedSide === "sell" ? equity : null,
    });
  });

  return points;
}

function EquityTooltip(props: TooltipProps<number, string>): JSX.Element | null {
  const { active, payload } = props;
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  const point = payload[0].payload as EquityPoint | undefined;
  if (!point) {
    return null;
  }

  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__title">
        {point.timestamp ? point.timeLabel : "Equity inicial"}
      </div>
      <div className="chart-tooltip__row">
        Equity: <strong>{fullMoney(point.equity)}</strong>
      </div>
      {point.timestamp && (
        <>
          <div className="chart-tooltip__row">
            Lado: <strong>{sideLabel(point.side)}</strong>
          </div>
          <div className="chart-tooltip__row">
            Precio: <strong>{point.price ?? "—"}</strong>
          </div>
          <div className="chart-tooltip__row">
            P&amp;L: <strong>{point.pnl ?? "—"}</strong>
          </div>
        </>
      )}
    </div>
  );
}

export function EquityChart(props: EquityChartProps): JSX.Element {
  const { result } = props;

  if (result.trades.length === 0) {
    return (
      <p className="empty-state">
        Sin operaciones simuladas: no hay curva de equity que dibujar.
      </p>
    );
  }

  // No measurable viewport (headless DOM): skip the SVG body entirely.
  if (!canRenderCharts()) {
    return <div className="chart" data-testid="equity-chart-skipped" />;
  }

  const data = buildSeries(result);
  const startingEquity = toNumber(result.starting_equity);
  const finalEquity = toNumber(result.final_equity);
  const up = finalEquity >= startingEquity;
  const stroke = up ? CHART_COLORS.buy : CHART_COLORS.sell;
  const gradientId = up ? "equity-gradient-up" : "equity-gradient-down";

  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={data}
          margin={{ top: 8, right: 12, bottom: 4, left: 4 }}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.28} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0.02} />
            </linearGradient>
          </defs>

          <CartesianGrid
            vertical={false}
            stroke={CHART_COLORS.grid}
            strokeDasharray="3 3"
          />
          <XAxis
            dataKey="timeLabel"
            tick={{ fill: CHART_COLORS.muted, fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: CHART_COLORS.axis }}
            minTickGap={24}
          />
          <YAxis
            tick={{ fill: CHART_COLORS.muted, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={56}
            domain={["auto", "auto"]}
            tickFormatter={compactMoney}
          />
          <Tooltip content={<EquityTooltip />} />

          {/* Baseline at the starting equity: above it the run is profitable. */}
          <ReferenceLine
            y={startingEquity}
            stroke={CHART_COLORS.muted}
            strokeDasharray="4 4"
            strokeOpacity={0.6}
          />

          <Area
            type="monotone"
            dataKey="equity"
            stroke={stroke}
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0, fill: stroke }}
            isAnimationActive={false}
          />

          {/* Buy / sell markers, only on points that correspond to a trade. */}
          <Scatter dataKey="buyEquity" fill={CHART_COLORS.buy} shape="circle" />
          <Scatter dataKey="sellEquity" fill={CHART_COLORS.sell} shape="circle" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
