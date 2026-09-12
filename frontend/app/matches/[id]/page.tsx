import { notFound } from "next/navigation";

import LinesChart from "@/components/charts/LinesChart";
import TotalGoalsChart from "@/components/charts/TotalGoalsChart";
import { DisclaimerBanner } from "@/components/Disclaimer";
import ExpectedGoalsPanel from "@/components/ExpectedGoalsPanel";
import MarketComparison from "@/components/MarketComparison";
import OverUnderTable from "@/components/OverUnderTable";
import { BackLink, Badge, BackendDownState, Panel, PageHeading } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatKickoff, leanStyles, percent } from "@/lib/format";
import type { Lean } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function MatchPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const matchId = Number(id);

  if (!Number.isInteger(matchId) || matchId <= 0) {
    notFound();
  }

  let prediction;
  try {
    prediction = await api.prediction(matchId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    if (error instanceof ApiError && error.status === 0) {
      return <BackendDownState />;
    }
    throw error;
  }

  const { match } = prediction;
  const line25 = prediction.lines.find((entry) => entry.line === 2.5);
  const lean: Lean =
    line25 === undefined
      ? "NEUTRAL"
      : line25.prob_over - line25.prob_under > 0.03
        ? "OVER"
        : line25.prob_under - line25.prob_over > 0.03
          ? "UNDER"
          : "NEUTRAL";
  const leanStyle = leanStyles(lean);

  return (
    <div className="space-y-6">
      <BackLink href="/">กลับไปหน้าโปรแกรมแข่ง</BackLink>

      <PageHeading
        title={`${match.home_team.name} พบ ${match.away_team.name}`}
        subtitle={`${match.league} · ${formatKickoff(match.match_date)}`}
        action={
          <Badge className={leanStyle.className}>
            {leanStyle.label}
            {line25 ? ` · สูง 2.5 ที่ ${percent(line25.prob_over, 0)}` : ""}
          </Badge>
        }
      />

      <DisclaimerBanner />

      <div className="grid gap-4 lg:grid-cols-5">
        <Panel
          title="ประตูที่คาดว่าจะได้"
          description="คำนวณจากพลังบุกและพลังรับของแต่ละทีมเทียบกับค่าเฉลี่ยของลีก"
          className="lg:col-span-2"
        >
          <ExpectedGoalsPanel prediction={prediction} />
        </Panel>

        <Panel
          title="การกระจายของประตูรวม"
          description="ความน่าจะเป็นที่แมตช์จะจบด้วยประตูรวมแต่ละจำนวน"
          className="lg:col-span-3"
        >
          <TotalGoalsChart data={prediction.total_goals_distribution} line={2.5} />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Panel
          title="สูง/ต่ำ แยกตามเส้น"
          description="อ่านค่าจากเมทริกซ์สกอร์ชุดเดียวกันที่ทุกเส้นซึ่งตั้งค่าไว้"
          className="lg:col-span-3"
        >
          <div className="space-y-5">
            <LinesChart lines={prediction.lines} />
            <OverUnderTable lines={prediction.lines} marketLine={match.market_line} />
          </div>
        </Panel>

        <Panel
          title="โมเดลเทียบกับตลาด"
          description="ราคาที่ตลาดเปิดไว้หลังหักค่าน้ำของเจ้ามือออกแล้ว"
          className="lg:col-span-2"
        >
          <MarketComparison items={prediction.market_comparison} />
        </Panel>
      </div>

      <Panel
        title="สกอร์ที่เป็นไปได้มากที่สุด"
        description="ช่องที่มีค่าสูงสุดในเมทริกซ์ความน่าจะเป็นของสกอร์"
      >
        <ul className="grid grid-cols-3 gap-3 sm:grid-cols-6">
          {prediction.top_scorelines.map((score) => (
            <li
              key={`${score.home_goals}-${score.away_goals}`}
              className="panel-raised px-3 py-2.5 text-center"
            >
              <p className="text-lg font-semibold text-ink tabular">
                {score.home_goals}&ndash;{score.away_goals}
              </p>
              <p className="mt-0.5 text-xs text-ink-muted tabular">
                {percent(score.probability, 1)}
              </p>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
