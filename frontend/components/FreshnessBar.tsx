"use client";

// How current the data is, and a self-refresh.
//
// The page reloads itself on an interval so a long-open tab does not quietly go
// stale. What it cannot do is make the data live: the upstream sources publish
// on their own schedule, so this states the age of the stored data plainly
// rather than implying a live feed.

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { Freshness } from "@/lib/types";

const REFRESH_SECONDS = 120;

function ageInWords(iso: string | null, now: number): string {
  if (!iso) return "ไม่ทราบ";

  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "เมื่อครู่นี้";
  if (minutes < 60) return `${minutes} นาทีที่แล้ว`;

  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ชั่วโมงที่แล้ว`;

  return `${Math.round(hours / 24)} วันที่แล้ว`;
}

function clockTime(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("th-TH-u-ca-gregory", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export default function FreshnessBar({ freshness }: { freshness: Freshness }) {
  const router = useRouter();
  const [now, setNow] = useState(() => Date.now());
  const [countdown, setCountdown] = useState(REFRESH_SECONDS);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    const tick = setInterval(() => {
      setNow(Date.now());
      setCountdown((remaining) => {
        if (!autoRefresh) return REFRESH_SECONDS;
        if (remaining <= 1) {
          router.refresh();
          return REFRESH_SECONDS;
        }
        return remaining - 1;
      });
    }, 1000);

    return () => clearInterval(tick);
  }, [autoRefresh, router]);

  return (
    <div className="panel flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="h-1.5 w-1.5 rounded-full bg-good"
          />
          ข้อมูลอัปเดต {ageInWords(freshness.last_ingest_at, now)}
        </span>
        <span>ผลล่าสุดในฐานข้อมูล {clockTime(freshness.latest_result_at)}</span>
        {freshness.next_kickoff_at ? (
          <span>เตะนัดต่อไป {clockTime(freshness.next_kickoff_at)}</span>
        ) : null}
      </div>

      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-ink-secondary">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(event) => setAutoRefresh(event.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--color-series-1)]"
          />
          รีเฟรชเอง
          {autoRefresh ? (
            <span className="text-ink-muted tabular">({countdown} วิ)</span>
          ) : null}
        </label>

        <button
          type="button"
          onClick={() => router.refresh()}
          className="rounded-lg border border-hairline px-3 py-1.5 text-xs font-medium text-ink-secondary transition-colors hover:border-series-1/40 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
        >
          รีเฟรชเดี๋ยวนี้
        </button>
      </div>
    </div>
  );
}
