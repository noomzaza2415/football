// Shared chart chrome. Recharts takes literal colours rather than CSS
// utilities, so the tokens from globals.css are repeated here once and every
// chart reads them from this module.

export const CHART = {
  surface: "#1a1a19",
  raised: "#232321",
  grid: "#2c2c2a",
  baseline: "#383835",
  ink: "#ffffff",
  inkSecondary: "#c3c2b7",
  inkMuted: "#898781",
  // Over is warm, Under is cool. Both always carry a text label as well, so
  // the two are never told apart by hue alone.
  over: "#d95926",
  under: "#3987e5",
  accent: "#199e70",
  good: "#0ca30c",
  critical: "#d03b3b",
} as const;

export const axisTick = {
  fill: CHART.inkMuted,
  fontSize: 11,
} as const;

export const axisLine = { stroke: CHART.baseline } as const;

export const tooltipStyles = {
  contentStyle: {
    background: CHART.raised,
    border: `1px solid ${CHART.grid}`,
    borderRadius: 10,
    fontSize: 12,
    padding: "8px 10px",
    boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
  },
  labelStyle: { color: CHART.inkSecondary, marginBottom: 4, fontWeight: 600 },
  itemStyle: { color: CHART.ink },
  cursor: { fill: "rgba(255,255,255,0.05)" },
} as const;

/** Recharts hands the legend an unknown-shaped payload; keep the label text. */
export const legendStyles = {
  wrapperStyle: { fontSize: 12, color: CHART.inkSecondary, paddingTop: 8 },
} as const;

/** Recharts 3 hands formatter callbacks loosely typed values; narrow them here. */
export function asNumber(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Pull the original row back out of a tooltip or label entry. */
export function payloadOf<T>(entry: unknown): T | undefined {
  return (entry as { payload?: T } | undefined)?.payload;
}
