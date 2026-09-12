import { DisclaimerBanner } from "@/components/Disclaimer";
import MatchCard from "@/components/MatchCard";
import { BackendDownState, EmptyState, PageHeading, StatTile } from "@/components/ui";
import { api, tryRequest } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const [summaries, health] = await Promise.all([
    tryRequest(api.upcomingMatches(14, 60)),
    tryRequest(api.health()),
  ]);

  if (summaries === null) {
    return <BackendDownState />;
  }

  const withModel = summaries.filter((item) => item.prob_over_2_5 !== null);
  const overLeans = withModel.filter((item) => item.lean === "OVER").length;
  const valueSpots = withModel.filter(
    (item) => item.edge_over_2_5 !== null && Math.abs(item.edge_over_2_5) > 0.05,
  ).length;
  const averageGoals =
    withModel.length > 0
      ? withModel.reduce((sum, item) => sum + (item.expected_total_goals ?? 0), 0) /
        withModel.length
      : 0;

  return (
    <div className="space-y-6">
      <PageHeading
        title="โปรแกรมการแข่งขัน"
        subtitle="ค่าประมาณประตูรวมจากโมเดล สำหรับนัดที่จะแข่งภายใน 14 วันข้างหน้า"
      />

      <DisclaimerBanner />

      {summaries.length === 0 ? (
        <EmptyState title="ไม่มีนัดที่จะแข่งใน 14 วันข้างหน้า">
          <p>
            ลองรันสคริปต์ดึงข้อมูลเพื่อโหลดโปรแกรมการแข่งขัน
            หรือใส่ข้อมูลตัวอย่างเพื่อดูหน้าจอพร้อมสถิติย้อนหลังหนึ่งฤดูกาลเต็ม
          </p>
        </EmptyState>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="จำนวนนัด" value={String(summaries.length)} />
            <StatTile
              label="เอนไปทางสูง"
              value={`${overLeans}`}
              hint={`จาก ${withModel.length} นัดที่คำนวณได้`}
              tone="over"
            />
            <StatTile
              label="ประตูรวมเฉลี่ย"
              value={averageGoals.toFixed(2)}
              hint="ค่าคาดหวังจากโมเดล"
            />
            <StatTile
              label="โมเดลต่างจากตลาด"
              value={String(valueSpots)}
              hint="นัดที่ต่างกันเกิน 5 จุด"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {summaries.map((summary) => (
              <MatchCard key={summary.match.id} summary={summary} />
            ))}
          </div>
        </>
      )}

      {health ? (
        <p className="text-xs text-ink-muted">
          ในฐานข้อมูลมีผลการแข่งขันที่จบแล้ว{" "}
          <span className="tabular">{health.finished_matches}</span> นัด และ{" "}
          <span className="tabular">{health.teams}</span> ทีม โมเดลเวอร์ชัน{" "}
          {health.model_version}
        </p>
      ) : null}
    </div>
  );
}
