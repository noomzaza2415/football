import Link from "next/link";

import AccuracyChart from "@/components/charts/AccuracyChart";
import CalibrationChart from "@/components/charts/CalibrationChart";
import BacktestPanel from "@/components/BacktestPanel";
import { DisclaimerBanner } from "@/components/Disclaimer";
import {
  BackendDownState,
  EmptyState,
  PageHeading,
  Panel,
  StatTile,
} from "@/components/ui";
import { api, tryRequest } from "@/lib/api";
import { formatDateOnly, goals, percent } from "@/lib/format";

export const dynamic = "force-dynamic";

const PICK_LABEL: Record<string, string> = {
  OVER: "สูง",
  UNDER: "ต่ำ",
  NEUTRAL: "ก้ำกึ่ง",
};

export default async function PerformancePage() {
  const [history, backtest] = await Promise.all([
    tryRequest(api.predictionHistory(300)),
    // The walk-forward run is the honest number; it is allowed to fail on its
    // own when there is too little history, without taking the page with it.
    tryRequest(api.backtest(60)),
  ]);

  if (history === null) {
    return <BackendDownState />;
  }

  if (history.total === 0 && backtest === null) {
    return (
      <div className="space-y-6">
        <PageHeading title="ผลงานของโมเดล" />
        <DisclaimerBanner />
        <EmptyState title="ยังไม่มีผลการทำนายที่ตรวจสอบแล้ว">
          <p>
            การตรวจย้อนหลังต้องเทียบผลทำนายที่บันทึกไว้กับผลจริง
            จึงต้องมีการบันทึกผลทำนายไว้ก่อนที่แมตช์จะแข่ง ลองใส่ข้อมูลตัวอย่าง
            หรือรันสคริปต์ดึงข้อมูลพร้อมตัวเลือกบันทึกผลทำนาย
          </p>
        </EmptyState>
      </div>
    );
  }

  const beatsCoinFlip = history.accuracy > 0.5;

  return (
    <div className="space-y-6">
      <PageHeading
        title="ผลงานของโมเดล"
        subtitle={
          backtest
            ? `ทดสอบแบบ walk-forward ${backtest.tested} นัด และมีผลทำนายที่บันทึกไว้อีก ${history.total} รายการ`
            : `ตรวจแล้ว ${history.evaluated} ครั้ง จากผลทำนายที่บันทึกไว้ทั้งหมด ${history.total} รายการ`
        }
      />

      <DisclaimerBanner text="ความแม่นยำในอดีตจากข้อมูลจำนวนน้อยแบบนี้บอกอนาคตได้น้อยมาก ให้มองตัวเลขทุกตัวในหน้านี้เป็นเครื่องมือตรวจสอบโมเดล ไม่ใช่หลักฐานว่าโมเดลทำกำไรได้" />

      {history.total > 0 ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="อัตราทายถูก"
            value={percent(history.accuracy, 1)}
            hint={`ถูก ${history.correct} จาก ${history.evaluated} ครั้ง`}
            tone={beatsCoinFlip ? "good" : "critical"}
          />
          <StatTile
            label="ที่ทายฝั่งสูง"
            value={percent(history.over_hit_rate, 0)}
            hint={`ทาย ${history.over_picks} ครั้ง`}
            tone="over"
          />
          <StatTile
            label="ที่ทายฝั่งต่ำ"
            value={percent(history.under_hit_rate, 0)}
            hint={`ทาย ${history.under_picks} ครั้ง`}
            tone="under"
          />
          <StatTile
            label="คะแนน Brier"
            value={history.brier_score.toFixed(3)}
            hint="ยิ่งต่ำยิ่งดี ค่า 0.25 เท่ากับเดาสุ่ม"
          />
        </div>
      ) : null}

      {backtest ? <BacktestPanel backtest={backtest} /> : null}

      {history.total > 0 ? (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel
              title="อัตราทายถูกตามช่วงเวลา"
              description="สัดส่วนที่โมเดลทายฝั่งสูง/ต่ำได้ตรงผลจริง เรียงจากเก่าไปใหม่"
            >
              <AccuracyChart items={history.items} />
            </Panel>

            <Panel
              title="ความแม่นของค่าความน่าจะเป็น"
              description="เมื่อโมเดลบอกว่า 70% แล้วเกิดขึ้นจริง 70% หรือไม่"
            >
              <CalibrationChart buckets={history.calibration} />
            </Panel>
          </div>

          <Panel
            title="รายการผลทำนายที่ตรวจแล้ว"
            description={`ค่าคลาดเคลื่อนเฉลี่ยของประตูรวม ${goals(history.mean_absolute_goal_error)} ประตูต่อนัด`}
          >
            <div className="overflow-x-auto">
              <table className="w-full min-w-[46rem] border-collapse text-sm">
                <caption className="sr-only">
                  ผลทำนายที่บันทึกไว้ทุกรายการ พร้อมผลการแข่งขันจริง
                </caption>
                <thead>
                  <tr className="border-b border-hairline text-left text-xs tracking-wide text-ink-muted">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      วันที่
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      คู่แข่งขัน
                    </th>
                    <th
                      scope="col"
                      className="py-2 pr-3 text-right font-medium"
                    >
                      ประตูที่ทาย
                    </th>
                    <th
                      scope="col"
                      className="py-2 pr-3 text-right font-medium"
                    >
                      โอกาสสูง 2.5
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      ทายฝั่ง
                    </th>
                    <th
                      scope="col"
                      className="py-2 pr-3 text-right font-medium"
                    >
                      ผลจริง
                    </th>
                    <th scope="col" className="py-2 font-medium">
                      สรุป
                    </th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {history.items.slice(0, 60).map((item) => (
                    <tr
                      key={`${item.match_id}-${item.created_at ?? ""}`}
                      className="border-b border-hairline/60 last:border-0"
                    >
                      <td className="py-2.5 pr-3 whitespace-nowrap text-ink-muted">
                        {formatDateOnly(item.match_date)}
                      </td>
                      <td className="py-2.5 pr-3">
                        <Link
                          href={`/matches/${item.match_id}`}
                          className="text-ink-secondary transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
                        >
                          {item.home_team} พบ {item.away_team}
                        </Link>
                      </td>
                      <td className="py-2.5 pr-3 text-right text-ink-secondary">
                        {goals(item.predicted_total_goals)}
                      </td>
                      <td className="py-2.5 pr-3 text-right text-ink-secondary">
                        {percent(item.prob_over_2_5, 0)}
                      </td>
                      <td className="py-2.5 pr-3">
                        <span
                          className={
                            item.model_pick === "OVER"
                              ? "text-series-2"
                              : item.model_pick === "UNDER"
                                ? "text-series-1"
                                : "text-ink-muted"
                          }
                        >
                          {PICK_LABEL[item.model_pick] ?? item.model_pick}
                        </span>
                      </td>
                      <td className="py-2.5 pr-3 text-right font-medium text-ink">
                        {item.actual_home_goals}&ndash;{item.actual_away_goals}
                      </td>
                      <td className="py-2.5 whitespace-nowrap">
                        {item.model_pick === "NEUTRAL" ? (
                          <span className="text-ink-muted">ไม่นับ</span>
                        ) : (
                          <span
                            className={
                              item.correct ? "text-good" : "text-critical"
                            }
                          >
                            <span aria-hidden="true">
                              {item.correct ? "✓" : "✕"}
                            </span>{" "}
                            {item.correct ? "ถูก" : "ผิด"}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      ) : null}
    </div>
  );
}
