import { Panel, StatTile } from "@/components/ui";
import { goals, percent, signedPercent } from "@/lib/format";
import type { Backtest } from "@/lib/types";

// Walk-forward results.
//
// The headline is deliberately the comparison against the baselines, not the
// hit rate. A hit rate above 50% means nothing on its own: if 74% of matches
// go over, a model that always says Over scores 74% while knowing nothing.

export default function BacktestPanel({ backtest }: { backtest: Backtest }) {
  const model = backtest.scorecards[0];
  const baselines = backtest.scorecards.slice(1);
  const bestBaseline = baselines.reduce(
    (best, card) => (card.brier < best.brier ? card : best),
    baselines[0],
  );
  const beatsBaseline =
    model !== undefined && model.brier < bestBaseline?.brier;

  return (
    <Panel
      title="ทดสอบย้อนหลังแบบ walk-forward"
      description="เทรนใหม่ก่อนทุกนัดด้วยข้อมูลที่มีอยู่ ณ เวลานั้นเท่านั้น แล้วทำนายนัดที่โมเดลไม่เคยเห็น"
    >
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="นัดที่ทดสอบ"
            value={String(backtest.tested)}
            hint={`อุ่นเครื่อง ${backtest.min_train_matches} นัดแรก`}
          />
          <StatTile
            label="อัตราทายถูก"
            value={percent(backtest.accuracy, 1)}
            hint={`จาก ${backtest.scored} นัดที่ให้คะแนน`}
          />
          <StatTile
            label="ออกสูงจริง"
            value={percent(backtest.actual_over_rate, 1)}
            hint="เกณฑ์ที่ต้องเอาชนะ"
          />
          <StatTile
            label="ชนะเกณฑ์อ้างอิงหรือไม่"
            value={beatsBaseline ? "ชนะ" : "แพ้"}
            hint="วัดด้วยคะแนน Brier"
            tone={beatsBaseline ? "good" : "critical"}
          />
        </div>

        {!beatsBaseline && model ? (
          <div className="panel-raised border-critical/30 bg-critical/5 p-4">
            <p className="text-sm font-semibold text-ink">
              โมเดลยังทำได้ไม่ดีกว่าการเดาแบบง่าย
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-secondary">
              คะแนน Brier ของโมเดลอยู่ที่ {model.brier.toFixed(4)}{" "}
              ขณะที่เกณฑ์อ้างอิงที่ดีที่สุด คือ {bestBaseline.name} ได้{" "}
              {bestBaseline.brier.toFixed(4)} ซึ่งต่ำกว่า
              แปลว่าขั้นตอนคำนวณพลังบุกและพลังรับยังไม่ได้เพิ่มข้อมูลที่เป็นประโยชน์
              สำหรับการทำนายประตูรวมที่เส้นนี้
            </p>
          </div>
        ) : null}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] border-collapse text-sm">
            <caption className="mb-2 text-left text-xs text-ink-muted">
              ทุกผู้ทำนายให้คะแนนบนนัดชุดเดียวกัน ค่ายิ่งต่ำยิ่งดีทั้งสองคอลัมน์
            </caption>
            <thead>
              <tr className="border-b border-hairline text-left text-xs tracking-wide text-ink-muted">
                <th scope="col" className="py-2 pr-3 font-medium">
                  ผู้ทำนาย
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  Brier
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  Log loss
                </th>
                <th scope="col" className="py-2 text-right font-medium">
                  ดีกว่าอัตราสูงในอดีต
                </th>
              </tr>
            </thead>
            <tbody className="tabular">
              {backtest.scorecards.map((card, index) => {
                const isModel = index === 0;
                return (
                  <tr
                    key={card.name}
                    className={`border-b border-hairline/60 last:border-0 ${
                      isModel ? "bg-series-1/5" : ""
                    }`}
                  >
                    <th
                      scope="row"
                      className={`py-2.5 pr-3 text-left font-medium ${
                        isModel ? "text-ink" : "text-ink-secondary"
                      }`}
                    >
                      {card.name}
                    </th>
                    <td className="py-2.5 pr-3 text-right text-ink-secondary">
                      {card.brier.toFixed(4)}
                    </td>
                    <td className="py-2.5 pr-3 text-right text-ink-secondary">
                      {card.log_loss.toFixed(4)}
                    </td>
                    <td
                      className={`py-2.5 text-right ${
                        (card.skill_vs_base_rate ?? 0) > 0
                          ? "text-good"
                          : "text-ink-muted"
                      }`}
                    >
                      {card.skill_vs_base_rate === null
                        ? "—"
                        : signedPercent(card.skill_vs_base_rate, 2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-hairline pt-4 text-xs sm:grid-cols-4">
          <Fact
            label="คลาดเคลื่อนประตูเฉลี่ย"
            value={goals(backtest.mean_absolute_goal_error)}
          />
          <Fact label="RMSE ประตู" value={goals(backtest.rmse_goals)} />
          <Fact label="ฟอร์มย้อนหลังที่ใช้" value={`${backtest.last_n} นัด`} />
          <Fact
            label="วิธีเทรน"
            value={
              backtest.window === "rolling"
                ? `หน้าต่าง ${backtest.train_window} นัด`
                : "ขยายไปเรื่อย ๆ"
            }
          />
        </dl>

        {backtest.priced_picks > 0 ? (
          <div className="border-t border-hairline pt-4">
            <p className="mb-2 text-xs tracking-wide text-ink-muted">
              ถ้าลงเงินเท่ากันทุกนัดที่โมเดลมีความเห็น และมีราคาตลาดเก็บไว้
            </p>
            <div className="grid grid-cols-3 gap-3">
              <StatTile
                label="จำนวนครั้งที่ลง"
                value={String(backtest.priced_picks)}
              />
              <StatTile
                label="กำไรขาดทุน"
                value={`${backtest.profit > 0 ? "+" : ""}${backtest.profit.toFixed(2)}`}
                hint="หน่วย"
                tone={backtest.profit > 0 ? "good" : "critical"}
              />
              <StatTile
                label="ผลตอบแทนต่อหน่วย"
                value={signedPercent(backtest.roi, 2)}
                tone={backtest.roi > 0 ? "good" : "critical"}
              />
            </div>
          </div>
        ) : null}

        <p className="text-xs leading-relaxed text-ink-muted">
          ทุกนัดในตารางนี้โมเดลไม่เคยเห็นตอนทำนาย
          ข้อมูลที่ใช้เทรนคือนัดที่แข่งจบก่อนเวลาเตะของนัดนั้นเท่านั้น
          ผลลัพธ์จึงไม่ได้เกิดจากการ fit ทับข้อมูลเดิม
        </p>
      </div>
    </Panel>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="mt-0.5 font-medium text-ink-secondary tabular">{value}</dd>
    </div>
  );
}
