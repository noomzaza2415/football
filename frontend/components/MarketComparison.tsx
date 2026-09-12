import { Badge } from "@/components/ui";
import { odds, percent, signedPercent, SIDE_LABEL } from "@/lib/format";
import type { MarketComparison as Comparison } from "@/lib/types";

// Model against the posted price, side by side.
//
// The fair market probability is the posted price with the bookmaker margin
// removed, which is the only honest thing to compare a model against.

export default function MarketComparison({ items }: { items: Comparison[] }) {
  if (items.length === 0) {
    return (
      <p className="text-sm leading-relaxed text-ink-muted">
        คู่นี้ยังไม่มีราคาตลาดเก็บไว้ จึงยังเทียบกับโมเดลไม่ได้
        ถ้าต้องการดูส่วนต่าง ให้เพิ่มราคาปิดลงในข้อมูลแมตช์ก่อน
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const modelShare = item.model_probability * 100;
        const marketShare = item.fair_market_probability * 100;
        const better = item.edge > 0;

        return (
          <div key={item.selection} className="panel-raised p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <span
                  className={`text-sm font-semibold ${
                    item.selection === "OVER" ? "text-series-2" : "text-series-1"
                  }`}
                >
                  {SIDE_LABEL[item.selection]} {item.line.toFixed(1)}
                </span>
                <span className="text-sm text-ink-secondary tabular">
                  ที่ราคา {odds(item.decimal_odds)}
                </span>
              </div>

              <Badge
                className={
                  item.is_value
                    ? "bg-good/12 text-good ring-good/30"
                    : "bg-slate-500/10 text-ink-muted ring-hairline"
                }
              >
                <span aria-hidden="true">{item.is_value ? "▲" : "▪"}</span>
                {item.is_value ? "โมเดลเห็น value" : "ไม่มี value"}
              </Badge>
            </div>

            {/* Two labelled bars rather than a dual axis: same scale, same
                units, so they can share one axis honestly. */}
            <div className="mt-4 space-y-2.5">
              <ComparisonBar
                label="โมเดล"
                value={modelShare}
                color="var(--color-series-3)"
              />
              <ComparisonBar
                label="ตลาด"
                value={marketShare}
                color="var(--color-ink-muted)"
              />
            </div>

            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-hairline pt-3 text-xs sm:grid-cols-4">
              <Metric label="ส่วนต่าง" value={signedPercent(item.edge)} highlight={better} />
              <Metric
                label="ผลตอบแทนคาดหวังต่อ 1 หน่วย"
                value={signedPercent(item.expected_value, 1)}
                highlight={item.expected_value > 0}
              />
              <Metric
                label="ราคาตลาดบอกว่า"
                value={percent(item.market_probability)}
              />
              <Metric
                label="Kelly (จำกัดที่ 5%)"
                value={percent(item.kelly_fraction, 1)}
              />
            </dl>
          </div>
        );
      })}

      <p className="text-xs leading-relaxed text-ink-muted">
        ส่วนต่างบอกแค่ว่าโมเดลกับตลาดมองไม่ตรงกัน ไม่ได้แปลว่าโมเดลถูก
        และเมื่อข้อมูลย้อนหลังมีไม่มาก ฝ่ายที่ผิดมักเป็นโมเดลเอง
      </p>
    </div>
  );
}

function ComparisonBar({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-14 shrink-0 text-xs text-ink-muted">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-hairline">
        <span
          className="block h-full rounded-full"
          style={{ width: `${Math.min(value, 100)}%`, backgroundColor: color }}
        />
      </div>
      <span className="w-12 shrink-0 text-right text-xs font-medium text-ink-secondary tabular">
        {value.toFixed(1)}%
      </span>
    </div>
  );
}

function Metric({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div>
      <dt className="text-ink-muted">{label}</dt>
      <dd
        className={`mt-0.5 font-medium tabular ${
          highlight ? "text-good" : "text-ink-secondary"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
