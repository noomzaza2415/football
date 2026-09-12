import DayNav from "@/components/DayNav";
import { DisclaimerBanner } from "@/components/Disclaimer";
import FreshnessBar from "@/components/FreshnessBar";
import MatchCard from "@/components/MatchCard";
import NewsPanel from "@/components/NewsPanel";
import { BackendDownState, EmptyState, PageHeading, StatTile } from "@/components/ui";
import { api, tryRequest } from "@/lib/api";

export const dynamic = "force-dynamic";

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ day?: string }>;
}) {
  const { day } = await searchParams;
  const requestedDay = day && DAY_PATTERN.test(day) ? day : undefined;

  // The calendar and the news feed are allowed to fail without taking the page
  // down; the matchday itself is the page.
  const [view, calendar, news] = await Promise.all([
    tryRequest(api.matchDay(requestedDay)),
    tryRequest(api.calendar()),
    tryRequest(api.news(10)),
  ]);

  if (view === null) {
    return <BackendDownState />;
  }

  if (view.day === null) {
    return (
      <div className="space-y-6">
        <PageHeading title="ยังไม่มีแมตช์ในฐานข้อมูล" />
        <DisclaimerBanner />
        <EmptyState title="ต้องดึงข้อมูลบอลเข้ามาก่อน">
          <p>
            เปิด Tasks: Run Task แล้วเลือก &quot;Pipeline: ดึงข้อมูลบอลจริง&quot;
            หรือรันคำสั่งนี้ในโฟลเดอร์ backend
          </p>
          <pre className="mt-3 overflow-x-auto rounded-lg bg-surface-raised p-3 text-left text-xs text-ink-secondary">
            <code>
              python -m app.pipeline.run_ingest --provider football-data-uk
              --competitions E0 --seasons 2024 2025 2026 --refresh-predictions
            </code>
          </pre>
        </EmptyState>
      </div>
    );
  }

  const withModel = view.matches.filter((item) => item.prob_over_2_5 !== null);
  const played = view.matches.filter((item) => item.actual_total_goals !== null);
  const scored = played.filter((item) => item.model_correct !== null);
  const hits = scored.filter((item) => item.model_correct).length;

  const averageGoals =
    withModel.length > 0
      ? withModel.reduce((sum, item) => sum + (item.expected_total_goals ?? 0), 0) /
        withModel.length
      : 0;
  const actualGoals =
    played.length > 0
      ? played.reduce((sum, item) => sum + (item.actual_total_goals ?? 0), 0) /
        played.length
      : null;

  const allPlayed = played.length === view.matches.length && played.length > 0;

  return (
    <div className="space-y-6">
      <PageHeading
        title="แมตช์รายวัน"
        subtitle={
          allPlayed
            ? "วันนี้แข่งจบแล้วทั้งหมด ค่าที่แสดงคือสิ่งที่โมเดลจะบอกก่อนเตะ เทียบกับผลจริง"
            : "ค่าประมาณประตูรวมจากโมเดล สำหรับแมตช์ในวันที่เลือก"
        }
      />

      <FreshnessBar freshness={view.freshness} />

      <DayNav
        day={view.day}
        previousDay={view.previous_day}
        nextDay={view.next_day}
        isDefaultDay={requestedDay === undefined}
        earliest={calendar?.earliest ? calendar.earliest.slice(0, 10) : null}
        latest={calendar?.latest ? calendar.latest.slice(0, 10) : null}
        daysWithMatches={calendar?.days ?? []}
      />

      <DisclaimerBanner />

      {view.matches.length === 0 ? (
        <EmptyState title="วันนี้ไม่มีแมตช์">
          <p>ใช้ลูกศรด้านบนเพื่อข้ามไปวันที่มีบอล หรือเลือกวันที่เอง</p>
        </EmptyState>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="จำนวนแมตช์" value={String(view.matches.length)} />
            <StatTile
              label="ประตูรวมที่คาดเฉลี่ย"
              value={averageGoals.toFixed(2)}
              hint={`จาก ${withModel.length} แมตช์ที่คำนวณได้`}
            />
            {actualGoals !== null ? (
              <StatTile
                label="ประตูรวมจริงเฉลี่ย"
                value={actualGoals.toFixed(2)}
                hint={`จาก ${played.length} แมตช์ที่จบแล้ว`}
              />
            ) : (
              <StatTile
                label="เอนไปทางสูง"
                value={String(withModel.filter((m) => m.lean === "OVER").length)}
                hint={`จาก ${withModel.length} แมตช์`}
                tone="over"
              />
            )}
            {scored.length > 0 ? (
              <StatTile
                label="โมเดลทายถูกวันนี้"
                value={`${hits}/${scored.length}`}
                hint="เทียบผลจริง"
                tone={hits * 2 >= scored.length ? "good" : "critical"}
              />
            ) : (
              <StatTile
                label="มีราคาตลาด"
                value={String(
                  view.matches.filter((m) => m.match.market_odds_over !== null).length,
                )}
                hint="แมตช์ที่เทียบตลาดได้"
              />
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {view.matches.map((summary) => (
              <MatchCard key={summary.match.id} summary={summary} />
            ))}
          </div>
        </>
      )}

      <NewsPanel feed={news} />
    </div>
  );
}
