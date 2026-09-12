"""Service layer: turn rows in the database into model input and back again.

The routers stay thin; every query and every conversion between ORM objects
and the pure analytics dataclasses lives here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.analytics import odds as odds_lib
from app.analytics.backtest import (
    DEFAULT_MIN_TRAIN_MATCHES,
    BacktestReport,
    DatedMatch,
    NotEnoughHistoryError,
    WindowMode,
    walk_forward,
)
from app.analytics.poisson_model import (
    DEFAULT_LINES,
    MODEL_VERSION,
    InsufficientDataError,
    MatchPrediction,
    MatchResult,
    compute_league_averages,
    compute_team_strengths,
    predict_match,
)
from app.analytics.stats_builder import build_all_team_stats
from app.config import get_settings
from app.models import Match, MatchStatus, Prediction, Team, TeamStats
from app.schemas import (
    CalibrationBucket,
    LineProbabilityOut,
    MarketComparisonOut,
    MatchSummaryOut,
    PredictionHistoryItem,
    PredictionOut,
    ScorelineOut,
    TotalGoalsBucket,
)

settings = get_settings()

TOP_SCORELINES = 6
NEUTRAL_EDGE_THRESHOLD = 0.03


# --------------------------------------------------------------------------- #
# Loading history
# --------------------------------------------------------------------------- #
def finished_matches_query(league: str | None = None, before: datetime | None = None):
    stmt = (
        select(Match)
        .where(
            Match.status == MatchStatus.FINISHED,
            Match.home_goals.is_not(None),
            Match.away_goals.is_not(None),
        )
        .order_by(Match.match_date.asc())
    )
    if league:
        stmt = stmt.where(Match.league == league)
    if before:
        stmt = stmt.where(Match.match_date < before)
    return stmt


def load_history(
    db: Session, league: str | None = None, before: datetime | None = None
) -> list[MatchResult]:
    """Finished matches as plain model input, oldest first.

    ``before`` is what keeps a backtest honest: when re-scoring a match that
    has already been played, only matches that finished before kick-off are
    allowed into the fit.
    """
    rows = db.execute(finished_matches_query(league, before)).scalars().all()
    return [
        MatchResult(
            home_team_id=row.home_team_id,
            away_team_id=row.away_team_id,
            home_goals=int(row.home_goals),
            away_goals=int(row.away_goals),
        )
        for row in rows
    ]


# --------------------------------------------------------------------------- #
# Running the model
# --------------------------------------------------------------------------- #
def run_model_for_match(
    db: Session,
    match: Match,
    *,
    last_n: int | None = None,
    max_goals: int | None = None,
    rho: float | None = None,
    lines: Iterable[float] | None = None,
    point_in_time: bool = False,
) -> tuple[MatchPrediction, int]:
    """Fit the model on this match's league and predict it.

    Returns the prediction and the number of finished matches it was fitted
    on, which the UI shows so a thin sample is visible rather than hidden.
    """
    before = match.match_date if point_in_time else None
    history = load_history(db, league=match.league, before=before)

    if len(history) < 20:
        # Fall back to every league so a newly seeded database still works.
        history = load_history(db, before=before)
    if not history:
        raise InsufficientDataError(
            "no finished matches available to fit the model; run the ingest script first"
        )

    league_averages = compute_league_averages(history)
    strengths = compute_team_strengths(
        history,
        league_averages,
        last_n=last_n or settings.model_last_n_matches,
        shrinkage=settings.shrinkage,
    )

    prediction = predict_match(
        match.home_team_id,
        match.away_team_id,
        strengths,
        league_averages,
        lines=lines or settings.line_list or DEFAULT_LINES,
        max_goals=max_goals or settings.model_max_goals,
        rho=settings.model_rho if rho is None else rho,
    )
    return prediction, len(history)


def store_prediction(
    db: Session, match: Match, prediction: MatchPrediction, sample_matches: int
) -> Prediction:
    """Persist a model run so the history endpoint can score it later."""

    def line_prob(line: float, side: str) -> float:
        entry = prediction.lines.get(line)
        if entry is None:
            return 0.0
        return entry.prob_over if side == "over" else entry.prob_under

    row = Prediction(
        match_id=match.id,
        expected_home_goals=prediction.expected_home_goals,
        expected_away_goals=prediction.expected_away_goals,
        predicted_total_goals=prediction.expected_total_goals,
        prob_over_1_5=line_prob(1.5, "over"),
        prob_under_1_5=line_prob(1.5, "under"),
        prob_over_2_5=line_prob(2.5, "over"),
        prob_under_2_5=line_prob(2.5, "under"),
        prob_over_3_5=line_prob(3.5, "over"),
        prob_under_3_5=line_prob(3.5, "under"),
        prob_home_win=prediction.prob_home_win,
        prob_draw=prediction.prob_draw,
        prob_away_win=prediction.prob_away_win,
        most_likely_home_goals=prediction.most_likely_score[0],
        most_likely_away_goals=prediction.most_likely_score[1],
        total_goals_distribution={
            str(total): round(p, 6) for total, p in prediction.total_goals_distribution.items()
        },
        sample_matches=sample_matches,
        model_version=prediction.model_version,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_prediction(db: Session, match_id: int) -> Prediction | None:
    return db.execute(
        select(Prediction)
        .where(Prediction.match_id == match_id)
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .limit(1)
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Market comparison
# --------------------------------------------------------------------------- #
def build_market_comparison(
    match: Match, prediction: MatchPrediction
) -> list[MarketComparisonOut]:
    """Compare the model with the stored market price, if there is one."""
    line = match.market_line
    over_price = match.market_odds_over
    under_price = match.market_odds_under
    if line is None or over_price is None or under_price is None:
        return []

    entry = prediction.lines.get(float(line))
    if entry is None:
        return []

    comparisons: list[MarketComparisonOut] = []
    for selection, price, opposite, model_probability in (
        ("OVER", over_price, under_price, entry.prob_over),
        ("UNDER", under_price, over_price, entry.prob_under),
    ):
        try:
            assessment = odds_lib.assess_value(
                selection, price, model_probability, opposite_odds=opposite
            )
        except odds_lib.InvalidOddsError:
            continue
        comparisons.append(
            MarketComparisonOut(
                line=float(line),
                selection=selection,
                decimal_odds=assessment.decimal_odds,
                market_probability=assessment.market_probability,
                fair_market_probability=assessment.fair_market_probability,
                model_probability=assessment.model_probability,
                edge=assessment.edge,
                expected_value=assessment.expected_value,
                is_value=assessment.is_value,
                kelly_fraction=odds_lib.kelly_fraction(model_probability, price),
            )
        )
    return comparisons


def lean_at_line(prediction: MatchPrediction, line: float = 2.5) -> str:
    entry = prediction.lines.get(line)
    if entry is None:
        return "NEUTRAL"
    gap = entry.prob_over - entry.prob_under
    if gap > NEUTRAL_EDGE_THRESHOLD:
        return "OVER"
    if gap < -NEUTRAL_EDGE_THRESHOLD:
        return "UNDER"
    return "NEUTRAL"


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #
def top_scorelines(prediction: MatchPrediction, limit: int = TOP_SCORELINES) -> list[ScorelineOut]:
    matrix = prediction.score_matrix
    flat = [
        (int(h), int(a), float(matrix[h][a]))
        for h in range(matrix.shape[0])
        for a in range(matrix.shape[1])
    ]
    flat.sort(key=lambda item: item[2], reverse=True)
    return [
        ScorelineOut(home_goals=h, away_goals=a, probability=p) for h, a, p in flat[:limit]
    ]


def serialize_prediction(
    match: Match,
    prediction: MatchPrediction,
    sample_matches: int,
    created_at: datetime | None = None,
) -> PredictionOut:
    return PredictionOut(
        match=match,
        expected_home_goals=prediction.expected_home_goals,
        expected_away_goals=prediction.expected_away_goals,
        expected_total_goals=prediction.expected_total_goals,
        prob_home_win=prediction.prob_home_win,
        prob_draw=prediction.prob_draw,
        prob_away_win=prediction.prob_away_win,
        most_likely_score=f"{prediction.most_likely_score[0]}-{prediction.most_likely_score[1]}",
        lines=[
            LineProbabilityOut(
                line=entry.line,
                prob_over=entry.prob_over,
                prob_under=entry.prob_under,
                prob_push=entry.prob_push,
                fair_odds_over=entry.fair_odds_over,
                fair_odds_under=entry.fair_odds_under,
            )
            for entry in sorted(prediction.lines.values(), key=lambda e: e.line)
        ],
        total_goals_distribution=[
            TotalGoalsBucket(total_goals=total, probability=p)
            for total, p in sorted(prediction.total_goals_distribution.items())
            if p >= 1e-5
        ],
        top_scorelines=top_scorelines(prediction),
        market_comparison=build_market_comparison(match, prediction),
        sample_matches=sample_matches,
        model_version=prediction.model_version,
        created_at=created_at,
    )


def summarize_match(
    db: Session, match: Match, prediction: MatchPrediction | None, sample_matches: int
) -> MatchSummaryOut:
    if prediction is None:
        return MatchSummaryOut(match=match)

    entry = prediction.lines.get(2.5)
    edge: float | None = None
    comparison = build_market_comparison(match, prediction)
    for item in comparison:
        if item.selection == "OVER" and item.line == 2.5:
            edge = item.edge

    return MatchSummaryOut(
        match=match,
        expected_total_goals=prediction.expected_total_goals,
        prob_over_2_5=entry.prob_over if entry else None,
        prob_under_2_5=entry.prob_under if entry else None,
        lean=lean_at_line(prediction, 2.5),
        edge_over_2_5=edge,
        model_version=prediction.model_version,
    )


# --------------------------------------------------------------------------- #
# Queries used by the routers
# --------------------------------------------------------------------------- #
def list_teams(db: Session, league: str | None = None, search: str | None = None) -> list[Team]:
    stmt = select(Team).order_by(Team.league.asc(), Team.name.asc())
    if league:
        stmt = stmt.where(Team.league == league)
    if search:
        stmt = stmt.where(Team.name.ilike(f"%{search}%"))
    return list(db.execute(stmt).scalars().all())


def get_team(db: Session, team_id: int) -> Team | None:
    return db.get(Team, team_id)


def get_team_stats(db: Session, team_id: int) -> TeamStats | None:
    return db.execute(
        select(TeamStats).where(TeamStats.team_id == team_id)
    ).scalar_one_or_none()


def get_match(db: Session, match_id: int) -> Match | None:
    return db.execute(
        select(Match)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
        .where(Match.id == match_id)
    ).scalar_one_or_none()


def upcoming_matches(
    db: Session, *, days: int = 14, league: str | None = None, limit: int = 50
) -> list[Match]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(Match)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
        .where(
            Match.status == MatchStatus.SCHEDULED,
            Match.match_date >= now - timedelta(hours=3),
            Match.match_date <= now + timedelta(days=days),
        )
        .order_by(Match.match_date.asc())
        .limit(limit)
    )
    if league:
        stmt = stmt.where(Match.league == league)
    return list(db.execute(stmt).scalars().all())


def rebuild_team_stats(db: Session, league: str | None = None) -> int:
    """Recompute every team_stats row from the match history."""
    history = load_history(db, league=league)
    if not history:
        return 0

    rows = build_all_team_stats(history, last_n=settings.model_last_n_matches)
    existing = {
        row.team_id: row for row in db.execute(select(TeamStats)).scalars().all()
    }

    for team_id, computed in rows.items():
        target = existing.get(team_id) or TeamStats(team_id=team_id)
        for field_name, value in vars(computed).items():
            if field_name == "team_id":
                continue
            setattr(target, field_name, value)
        db.add(target)

    db.commit()
    return len(rows)


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #
def _bucket_label(probability: float) -> str:
    lower = int(probability * 10) * 10
    lower = min(lower, 90)
    return f"{lower}-{lower + 10}%"


def prediction_history(
    db: Session, *, league: str | None = None, limit: int = 200, model_version: str | None = None
) -> dict:
    """Every stored prediction whose match has since finished, plus accuracy.

    A prediction counts as correct when the side it leaned to at the 2.5 line
    matches what actually happened. Predictions within three percentage points
    of a coin flip are recorded as NEUTRAL and excluded from the hit rate.
    """
    stmt = (
        select(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
        .where(
            Match.status == MatchStatus.FINISHED,
            Match.home_goals.is_not(None),
            Match.away_goals.is_not(None),
        )
        .order_by(Match.match_date.desc())
        .limit(limit)
    )
    if league:
        stmt = stmt.where(Match.league == league)
    if model_version:
        stmt = stmt.where(Prediction.model_version == model_version)

    rows = db.execute(stmt).all()

    items: list[PredictionHistoryItem] = []
    brier_terms: list[float] = []
    goal_errors: list[float] = []
    buckets: dict[str, list[float]] = {}

    over_picks = over_hits = under_picks = under_hits = 0

    for prediction, match in rows:
        actual_total = int(match.home_goals) + int(match.away_goals)
        actual_over = actual_total > 2.5
        gap = prediction.prob_over_2_5 - prediction.prob_under_2_5

        if gap > NEUTRAL_EDGE_THRESHOLD:
            pick = "OVER"
        elif gap < -NEUTRAL_EDGE_THRESHOLD:
            pick = "UNDER"
        else:
            pick = "NEUTRAL"

        correct = (pick == "OVER" and actual_over) or (pick == "UNDER" and not actual_over)
        if pick == "OVER":
            over_picks += 1
            over_hits += int(actual_over)
        elif pick == "UNDER":
            under_picks += 1
            under_hits += int(not actual_over)

        brier_terms.append((prediction.prob_over_2_5 - float(actual_over)) ** 2)
        goal_errors.append(abs(prediction.predicted_total_goals - actual_total))
        buckets.setdefault(_bucket_label(prediction.prob_over_2_5), []).append(
            float(actual_over)
        )

        items.append(
            PredictionHistoryItem(
                match_id=match.id,
                match_date=match.match_date,
                league=match.league,
                home_team=match.home_team.name,
                away_team=match.away_team.name,
                predicted_total_goals=prediction.predicted_total_goals,
                prob_over_2_5=prediction.prob_over_2_5,
                model_pick=pick,
                actual_home_goals=int(match.home_goals),
                actual_away_goals=int(match.away_goals),
                actual_total_goals=actual_total,
                actual_result="OVER" if actual_over else "UNDER",
                correct=correct,
                model_version=prediction.model_version,
                created_at=prediction.created_at,
            )
        )

    evaluated = over_picks + under_picks
    correct_count = over_hits + under_hits

    calibration = [
        CalibrationBucket(
            bucket=label,
            predicted_probability=(int(label.split("-")[0]) + 5) / 100,
            actual_rate=float(np.mean(values)),
            samples=len(values),
        )
        for label, values in sorted(buckets.items())
    ]

    return {
        "items": items,
        "total": len(items),
        "evaluated": evaluated,
        "correct": correct_count,
        "accuracy": correct_count / evaluated if evaluated else 0.0,
        "over_picks": over_picks,
        "under_picks": under_picks,
        "over_hit_rate": over_hits / over_picks if over_picks else 0.0,
        "under_hit_rate": under_hits / under_picks if under_picks else 0.0,
        "brier_score": float(np.mean(brier_terms)) if brier_terms else 0.0,
        "mean_absolute_goal_error": float(np.mean(goal_errors)) if goal_errors else 0.0,
        "calibration": calibration,
    }


def counts(db: Session) -> dict[str, int]:
    return {
        "teams": db.execute(select(func.count(Team.id))).scalar_one(),
        "matches": db.execute(select(func.count(Match.id))).scalar_one(),
        "finished_matches": db.execute(
            select(func.count(Match.id)).where(Match.status == MatchStatus.FINISHED)
        ).scalar_one(),
        "predictions": db.execute(select(func.count(Prediction.id))).scalar_one(),
    }


# --------------------------------------------------------------------------- #
# Walk-forward backtest
# --------------------------------------------------------------------------- #
def load_dated_matches(db: Session, league: str | None = None) -> list[DatedMatch]:
    """Finished matches with kick-off and any stored price, oldest first."""
    stmt = (
        finished_matches_query(league)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
    )
    rows = db.execute(stmt).scalars().all()

    return [
        DatedMatch(
            match_id=row.id,
            kickoff=row.match_date,
            league=row.league,
            home_team_id=row.home_team_id,
            away_team_id=row.away_team_id,
            home_goals=int(row.home_goals),
            away_goals=int(row.away_goals),
            home_name=row.home_team.name,
            away_name=row.away_team.name,
            market_line=row.market_line,
            market_odds_over=row.market_odds_over,
            market_odds_under=row.market_odds_under,
        )
        for row in rows
    ]


def run_backtest(
    db: Session,
    *,
    league: str | None = None,
    min_train_matches: int = DEFAULT_MIN_TRAIN_MATCHES,
    window: WindowMode = "expanding",
    train_window: int | None = None,
    last_n: int | None = None,
    rho: float | None = None,
    line: float = 2.5,
    shrinkage: float | str | None = "__default__",
) -> BacktestReport:
    """Load history from the database and walk forward through it."""
    matches = load_dated_matches(db, league=league)
    return walk_forward(
        matches,
        min_train_matches=min_train_matches,
        window=window,
        train_window=train_window,
        last_n=last_n or settings.model_last_n_matches,
        max_goals=settings.model_max_goals,
        rho=settings.model_rho if rho is None else rho,
        line=line,
        shrinkage=settings.shrinkage if shrinkage == "__default__" else shrinkage,
    )
