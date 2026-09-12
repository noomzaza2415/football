"use client";

// Calibration: when the model said 70%, did it happen 70% of the time?
//
// Bars are the measured rate per probability bucket; the dashed diagonal is
// perfect calibration. Bars above the diagonal mean the model is too cautious,
// below means it is overconfident.

import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
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
import type { CalibrationBucket } from "@/lib/types";

interface Row {
  bucket: string;
  actual: number;
  ideal: number;
  samples: number;
}

export default function CalibrationChart({ buckets }: { buckets: CalibrationBucket[] }) {
  if (buckets.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-ink-muted">
        ยังไม่มีผลการทำนายที่ตรวจแล้ว
      </p>
    );
  }

  const rows: Row[] = buckets.map((bucket) => ({
    bucket: bucket.bucket,
    actual: bucket.actual_rate * 100,
    ideal: bucket.predicted_probability * 100,
    samples: bucket.samples,
  }));

  return (
    <figure className="m-0">
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis
              dataKey="bucket"
              tick={axisTick}
              axisLine={axisLine}
              tickLine={false}
              label={{
                value: "ความน่าจะเป็นฝั่งสูง 2.5 ที่โมเดลให้ไว้",
                position: "insideBottom",
                offset: -2,
                fill: CHART.inkMuted,
                fontSize: 11,
              }}
            />
            <YAxis
              domain={[0, 100]}
              tick={axisTick}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value: number) => `${value}%`}
              width={48}
            />
            <Tooltip
              {...tooltipStyles}
              formatter={(value: unknown, name: unknown, entry: unknown) => [
                `${asNumber(value).toFixed(0)}%${
                  name === "actual"
                    ? ` จาก ${payloadOf<Row>(entry)?.samples ?? 0} นัด`
                    : ""
                }`,
                name === "actual" ? "ออกสูงจริง" : "แม่นยำสมบูรณ์",
              ]}
            />
            <Bar dataKey="actual" radius={[4, 4, 0, 0]} maxBarSize={40}>
              {rows.map((row) => (
                <Cell
                  key={row.bucket}
                  fill={CHART.under}
                  stroke={CHART.surface}
                  strokeWidth={2}
                  // A bucket with almost no matches in it is noise, not signal.
                  fillOpacity={row.samples < 3 ? 0.4 : 1}
                />
              ))}
            </Bar>
            <Line
              type="linear"
              dataKey="ideal"
              stroke={CHART.inkMuted}
              strokeWidth={2}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: CHART.under }}
          />
          อัตราที่ออกสูงจริง
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="h-0.5 w-4 rounded-full"
            style={{
              backgroundImage: `repeating-linear-gradient(to right, ${CHART.inkMuted} 0 4px, transparent 4px 7px)`,
            }}
          />
          เส้นแม่นยำสมบูรณ์
        </span>
        <span>แท่งที่จางคือช่วงที่มีไม่ถึงสามนัด</span>
      </figcaption>
    </figure>
  );
}
