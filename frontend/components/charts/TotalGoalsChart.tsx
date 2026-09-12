"use client";

// Distribution of total goals in the match, split at the 2.5 line.
//
// Magnitude by category, so bars. The split is the whole point of the chart,
// so each bar is filled by the side of the line it falls on and both sides are
// named in the legend and in the tooltip.

import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  CHART,
  asNumber,
  axisLine,
  axisTick,
  payloadOf,
  tooltipStyles,
} from "./chartTheme";
import type { TotalGoalsBucket } from "@/lib/types";

interface Props {
  data: TotalGoalsBucket[];
  line?: number;
}

interface Row {
  total: number;
  probability: number;
  percent: number;
  side: "สูง" | "ต่ำ";
}

export default function TotalGoalsChart({ data, line = 2.5 }: Props) {
  const rows: Row[] = data
    .filter((bucket) => bucket.probability >= 0.002)
    .map((bucket) => ({
      total: bucket.total_goals,
      probability: bucket.probability,
      percent: bucket.probability * 100,
      side: bucket.total_goals > line ? "สูง" : "ต่ำ",
    }));

  // The reference line sits between the last Under bar and the first Over bar.
  const splitIndex = rows.findIndex((row) => row.side === "สูง");

  return (
    <figure className="m-0">
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 18, right: 8, bottom: 4, left: -18 }}>
            <XAxis
              dataKey="total"
              tick={axisTick}
              axisLine={axisLine}
              tickLine={false}
              label={{
                value: "จำนวนประตูรวมในนัดนั้น",
                position: "insideBottom",
                offset: -2,
                fill: CHART.inkMuted,
                fontSize: 11,
              }}
            />
            <YAxis
              tick={axisTick}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value: number) => `${value.toFixed(0)}%`}
              width={48}
            />
            <Tooltip
              {...tooltipStyles}
              formatter={(value: unknown, _name: unknown, entry: unknown) => [
                `${asNumber(value).toFixed(1)}%`,
                `${payloadOf<Row>(entry)?.side ?? ""} ${line}`,
              ]}
              labelFormatter={(label: unknown) => `${asNumber(label)} ประตู`}
            />
            {splitIndex > 0 ? (
              <ReferenceLine
                x={rows[splitIndex].total}
                stroke={CHART.baseline}
                strokeDasharray="3 3"
                label={{
                  value: `เส้น ${line}`,
                  position: "top",
                  fill: CHART.inkMuted,
                  fontSize: 10,
                }}
              />
            ) : null}
            <Bar dataKey="percent" radius={[4, 4, 0, 0]} maxBarSize={44}>
              <LabelList
                dataKey="percent"
                position="top"
                fill={CHART.inkMuted}
                fontSize={10}
                formatter={(value: unknown) => {
                  const percentage = asNumber(value);
                  return percentage >= 6 ? `${percentage.toFixed(0)}%` : "";
                }}
              />
              {rows.map((row) => (
                <Cell
                  key={row.total}
                  fill={row.side === "สูง" ? CHART.over : CHART.under}
                  stroke={CHART.surface}
                  strokeWidth={2}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        <LegendSwatch color={CHART.under} label={`ต่ำ ${line}`} />
        <LegendSwatch color={CHART.over} label={`สูง ${line}`} />
        <span>ความน่าจะเป็นของประตูรวมแต่ละค่า รวมกันได้ 100%</span>
      </figcaption>
    </figure>
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="h-2.5 w-2.5 rounded-sm"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}
