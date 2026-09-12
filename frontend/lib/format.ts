// Display helpers shared by the pages and the chart components.
//
// The interface is Thai. Dates use the Thai locale but are pinned to the
// Gregorian calendar, so the year reads 2026 rather than the Buddhist 2569,
// which is what football fixture lists normally show.

import type { Lean } from "./types";

const THAI_LOCALE = "th-TH-u-ca-gregory";

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function goals(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function odds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

/** A signed percentage, used for edges where the direction is the point. */
export function signedPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const formatted = `${(Math.abs(value) * 100).toFixed(digits)}%`;
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `-${formatted}`;
  return formatted;
}

export function formatKickoff(iso: string): string {
  return new Intl.DateTimeFormat(THAI_LOCALE, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function formatDateOnly(iso: string): string {
  return new Intl.DateTimeFormat(THAI_LOCALE, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

/** Short day and month, for a crowded chart axis. */
export function formatAxisDate(iso: string): string {
  return new Intl.DateTimeFormat(THAI_LOCALE, {
    day: "numeric",
    month: "short",
  }).format(new Date(iso));
}

/** The Thai label for each side of the market. */
export const SIDE_LABEL: Record<"OVER" | "UNDER", string> = {
  OVER: "สูง",
  UNDER: "ต่ำ",
};

export function leanStyles(lean: Lean | null | undefined): {
  label: string;
  badge: string;
  className: string;
} {
  switch (lean) {
    case "OVER":
      return {
        label: "โมเดลเอนไปทางสูง",
        badge: "สูง",
        className: "bg-series-2/12 text-series-2 ring-series-2/30",
      };
    case "UNDER":
      return {
        label: "โมเดลเอนไปทางต่ำ",
        badge: "ต่ำ",
        className: "bg-series-1/12 text-series-1 ring-series-1/30",
      };
    default:
      return {
        label: "ไม่เอนไปทางใด",
        badge: "ก้ำกึ่ง",
        className: "bg-slate-500/12 text-ink-secondary ring-hairline",
      };
  }
}

/** Colour a form letter: W green, D grey, L red. */
export function formLetterClass(letter: string): string {
  if (letter === "W") return "bg-good/15 text-good ring-good/30";
  if (letter === "L") return "bg-critical/15 text-critical ring-critical/30";
  return "bg-slate-500/15 text-ink-secondary ring-hairline";
}

/** W / D / L in Thai, for the form string tooltip. */
export function formLetterLabel(letter: string): string {
  if (letter === "W") return "ชนะ";
  if (letter === "L") return "แพ้";
  return "เสมอ";
}
