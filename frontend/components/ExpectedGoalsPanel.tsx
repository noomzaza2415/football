import { goals, percent } from "@/lib/format";
import type { Prediction } from "@/lib/types";

// Expected goals for each side, plus the 1X2 split the same matrix implies.

export default function ExpectedGoalsPanel({ prediction }: { prediction: Prediction }) {
  const { match } = prediction;
  const total = prediction.expected_total_goals || 1;
  const homeShare = (prediction.expected_home_goals / total) * 100;

  const outcomes = [
    {
      label: match.home_team.short_name ?? match.home_team.name,
      note: "เหย้าชนะ",
      value: prediction.prob_home_win,
    },
    { label: "เสมอ", note: "เสมอ", value: prediction.prob_draw },
    {
      label: match.away_team.short_name ?? match.away_team.name,
      note: "เยือนชนะ",
      value: prediction.prob_away_win,
    },
  ];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 items-end gap-3">
        <TeamGoals
          name={match.home_team.name}
          venue="เหย้า"
          value={prediction.expected_home_goals}
          align="left"
        />
        <div className="pb-1 text-center">
          <p className="text-xs tracking-wide text-ink-muted">ประตูรวม</p>
          <p className="text-3xl font-semibold tracking-tight text-ink tabular">
            {goals(prediction.expected_total_goals)}
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            สกอร์ที่เป็นไปได้มากสุด {prediction.most_likely_score}
          </p>
        </div>
        <TeamGoals
          name={match.away_team.name}
          venue="เยือน"
          value={prediction.expected_away_goals}
          align="right"
        />
      </div>

      <div
        className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full"
        role="img"
        aria-label={`สัดส่วนประตูที่คาด ทีมเหย้าคิดเป็น ${homeShare.toFixed(0)} เปอร์เซ็นต์ของประตูรวม`}
      >
        <span
          className="h-full rounded-l-full bg-series-3"
          style={{ width: `${homeShare}%` }}
        />
        <span className="h-full flex-1 rounded-r-full bg-series-1" />
      </div>

      <div className="border-t border-hairline pt-4">
        <p className="mb-3 text-xs tracking-wide text-ink-muted">
          ผลการแข่งขันจากเมทริกซ์สกอร์ชุดเดียวกัน
        </p>
        <dl className="grid grid-cols-3 gap-3">
          {outcomes.map((outcome) => (
            <div key={outcome.note} className="panel-raised px-3 py-2.5 text-center">
              <dt className="truncate text-xs text-ink-muted" title={outcome.note}>
                {outcome.label}
              </dt>
              <dd className="mt-0.5 text-lg font-semibold text-ink tabular">
                {percent(outcome.value, 0)}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <p className="text-xs leading-relaxed text-ink-muted">
        คำนวณจากผลการแข่งขันที่จบแล้ว {prediction.sample_matches} นัด ด้วยโมเดล{" "}
        {prediction.model_version}
      </p>
    </div>
  );
}

function TeamGoals({
  name,
  venue,
  value,
  align,
}: {
  name: string;
  venue: string;
  value: number;
  align: "left" | "right";
}) {
  return (
    <div className={align === "right" ? "text-right" : "text-left"}>
      <p className="text-xs tracking-wide text-ink-muted">{venue}</p>
      <p className="mt-0.5 truncate text-sm font-medium text-ink-secondary">{name}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-ink tabular">
        {goals(value)}
      </p>
    </div>
  );
}
