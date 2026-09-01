// ActivityChart: purely presentational live price chart built from the bot
// events already rendered by the Dashboard table. It reads only the fields the
// events carry (price, side, timestamp) and never mutates the array it receives.
//
// Many events (e.g. SUBMITTED) arrive with a null price; those cannot be plotted,
// so the chart falls back to a discreet explanation until priced executions show
// up.
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import type { BotEvent } from "../types";
import { CHART_COLORS, canRenderCharts } from "./chartTheme";

export interface ActivityChartProps {
  events: BotEvent[];
}

interface ActivityPoint {
  index: number;
  price: number;
  timeLabel: string;
  eventType: string;
  side: string | null;
  qty: string | null;
  buyPrice: number | null;
  sellPrice: number | null;
}

/** Parses a decimal-as-string; returns null when it is not a finite number. */
function parsePrice(value: string | null): number | null {
  if (value == null || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Short, locale-independent time label for the X axis. */
function timeLabelOf(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return timestamp;
  }
  const hours = String(parsed.getUTCHours()).padStart(2, "0");
  const minutes = String(parsed.getUTCMinutes()).padStart(2, "0");
  const seconds = String(parsed.getUTCSeconds()).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

function compactPrice(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000) {
    return `${(value / 1_000).toFixed(1)}k`;
  }
  return value.toFixed(2);
}

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

/**
 * Builds the chronological price series. Events arrive most-recent-first, so a
 * copy is reversed (never the received array) to draw time left-to-right.
 */
function buildSeries(events: BotEvent[]): ActivityPoint[] {
  const chronological = [...events].reverse();
  const points: ActivityPoint[] = [];

  chronological.forEach((event) => {
    const price = parsePrice(event.price);
    if (price == null) {
      return;
    }
    const normalizedSide = (event.side ?? "").toLowerCase();
    points.push({
      index: points.length,
      price,
      timeLabel: timeLabelOf(event.timestamp),
      eventType: event.event_type,
      side: event.side,
      qty: event.qty,
      buyPrice: normalizedSide === "buy" ? price : null,
      sellPrice: normalizedSide === "sell" ? price : null,
    });
  });

  return points;
}

function ActivityTooltip(
  props: TooltipProps<number, string>,
): JSX.Element | null {
  const { active, payload } = props;
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  const point = payload[0].payload as ActivityPoint | undefined;
  if (!point) {
    return null;
  }

  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__title">{point.timeLabel}</div>
      <div className="chart-tooltip__row">
        Precio: <strong>{point.price.toLocaleString("es-ES")}</strong>
      </div>
      <div className="chart-tooltip__row">
        Tipo: <strong>{point.eventType}</strong>
      </div>
      <div className="chart-tooltip__row">
        Lado: <strong>{sideLabel(point.side)}</strong>
      </div>
      <div className="chart-tooltip__row">
        Cantidad: <strong>{point.qty ?? "—"}</strong>
      </div>
    </div>
  );
}

export function ActivityChart(props: ActivityChartProps): JSX.Element {
  const { events } = props;
  const data = buildSeries(events);

  if (data.length === 0) {
    return (
      <p className="empty-state">
        Todavía no hay eventos con precio: los eventos de tipo SUBMITTED llegan
        sin precio. La gráfica se dibuja cuando lleguen ejecuciones con precio.
      </p>
    );
  }

  // No measurable viewport (headless DOM): skip the SVG body entirely.
  if (!canRenderCharts()) {
    return <div className="chart chart--sm" data-testid="activity-chart-skipped" />;
  }

  return (
    <div className="chart chart--sm">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={data}
          margin={{ top: 8, right: 12, bottom: 4, left: 4 }}
        >
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
            tickFormatter={compactPrice}
          />
          <Tooltip content={<ActivityTooltip />} />

          <Line
            type="monotone"
            dataKey="price"
            stroke={CHART_COLORS.accent}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0, fill: CHART_COLORS.accent }}
            isAnimationActive={false}
          />

          {/* Buy / sell execution markers. */}
          <Scatter dataKey="buyPrice" fill={CHART_COLORS.buy} shape="circle" />
          <Scatter dataKey="sellPrice" fill={CHART_COLORS.sell} shape="circle" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
