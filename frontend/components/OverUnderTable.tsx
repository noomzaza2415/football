import { odds, percent } from "@/lib/format";
import type { LineProbability } from "@/lib/types";

// The table view that sits beside the charts, so every number is readable
// without hovering anything.

export default function OverUnderTable({
  lines,
  marketLine,
}: {
  lines: LineProbability[];
  marketLine?: number | null;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[30rem] border-collapse text-sm">
        <caption className="sr-only">
          ความน่าจะเป็นจากโมเดลและราคายุติธรรมของแต่ละเส้นสูง/ต่ำ
        </caption>
        <thead>
          <tr className="border-b border-hairline text-left text-xs uppercase tracking-wide text-ink-muted">
            <th scope="col" className="py-2 pr-3 font-medium">
              เส้น
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              สูง
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              ต่ำ
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              ราคายุติธรรมสูง
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              ราคายุติธรรมต่ำ
            </th>
          </tr>
        </thead>
        <tbody className="tabular">
          {lines.map((entry) => {
            const isMarketLine = marketLine !== null && marketLine === entry.line;
            return (
              <tr
                key={entry.line}
                className={`border-b border-hairline/60 last:border-0 ${
                  isMarketLine ? "bg-series-1/5" : ""
                }`}
              >
                <th
                  scope="row"
                  className="py-2.5 pr-3 text-left font-medium text-ink"
                >
                  {entry.line.toFixed(1)}
                  {isMarketLine ? (
                    <span className="ml-2 rounded bg-series-1/15 px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-series-1 ring-1 ring-inset ring-series-1/30">
                      เส้นตลาด
                    </span>
                  ) : null}
                </th>
                <td className="py-2.5 pr-3 text-right font-medium text-series-2">
                  {percent(entry.prob_over)}
                </td>
                <td className="py-2.5 pr-3 text-right font-medium text-series-1">
                  {percent(entry.prob_under)}
                </td>
                <td className="py-2.5 pr-3 text-right text-ink-secondary">
                  {odds(entry.fair_odds_over)}
                </td>
                <td className="py-2.5 text-right text-ink-secondary">
                  {odds(entry.fair_odds_under)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-3 text-xs leading-relaxed text-ink-muted">
        ราคายุติธรรมคือราคาต่อรองแบบทศนิยมที่คุ้มทุนพอดีตามความน่าจะเป็นของโมเดล
        ยังไม่รวมค่าน้ำของเจ้ามือ ถ้าราคาจริงต่ำกว่าราคายุติธรรม แปลว่าไม่มี value
        ตามมุมมองของโมเดลนี้
      </p>
    </div>
  );
}
