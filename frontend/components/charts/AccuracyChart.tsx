"use client";

// Rolling hit rate of the model's Over/Under pick, oldest to newest.
//
// Change over time, so a line. One series, so the title names it and no legend
// box is needed. The 50% mark is drawn as a reference because it is the level
// the model has to beat to be saying anything at all.

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART, asNumber, axisLine, axisTick, tooltipStyles } from "./chartTheme";
import { formatAxisDate } from "@/lib/format";
import type { PredictionHistoryItem } from "@/lib/types";

const WINDOW = 10;

interface Row {
  index: number;
  date: string;
  rollingAccuracy: number;
  cumulativeAccuracy: number;
}

function buildRows(items: PredictionHistoryItem[]): Row[] {
  // The API returns newest first; a trend reads left to right in time order.
  const ordered = [...items]
    .filter((item) => item.model_pick !== "NEUTRAL")
    .reverse();

  const rows: Row[] = [];
  let hits = 0;

  ordered.forEach((item, index) => {
    hits += item.correct ? 1 : 0;
    const from = Math.max(0, index - WINDOW + 1);
    const window = ordered.slice(from, index + 1);
    const windowHits = window.filter((entry) => entry.correct).length;

    rows.push({
      index: index + 1,
      date: formatAxisDate(item.match_date),
      rollingAccuracy: (windowHits / window.length) * 100,
      cumulativeAccuracy: (hits / (index + 1)) * 100,
    });
  });

  return rows;
}

export default function AccuracyChart({ items }: { items: PredictionHistoryItem[] }) {
  const rows = buildRows(items);

  if (rows.length < 2) {
    return (
      <p className="py-8 text-center text-sm text-ink-muted">
        ยังมีผลการทำนายที่ตรวจแล้วไม่พอจะวาดแนวโน้ม
      </p>
    );
  }

  return (
    <figure className="m-0">
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis
              dataKey="date"
              tick={axisTick}
              axisLine={axisLine}
              tickLine={false}
              minTickGap={28}
            />
            <YAxis
              domain={[0, 100]}
              tick={axisTick}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value: number) => `${value}%`}
              width={48}
            />
            <ReferenceLine
              y={50}
              stroke={CHART.baseline}
              strokeDasharray="4 4"
              label={{
                value: "เสี่ยงทาย 50%",
                position: "insideTopRight",
                fill: CHART.inkMuted,
                fontSize: 10,
              }}
            />
            <Tooltip
              {...tooltipStyles}
              cursor={{ stroke: CHART.baseline, strokeWidth: 1 }}
              formatter={(value: unknown, name: unknown) => [
                `${asNumber(value).toFixed(0)}%`,
                name === "rollingAccuracy"
                  ? `${WINDOW} นัดล่าสุด`
                  : "ตั้งแต่เริ่มเก็บ",
              ]}
            />
            <Line
              type="monotone"
              dataKey="cumulativeAccuracy"
              stroke={CHART.inkMuted}
              strokeWidth={2}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="rollingAccuracy"
              stroke={CHART.accent}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="h-0.5 w-4 rounded-full"
            style={{ backgroundColor: CHART.accent }}
          />
          อัตราทายถูกแบบเคลื่อนที่ {WINDOW} นัด
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="h-0.5 w-4 rounded-full opacity-70"
            style={{
              backgroundImage: `repeating-linear-gradient(to right, ${CHART.inkMuted} 0 4px, transparent 4px 7px)`,
            }}
          />
          อัตราทายถูกสะสม
        </span>
      </figcaption>
    </figure>
  );
}
