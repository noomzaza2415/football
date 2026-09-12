"use client";

// Day navigation for the fixture list.
//
// Football is not played every day, so the arrows jump to the previous and next
// day that actually has matches rather than stepping blindly by 24 hours. The
// date input is there for going somewhere specific.

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import type { MatchDay } from "@/lib/types";

const THAI_LOCALE = "th-TH-u-ca-gregory";

function longDate(iso: string): string {
  return new Intl.DateTimeFormat(THAI_LOCALE, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(`${iso}T00:00:00Z`));
}

export default function DayNav({
  day,
  previousDay,
  nextDay,
  isDefaultDay,
  earliest,
  latest,
  daysWithMatches,
}: {
  day: string;
  previousDay: string | null;
  nextDay: string | null;
  /** True when the URL carries no day, so the server picked this one. */
  isDefaultDay: boolean;
  earliest: string | null;
  latest: string | null;
  daysWithMatches: MatchDay[];
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function goTo(target: string | null) {
    if (!target) return;
    startTransition(() => {
      router.push(`/?day=${target}`);
    });
  }

  // Dropping the query string is what asks the server for the nearest day, so
  // the client never has to work out which day that is.
  function goToDefault() {
    startTransition(() => {
      router.push("/");
    });
  }

  return (
    <div className="panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => goTo(previousDay)}
          disabled={!previousDay || isPending}
          aria-label="วันที่มีบอลก่อนหน้า"
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-hairline text-ink-secondary transition-colors hover:border-series-1/40 hover:text-ink disabled:cursor-not-allowed disabled:opacity-35 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
        >
          <span aria-hidden="true">←</span>
        </button>

        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{longDate(day)}</p>
          <p className="text-xs text-ink-muted">
            {daysWithMatches.length} วันที่มีบอลในฐานข้อมูล
          </p>
        </div>

        <button
          type="button"
          onClick={() => goTo(nextDay)}
          disabled={!nextDay || isPending}
          aria-label="วันที่มีบอลถัดไป"
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-hairline text-ink-secondary transition-colors hover:border-series-1/40 hover:text-ink disabled:cursor-not-allowed disabled:opacity-35 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
        >
          <span aria-hidden="true">→</span>
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {!isDefaultDay ? (
          <button
            type="button"
            onClick={goToDefault}
            disabled={isPending}
            className="rounded-lg bg-series-1/15 px-3 py-2 text-xs font-medium text-series-1 ring-1 ring-inset ring-series-1/30 transition-colors hover:bg-series-1/25 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
          >
            กลับไปวันล่าสุด
          </button>
        ) : null}

        <label className="flex items-center gap-2 text-xs text-ink-muted">
          <span>เลือกวันที่</span>
          <input
            type="date"
            value={day}
            min={earliest ?? undefined}
            max={latest ?? undefined}
            onChange={(event) => goTo(event.target.value)}
            disabled={isPending}
            className="rounded-lg border border-hairline bg-surface-raised px-2.5 py-1.5 text-sm text-ink [color-scheme:dark] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
          />
        </label>

        {isPending ? (
          <span className="text-xs text-ink-muted" role="status">
            กำลังโหลด…
          </span>
        ) : null}
      </div>
    </div>
  );
}
