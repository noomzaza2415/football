"""Flat table exports, for spreadsheets.

Everything here produces the same shape: a header row plus data rows, as plain
Python values. The CSV endpoints and the Google Sheets writer both consume
these, so a column added once appears in both places.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import services
from app.models import Match, Prediction


def _date_parts(value: datetime | None) -> tuple[str, str]:
    """Split a timestamp into date and time columns.

    A spreadsheet treats a full ISO timestamp as text, so it cannot sort or
    filter on it. Two plain columns behave the way a user expects.
    """
    if value is None:
        return "", ""
    return value.date().isoformat(), value.strftime("%H:%M")


def matches_table(
    db: Session, *, league: str | None = None, limit: int = 5000
) -> tuple[list[str], list[list[Any]]]:
    """Every match with its result and stored market prices."""
    stmt = (
        select(Match)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
        .order_by(Match.match_date.asc())
        .limit(limit)
    )
    if league:
        stmt = stmt.where(Match.league == league)

    header = [
        "match_id",
        "date",
        "time",
        "league",
        "season",
        "status",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        "total_goals",
        "result_2_5",
        "market_line",
        "odds_over",
        "odds_under",
    ]

    rows: list[list[Any]] = []
    for match in db.execute(stmt).scalars().all():
        day, clock = _date_parts(match.match_date)
        total = match.total_goals
        rows.append(
            [
                match.id,
                day,
                clock,
                match.league,
                match.season or "",
                match.status.value,
                match.home_team.name,
                match.away_team.name,
                match.home_goals if match.home_goals is not None else "",
                match.away_goals if match.away_goals is not None else "",
                total if total is not None else "",
                "" if total is None else ("OVER" if total > 2.5 else "UNDER"),
                match.market_line if match.market_line is not None else "",
                match.market_odds_over if match.market_odds_over is not None else "",
                match.market_odds_under if match.market_odds_under is not None else "",
            ]
        )

    return header, rows


def predictions_table(
    db: Session, *, limit: int = 5000
) -> tuple[list[str], list[list[Any]]]:
    """Every stored prediction beside the result it was scored against."""
    stmt = (
        select(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
        .order_by(Prediction.created_at.desc())
        .limit(limit)
    )

    header = [
        "prediction_id",
        "match_id",
        "match_date",
        "league",
        "home_team",
        "away_team",
        "expected_home_goals",
        "expected_away_goals",
        "predicted_total_goals",
        "prob_over_1_5",
        "prob_over_2_5",
        "prob_over_3_5",
        "prob_home_win",
        "prob_draw",
        "prob_away_win",
        "sample_matches",
        "model_version",
        "created_at",
        "actual_home_goals",
        "actual_away_goals",
        "actual_total_goals",
        "actual_result",
    ]

    rows: list[list[Any]] = []
    for prediction, match in db.execute(stmt).all():
        total = match.total_goals
        day, _ = _date_parts(match.match_date)
        created, _ = _date_parts(prediction.created_at)
        rows.append(
            [
                prediction.id,
                match.id,
                day,
                match.league,
                match.home_team.name,
                match.away_team.name,
                round(prediction.expected_home_goals, 4),
                round(prediction.expected_away_goals, 4),
                round(prediction.predicted_total_goals, 4),
                round(prediction.prob_over_1_5, 6),
                round(prediction.prob_over_2_5, 6),
                round(prediction.prob_over_3_5, 6),
                round(prediction.prob_home_win, 6),
                round(prediction.prob_draw, 6),
                round(prediction.prob_away_win, 6),
                prediction.sample_matches,
                prediction.model_version,
                created,
                match.home_goals if match.home_goals is not None else "",
                match.away_goals if match.away_goals is not None else "",
                total if total is not None else "",
                "" if total is None else ("OVER" if total > 2.5 else "UNDER"),
            ]
        )

    return header, rows


def backtest_table(
    db: Session, *, league: str | None = None, min_train_matches: int = 300
) -> tuple[list[str], list[list[Any]]]:
    """Every out-of-sample prediction from a walk-forward run.

    This is the table worth analysing in a spreadsheet: one row per match the
    model had never seen, with what it said and what happened.
    """
    report = services.run_backtest(
        db, league=league, min_train_matches=min_train_matches
    )

    header = [
        "match_id",
        "date",
        "league",
        "home_team",
        "away_team",
        "train_size",
        "predicted_total_goals",
        "prob_over",
        "pick",
        "home_goals",
        "away_goals",
        "total_goals",
        "actual_result",
        "correct",
        "odds_over",
        "odds_under",
        "profit",
        "market_prob_over",
    ]

    rows: list[list[Any]] = []
    for record in report.records:
        day, _ = _date_parts(record.kickoff)
        profit = record.profit()
        rows.append(
            [
                record.match_id,
                day,
                record.league,
                record.home_name,
                record.away_name,
                record.train_size,
                round(record.predicted_total_goals, 4),
                round(record.prob_over, 6),
                record.pick,
                record.actual_home_goals,
                record.actual_away_goals,
                record.actual_total_goals,
                "OVER" if record.actual_over else "UNDER",
                "" if record.correct is None else int(record.correct),
                record.decimal_odds_over if record.decimal_odds_over else "",
                record.decimal_odds_under if record.decimal_odds_under else "",
                "" if profit is None else round(profit, 4),
                ""
                if record.market_prob_over is None
                else round(record.market_prob_over, 6),
            ]
        )

    return header, rows


def team_stats_table(db: Session) -> tuple[list[str], list[list[Any]]]:
    """One row per team: the aggregates and the fitted strengths."""
    header = [
        "team_id",
        "team",
        "league",
        "matches_played",
        "avg_goals_scored_home",
        "avg_goals_scored_away",
        "avg_goals_conceded_home",
        "avg_goals_conceded_away",
        "avg_total_goals",
        "over_2_5_rate",
        "btts_rate",
        "form_last_5",
        "attack_strength_home",
        "attack_strength_away",
        "defense_strength_home",
        "defense_strength_away",
    ]

    rows: list[list[Any]] = []
    for team in services.list_teams(db):
        stats = services.get_team_stats(db, team.id)
        if stats is None:
            continue
        rows.append(
            [
                team.id,
                team.name,
                team.league,
                stats.matches_played,
                round(stats.avg_goals_scored_home, 4),
                round(stats.avg_goals_scored_away, 4),
                round(stats.avg_goals_conceded_home, 4),
                round(stats.avg_goals_conceded_away, 4),
                round(stats.avg_total_goals, 4),
                round(stats.over_2_5_rate, 4),
                round(stats.btts_rate, 4),
                stats.form_last_5,
                round(stats.attack_strength_home, 4),
                round(stats.attack_strength_away, 4),
                round(stats.defense_strength_home, 4),
                round(stats.defense_strength_away, 4),
            ]
        )

    return header, rows


TABLES = {
    "matches": matches_table,
    "predictions": predictions_table,
    "backtest": backtest_table,
    "team_stats": team_stats_table,
}


#: Which optional arguments each builder understands, so a caller can pass one
#: set of options for any table without every builder having to accept them all.
TABLE_OPTIONS: dict[str, set[str]] = {
    "matches": {"league", "limit"},
    "predictions": {"limit"},
    "backtest": {"league", "min_train_matches"},
    "team_stats": set(),
}


def build_table(db: Session, name: str, **options) -> tuple[list[str], list[list[Any]]]:
    """One table by name. Options the chosen table does not take are ignored."""
    if name not in TABLES:
        raise KeyError(f"unknown table {name!r}; choose from {sorted(TABLES)}")

    accepted = TABLE_OPTIONS[name]
    usable = {
        key: value
        for key, value in options.items()
        if key in accepted and value is not None
    }
    return TABLES[name](db, **usable)


def to_csv(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """A table as CSV text, with the BOM spreadsheets want for UTF-8."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()
