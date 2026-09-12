import Link from "next/link";

import { Badge } from "@/components/ui";
import { formatKickoff, goals, leanStyles, percent, signedPercent } from "@/lib/format";
import type { MatchSummary } from "@/lib/types";

export default function MatchCard({ summary }: { summary: MatchSummary }) {
  const { match } = summary;
  const lean = leanStyles(summary.lean);
  const hasModel = summary.prob_over_2_5 !== null;
  const overShare = (summary.prob_over_2_5 ?? 0) * 100;
  const played = summary.actual_total_goals !== null;

  return (
    <Link
      href={`/matches/${match.id}`}
      className="panel group flex flex-col gap-4 p-5 transition-colors hover:border-series-1/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs uppercase tracking-wide text-ink-muted">
            {match.league}
          </p>
          <p className="mt-1 text-xs text-ink-secondary tabular">
            {formatKickoff(match.match_date)}
          </p>
        </div>
        <Badge className={lean.className}>
          {hasModel ? lean.badge : "ไม่มีข้อมูล"}
        </Badge>
      </div>

      {/* A finished match leads with the score; an upcoming one has none. */}
      {played ? (
        <div className="space-y-1">
          <div className="flex items-baseline justify-between gap-3">
            <p className="min-w-0 truncate text-base font-semibold tracking-tight text-ink">
              {match.home_team.name}
            </p>
            <p className="text-lg font-semibold text-ink tabular">{match.home_goals}</p>
          </div>
          <div className="flex items-baseline justify-between gap-3">
            <p className="min-w-0 truncate text-base font-semibold tracking-tight text-ink">
              {match.away_team.name}
            </p>
            <p className="text-lg font-semibold text-ink tabular">{match.away_goals}</p>
          </div>
        </div>
      ) : (
        <div className="space-y-1">
          <p className="truncate text-base font-semibold tracking-tight text-ink">
            {match.home_team.name}
          </p>
          <p className="truncate text-base font-semibold tracking-tight text-ink">
            {match.away_team.name}
          </p>
        </div>
      )}

      {hasModel ? (
        <>
          <div className="flex items-baseline justify-between gap-3">
            <div>
              <p className="text-xs text-ink-muted">
                {played ? "ประตูรวมที่คาดไว้" : "ประตูรวมที่คาด"}
              </p>
              <p className="text-2xl font-semibold tracking-tight text-ink tabular">
                {goals(summary.expected_total_goals)}
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-ink-muted">
                {played ? "ประตูรวมจริง" : "สูง 2.5"}
              </p>
              <p
                className={`text-2xl font-semibold tracking-tight tabular ${
                  played ? "text-ink" : "text-series-2"
                }`}
              >
                {played
                  ? summary.actual_total_goals
                  : percent(summary.prob_over_2_5, 0)}
              </p>
            </div>
          </div>

          {/* Over on the left, Under on the right, each labelled below so the
              split never depends on colour alone. */}
          <div>
            <div
              className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full"
              role="img"
              aria-label={`สูง 2.5 ${percent(summary.prob_over_2_5, 0)} ต่ำ 2.5 ${percent(summary.prob_under_2_5, 0)}`}
            >
              <span
                className="h-full rounded-l-full bg-series-2"
                style={{ width: `${overShare}%` }}
              />
              <span className="h-full flex-1 rounded-r-full bg-series-1" />
            </div>
            <div className="mt-1.5 flex justify-between text-xs text-ink-muted tabular">
              <span>สูง {percent(summary.prob_over_2_5, 0)}</span>
              <span>ต่ำ {percent(summary.prob_under_2_5, 0)}</span>
            </div>
          </div>

          <div className="border-t border-hairline pt-3 text-xs text-ink-muted">
            {played ? (
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span>ผลออก {summary.actual_result === "OVER" ? "สูง" : "ต่ำ"}</span>
                {summary.model_correct === null ? (
                  <span>โมเดลก้ำกึ่ง ไม่นับ</span>
                ) : (
                  <span className={summary.model_correct ? "text-good" : "text-critical"}>
                    <span aria-hidden="true">{summary.model_correct ? "✓" : "✕"}</span>{" "}
                    โมเดลทาย{summary.model_correct ? "ถูก" : "ผิด"}
                  </span>
                )}
                {summary.point_in_time ? (
                  <span
                    className="rounded bg-surface-raised px-1.5 py-0.5 text-[10px]"
                    title="ทำนายจากข้อมูลที่มีก่อนเวลาเตะเท่านั้น"
                  >
                    ไม่แอบดูผล
                  </span>
                ) : null}
              </p>
            ) : match.market_odds_over !== null && summary.edge_over_2_5 !== null ? (
              <p>
                ราคาตลาด {match.market_odds_over.toFixed(2)} /{" "}
                {match.market_odds_under?.toFixed(2)}
                <span className="mx-1.5 text-baseline">·</span>
                <span
                  className={
                    summary.edge_over_2_5 > 0 ? "text-good" : "text-ink-secondary"
                  }
                >
                  ส่วนต่างฝั่งสูง {signedPercent(summary.edge_over_2_5, 1)}
                </span>
              </p>
            ) : (
              <p>ยังไม่มีราคาตลาดของคู่นี้</p>
            )}
          </div>
        </>
      ) : (
        <p className="text-sm text-ink-muted">
          ผลการแข่งขันย้อนหลังยังไม่พอให้โมเดลคำนวณคู่นี้
        </p>
      )}
    </Link>
  );
}
