// Small shared pieces: panels, stat tiles, badges, empty and error states.

import Link from "next/link";
import type { ReactNode } from "react";

export function PageHeading({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle ? (
          <p className="mt-1 text-sm text-ink-secondary">{subtitle}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function Panel({
  title,
  description,
  children,
  className = "",
}: {
  title?: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel p-5 ${className}`}>
      {title ? (
        <header className="mb-4">
          <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
          {description ? (
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">{description}</p>
          ) : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

/** A single headline number. No chart, so no hover layer. */
export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "over" | "under" | "good" | "critical";
}) {
  const toneClass = {
    neutral: "text-ink",
    over: "text-series-2",
    under: "text-series-1",
    good: "text-good",
    critical: "text-critical",
  }[tone];

  return (
    <div className="panel-raised px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
        {label}
      </p>
      <p className={`mt-1 text-2xl font-semibold tracking-tight ${toneClass}`}>
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
    </div>
  );
}

export function Badge({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${className}`}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="panel px-6 py-12 text-center">
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <div className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-ink-secondary">
        {children}
      </div>
    </div>
  );
}

export function BackendDownState() {
  return (
    <EmptyState title="ติดต่อ API วิเคราะห์ไม่ได้">
      <p>
        กรุณาเปิดเซิร์ฟเวอร์ฝั่ง backend แล้วโหลดหน้านี้ใหม่ โดยรันคำสั่งนี้ในโฟลเดอร์{" "}
        <code className="rounded bg-surface-raised px-1.5 py-0.5 text-xs">backend</code>
      </p>
      <pre className="mt-3 overflow-x-auto rounded-lg bg-surface-raised p-3 text-left text-xs text-ink-secondary">
        <code>uvicorn app.main:app --reload --port 8000</code>
      </pre>
      <p className="mt-3">
        ถ้าฐานข้อมูลยังว่างอยู่ ให้ใส่ข้อมูลตัวอย่างก่อนด้วยคำสั่ง{" "}
        <code className="rounded bg-surface-raised px-1.5 py-0.5 text-xs">
          python -m scripts.seed_demo --reset
        </code>
      </p>
    </EmptyState>
  );
}

export function BackLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1.5 text-sm text-ink-secondary transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
    >
      <span aria-hidden="true">←</span>
      {children}
    </Link>
  );
}
