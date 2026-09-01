// Chart palette. SVG presentation attributes cannot reliably resolve CSS custom
// properties, so the chart components use these literal values. They mirror the
// tokens declared in `styles.css` (--buy, --sell, --border, --text-muted).
export const CHART_COLORS = {
  buy: "#16a34a",
  sell: "#dc2626",
  accent: "#f0b429",
  grid: "#e5e7eb",
  axis: "#e5e7eb",
  muted: "#6b7280",
} as const;

/**
 * Charts rely on `ResponsiveContainer`, which measures its parent through a
 * ResizeObserver. Headless DOM implementations (jsdom, used by the test suite)
 * do not provide one, and there is no viewport to measure anyway, so the chart
 * bodies are skipped there. In any real browser this always returns true.
 */
export function canRenderCharts(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.ResizeObserver !== "undefined"
  );
}
