"use client";

// Over probability at each available line, as a horizontal bar per line.
//
// One measure across a handful of named lines, so horizontal bars: the line
// labels read left to right and nothing has to be rotated.

import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART, asNumber, axisTick, tooltipStyles } from "./chartTheme";
import type { LineProbability } from "@/lib/types";

interface Row {
  label: string;
  over: number;
  under: number;
}

export default function LinesChart({ lines }: { lines: LineProbability[] }) {
  const rows: Row[] = lines.map((entry) => ({
    label: `สูง/ต่ำ ${entry.line}`,
    over: entry.prob_over * 100,
    under: entry.prob_under * 100,
  }));

  return (
    <figure className="m-0">
      <div className="w-full" style={{ height: Math.max(rows.length * 52, 140) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 4, right: 56, bottom: 4, left: 4 }}
          >
            <XAxis type="number" domain={[0, 100]} hide />
            <YAxis
              type="category"
              dataKey="label"
              tick={{ ...axisTick, fill: CHART.inkSecondary }}
              axisLine={false}
              tickLine={false}
              width={80}
            />
            <Tooltip
              {...tooltipStyles}
              formatter={(value: unknown, name: unknown) => [
                `${asNumber(value).toFixed(1)}%`,
                name === "over" ? "สูง" : "ต่ำ",
              ]}
            />
            <Bar dataKey="over" radius={[0, 4, 4, 0]} maxBarSize={22}>
              <LabelList
                dataKey="over"
                position="right"
                fill={CHART.inkSecondary}
                fontSize={11}
                formatter={(value: unknown) => `${asNumber(value).toFixed(0)}%`}
              />
              {rows.map((row) => (
                <Cell
                  key={row.label}
                  fill={CHART.over}
                  stroke={CHART.surface}
                  strokeWidth={2}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="mt-1 text-xs text-ink-muted">
        ความน่าจะเป็นที่ประตูรวมจะสูงกว่าแต่ละเส้น ส่วนที่เหลือคือฝั่งต่ำ
      </figcaption>
    </figure>
  );
}
