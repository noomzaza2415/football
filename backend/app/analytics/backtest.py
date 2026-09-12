"""Walk-forward backtesting.

The question this module answers is not "how well does the model describe the
matches it was fitted on" but "how well would it have done on matches it had
never seen". Those are very different numbers, and only the second one means
anything.

The procedure is strictly chronological:

1. Sort every finished match by kick-off.
2. Skip the first ``min_train_matches``; there is nothing to fit on yet.
3. For each remaining match, fit league averages and team strengths using
   **only matches that kicked off before it**, predict, then reveal the result
   and score the prediction.
4. Move the boundary forward one match and repeat.

Nothing about a match, or any match after it, can reach the fit that predicts
it. That is what makes the result out of sample.

Two window modes are supported. ``expanding`` trains on all prior history,
which is the usual choice. ``rolling`` trains on only the most recent N prior
matches, which tests whether old results are still informative.

A raw accuracy number is close to meaningless on its own, so every run is
scored against three baselines:

- **always over** - bet Over every time, the laziest possible strategy.
- **base rate** - predict the historical Over rate observed so far.
- **league only** - the same Poisson machinery but with every team forced to
  average strength, which isolates what the team-strength step actually adds.
- **market** - the posted price with the margin removed, where odds exist.
  A model that cannot beat this has no edge, whatever its accuracy looks like.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Literal, Sequence

import numpy as np

from app.analytics.odds import implied_probability, remove_vig
from app.analytics.poisson_model import (
    DEFAULT_LINES,
    DEFAULT_MAX_GOALS,
    MODEL_VERSION,
    LeagueAverages,
    MatchResult,
    Shrinkage,
    compute_league_averages,
    compute_team_strengths,
    predict_match,
    score_matrix,
    over_under_probability,
)

DEFAULT_MIN_TRAIN_MATCHES = 60
DEFAULT_LINE = 2.5
NEUTRAL_EDGE_THRESHOLD = 0.03

WindowMode = Literal["expanding", "rolling"]


class NotEnoughHistoryError(ValueError):
    """Raised when there are fewer matches than the training window needs."""


@dataclass(frozen=True)
class DatedMatch:
    """A finished match with everything the backtest needs, including odds."""

    match_id: int
    kickoff: datetime
    league: str
    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int
    home_name: str = ""
    away_name: str = ""
    market_line: float | None = None
    market_odds_over: float | None = None
    market_odds_under: float | None = None

    @property
    def total_goals(self) -> int:
        return self.home_goals + self.away_goals

    def as_result(self) -> MatchResult:
        return MatchResult(
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            home_goals=self.home_goals,
            away_goals=self.away_goals,
        )


@dataclass(frozen=True)
class BacktestRecord:
    """One out-of-sample prediction with the result that followed it."""

    match_id: int
    kickoff: datetime
    league: str
    home_name: str
    away_name: str
    train_size: int

    expected_home_goals: float
    expected_away_goals: float
    predicted_total_goals: float
    prob_over: float

    baseline_base_rate: float
    baseline_league_only: float
    market_prob_over: float | None

    actual_home_goals: int
    actual_away_goals: int

    decimal_odds_over: float | None = None
    decimal_odds_under: float | None = None

    @property
    def prob_under(self) -> float:
        return 1.0 - self.prob_over

    @property
    def actual_total_goals(self) -> int:
        return self.actual_home_goals + self.actual_away_goals

    @property
    def actual_over(self) -> bool:
        return self.actual_total_goals > DEFAULT_LINE

    @property
    def pick(self) -> str:
        gap = self.prob_over - self.prob_under
        if gap > NEUTRAL_EDGE_THRESHOLD:
            return "OVER"
        if gap < -NEUTRAL_EDGE_THRESHOLD:
            return "UNDER"
        return "NEUTRAL"

    @property
    def correct(self) -> bool | None:
        """None when the model had no opinion, so it is not scored."""
        if self.pick == "NEUTRAL":
            return None
        return (self.pick == "OVER") == self.actual_over

    def staked_odds(self) -> float | None:
        """The price the pick would have been taken at, if one exists."""
        if self.pick == "OVER":
            return self.decimal_odds_over
        if self.pick == "UNDER":
            return self.decimal_odds_under
        return None

    def profit(self) -> float | None:
        """Profit from a 1 unit flat stake on the pick, or None if unpriced."""
        price = self.staked_odds()
        if price is None or self.correct is None:
            return None
        return (price - 1.0) if self.correct else -1.0


@dataclass
class ScoreCard:
    """Probabilistic scores for one forecaster over the same set of matches."""

    name: str
    brier: float
    log_loss: float
    samples: int

    def skill_against(self, baseline: "ScoreCard") -> float:
        """Brier skill score: 1 means perfect, 0 means no better than baseline."""
        if baseline.brier <= 0:
            return 0.0
        return 1.0 - (self.brier / baseline.brier)


@dataclass
class CalibrationBin:
    bucket: str
    predicted_probability: float
    actual_rate: float
    samples: int


@dataclass
class BacktestReport:
    """Everything one walk-forward run produced."""

    records: list[BacktestRecord] = field(default_factory=list)

    # Configuration, echoed back so a report is self-describing.
    model_version: str = MODEL_VERSION
    window: WindowMode = "expanding"
    train_window: int | None = None
    min_train_matches: int = DEFAULT_MIN_TRAIN_MATCHES
    last_n: int = 20
    rho: float = 0.0
    line: float = DEFAULT_LINE
    shrinkage: Shrinkage = None

    # --- headline counts ---------------------------------------------------
    @property
    def tested(self) -> int:
        return len(self.records)

    @property
    def scored(self) -> list[BacktestRecord]:
        return [r for r in self.records if r.correct is not None]

    @property
    def accuracy(self) -> float:
        scored = self.scored
        if not scored:
            return 0.0
        return sum(1 for r in scored if r.correct) / len(scored)

    @property
    def actual_over_rate(self) -> float:
        if not self.records:
            return 0.0
        return sum(1 for r in self.records if r.actual_over) / len(self.records)

    # --- goal error --------------------------------------------------------
    @property
    def mean_absolute_goal_error(self) -> float:
        if not self.records:
            return 0.0
        return float(
            np.mean([abs(r.predicted_total_goals - r.actual_total_goals) for r in self.records])
        )

    @property
    def rmse_goals(self) -> float:
        if not self.records:
            return 0.0
        errors = [(r.predicted_total_goals - r.actual_total_goals) ** 2 for r in self.records]
        return float(np.sqrt(np.mean(errors)))

    # --- probabilistic scores ---------------------------------------------
    def scorecards(self) -> list[ScoreCard]:
        """Model and baselines, scored on exactly the same matches."""
        if not self.records:
            return []

        outcomes = np.array([float(r.actual_over) for r in self.records])

        cards = [
            _score("โมเดล", np.array([r.prob_over for r in self.records]), outcomes),
            _score(
                "ทายสูงทุกนัด",
                np.ones_like(outcomes) * 0.999,
                outcomes,
            ),
            _score(
                "อัตราสูงในอดีต",
                np.array([r.baseline_base_rate for r in self.records]),
                outcomes,
            ),
            _score(
                "Poisson ค่าเฉลี่ยลีกล้วน",
                np.array([r.baseline_league_only for r in self.records]),
                outcomes,
            ),
        ]

        # The market is only scored where a price actually existed, so it gets
        # its own subset rather than being compared on different matches.
        priced = [r for r in self.records if r.market_prob_over is not None]
        if priced:
            cards.append(
                _score(
                    "ตลาด (หักค่าน้ำแล้ว)",
                    np.array([r.market_prob_over for r in priced]),
                    np.array([float(r.actual_over) for r in priced]),
                )
            )
            cards.append(
                _score(
                    "โมเดล (เฉพาะนัดที่มีราคา)",
                    np.array([r.prob_over for r in priced]),
                    np.array([float(r.actual_over) for r in priced]),
                )
            )

        return cards

    @property
    def brier(self) -> float:
        cards = self.scorecards()
        return cards[0].brier if cards else 0.0

    # --- money -------------------------------------------------------------
    @property
    def priced_picks(self) -> list[BacktestRecord]:
        return [r for r in self.scored if r.profit() is not None]

    @property
    def profit(self) -> float:
        return float(sum(r.profit() or 0.0 for r in self.priced_picks))

    @property
    def roi(self) -> float:
        """Return per unit staked, flat staking every non-neutral pick."""
        picks = self.priced_picks
        if not picks:
            return 0.0
        return self.profit / len(picks)

    # --- calibration -------------------------------------------------------
    def calibration(self, bins: int = 10) -> list[CalibrationBin]:
        if not self.records:
            return []

        buckets: dict[int, list[float]] = {}
        for record in self.records:
            index = min(int(record.prob_over * bins), bins - 1)
            buckets.setdefault(index, []).append(float(record.actual_over))

        width = 100 // bins
        return [
            CalibrationBin(
                bucket=f"{index * width}-{(index + 1) * width}%",
                predicted_probability=(index * width + width / 2) / 100,
                actual_rate=float(np.mean(values)),
                samples=len(values),
            )
            for index, values in sorted(buckets.items())
        ]


def _score(name: str, predictions: np.ndarray, outcomes: np.ndarray) -> ScoreCard:
    """Brier score and log loss, both lower-is-better."""
    clipped = np.clip(predictions, 1e-9, 1 - 1e-9)
    brier = float(np.mean((clipped - outcomes) ** 2))
    log_loss = float(
        -np.mean(outcomes * np.log(clipped) + (1 - outcomes) * np.log(1 - clipped))
    )
    return ScoreCard(name=name, brier=brier, log_loss=log_loss, samples=len(outcomes))


def _market_probability(match: DatedMatch, line: float) -> float | None:
    """Vig-free market probability of Over, when both prices are present."""
    if (
        match.market_line is None
        or match.market_odds_over is None
        or match.market_odds_under is None
        or float(match.market_line) != float(line)
    ):
        return None
    try:
        return remove_vig([match.market_odds_over, match.market_odds_under])[0]
    except Exception:
        return None


def _league_only_probability(league: LeagueAverages, line: float, max_goals: int) -> float:
    """P(over) if both sides were exactly average, the no-information Poisson."""
    matrix = score_matrix(league.home_goals, league.away_goals, max_goals)
    return over_under_probability(matrix, line).prob_over


def walk_forward(
    matches: Sequence[DatedMatch],
    *,
    min_train_matches: int = DEFAULT_MIN_TRAIN_MATCHES,
    window: WindowMode = "expanding",
    train_window: int | None = None,
    last_n: int = 20,
    max_goals: int = DEFAULT_MAX_GOALS,
    rho: float = 0.0,
    line: float = DEFAULT_LINE,
    shrinkage: Shrinkage = None,
) -> BacktestReport:
    """Run the walk-forward backtest over ``matches``.

    ``matches`` may arrive in any order; it is sorted by kick-off here so the
    caller cannot accidentally leak the future by passing a bad ordering.
    """
    if min_train_matches < 10:
        raise ValueError("min_train_matches must be at least 10 to fit anything")
    if window == "rolling" and not train_window:
        raise ValueError("rolling mode needs a train_window")

    ordered = sorted(matches, key=lambda m: (m.kickoff, m.match_id))
    if len(ordered) <= min_train_matches:
        raise NotEnoughHistoryError(
            f"need more than {min_train_matches} finished matches to backtest, "
            f"got {len(ordered)}"
        )

    report = BacktestReport(
        window=window,
        train_window=train_window,
        min_train_matches=min_train_matches,
        last_n=last_n,
        rho=rho,
        line=line,
        shrinkage=shrinkage,
    )

    # Results of everything already revealed, in chronological order. The
    # match being predicted is appended only after its prediction is recorded,
    # which is the mechanical guarantee that no future data reaches the fit.
    revealed: list[MatchResult] = [m.as_result() for m in ordered[:min_train_matches]]
    over_count = sum(1 for m in ordered[:min_train_matches] if m.total_goals > line)

    for match in ordered[min_train_matches:]:
        train = revealed[-train_window:] if train_window else revealed

        league = compute_league_averages(train)
        strengths = compute_team_strengths(
            train, league, last_n=last_n, shrinkage=shrinkage
        )

        prediction = predict_match(
            match.home_team_id,
            match.away_team_id,
            strengths,
            league,
            lines=[line],
            max_goals=max_goals,
            rho=rho,
        )

        report.records.append(
            BacktestRecord(
                match_id=match.match_id,
                kickoff=match.kickoff,
                league=match.league,
                home_name=match.home_name,
                away_name=match.away_name,
                train_size=len(train),
                expected_home_goals=prediction.expected_home_goals,
                expected_away_goals=prediction.expected_away_goals,
                predicted_total_goals=prediction.expected_total_goals,
                prob_over=prediction.lines[line].prob_over,
                baseline_base_rate=over_count / len(revealed),
                baseline_league_only=_league_only_probability(league, line, max_goals),
                market_prob_over=_market_probability(match, line),
                actual_home_goals=match.home_goals,
                actual_away_goals=match.away_goals,
                decimal_odds_over=match.market_odds_over,
                decimal_odds_under=match.market_odds_under,
            )
        )

        # Only now is the result allowed into the training set.
        revealed.append(match.as_result())
        if match.total_goals > line:
            over_count += 1

    return report


def format_report(report: BacktestReport, *, top_rows: int = 0) -> str:
    """A plain-text summary, for the CLI and for logs."""
    lines: list[str] = []
    add = lines.append

    add("=" * 72)
    add("ผลการทดสอบย้อนหลังแบบ walk-forward")
    add("=" * 72)
    add(f"โมเดล            : {report.model_version}")
    add(
        f"วิธีเทรน          : {report.window}"
        + (f" (หน้าต่าง {report.train_window} นัด)" if report.train_window else " (ขยายไปเรื่อย ๆ)")
    )
    add(f"ข้อมูลเริ่มต้น     : {report.min_train_matches} นัด")
    add(f"ฟอร์มย้อนหลัง     : {report.last_n} นัดต่อทีม")
    add(f"ค่า rho          : {report.rho}")
    add(f"Shrinkage        : {report.shrinkage if report.shrinkage is not None else 'ปิด'}")
    add(f"เส้นที่ทดสอบ      : {report.line}")
    add("")
    add(f"นัดที่ทดสอบ       : {report.tested}")
    add(f"นัดที่ให้คะแนน     : {len(report.scored)} (ไม่นับนัดที่โมเดลก้ำกึ่ง)")
    add(f"อัตราทายถูก       : {report.accuracy * 100:.1f}%")
    add(f"อัตราออกสูงจริง    : {report.actual_over_rate * 100:.1f}%")
    add(f"คลาดเคลื่อนประตู   : {report.mean_absolute_goal_error:.3f} เฉลี่ย, {report.rmse_goals:.3f} RMSE")
    add("")

    add("-" * 72)
    add("เทียบกับเกณฑ์อ้างอิง (ยิ่งต่ำยิ่งดีทั้งสองคอลัมน์)")
    add("-" * 72)
    add(f"{'ผู้ทำนาย':<34}{'Brier':>10}{'Log loss':>12}{'นัด':>8}")
    for card in report.scorecards():
        add(f"{card.name:<34}{card.brier:>10.4f}{card.log_loss:>12.4f}{card.samples:>8}")

    cards = report.scorecards()
    if len(cards) >= 4:
        model, base_rate, league_only = cards[0], cards[2], cards[3]
        add("")
        add(f"Skill score เทียบอัตราสูงในอดีต      : {model.skill_against(base_rate):+.4f}")
        add(f"Skill score เทียบ Poisson ค่าเฉลี่ยลีก : {model.skill_against(league_only):+.4f}")
        add("  (บวก = ดีกว่าเกณฑ์อ้างอิง, ลบ = แย่กว่า)")
    if len(cards) == 6:
        add(f"Skill score เทียบตลาด               : {cards[5].skill_against(cards[4]):+.4f}")

    picks = report.priced_picks
    if picks:
        add("")
        add("-" * 72)
        add("ถ้าลงเงินจริงเท่ากันทุกนัดที่โมเดลมีความเห็น")
        add("-" * 72)
        add(f"จำนวนครั้งที่ลง   : {len(picks)}")
        add(f"กำไรขาดทุนรวม    : {report.profit:+.2f} หน่วย")
        add(f"ผลตอบแทนต่อหน่วย : {report.roi * 100:+.2f}%")

    add("")
    add("-" * 72)
    add("ความแม่นของค่าความน่าจะเป็น")
    add("-" * 72)
    add(f"{'ช่วงที่โมเดลให้':<18}{'ออกสูงจริง':>14}{'จำนวนนัด':>12}")
    for bucket in report.calibration():
        add(f"{bucket.bucket:<18}{bucket.actual_rate * 100:>13.1f}%{bucket.samples:>12}")

    if top_rows:
        add("")
        add("-" * 72)
        add(f"ตัวอย่าง {top_rows} นัดล่าสุด")
        add("-" * 72)
        for record in report.records[-top_rows:]:
            mark = "-" if record.correct is None else ("ถูก" if record.correct else "ผิด")
            add(
                f"{record.kickoff:%Y-%m-%d} {record.home_name[:18]:<18} "
                f"{record.away_name[:18]:<18} คาด {record.predicted_total_goals:4.2f} "
                f"สูง {record.prob_over * 100:5.1f}% -> {record.pick:<7} "
                f"จริง {record.actual_home_goals}-{record.actual_away_goals} {mark}"
            )

    add("")
    add("หมายเหตุ: ผลในอดีตไม่รับประกันผลในอนาคต ตัวเลขชุดนี้ใช้ตรวจสอบโมเดลเท่านั้น")
    return "\n".join(lines)
