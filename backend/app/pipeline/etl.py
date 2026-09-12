"""ETL: upsert provider records into the project schema.

Every write is keyed on ``(external_id, source)`` so re-running the ingest is
safe: existing rows are updated in place rather than duplicated. That makes
the cron job idempotent, which matters because a scheduled run will re-fetch
the same fixtures many times before they are played.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Match, MatchStatus, Team
from app.pipeline.providers.base import FootballDataProvider, RawMatch, RawTeam

logger = logging.getLogger(__name__)


@dataclass
class IngestReport:
    """What one ingest run changed, for logging and the CLI summary."""

    teams_created: int = 0
    teams_updated: int = 0
    matches_created: int = 0
    matches_updated: int = 0
    matches_skipped: int = 0

    def __str__(self) -> str:
        return (
            f"teams +{self.teams_created}/~{self.teams_updated}, "
            f"matches +{self.matches_created}/~{self.matches_updated}, "
            f"skipped {self.matches_skipped}"
        )


def raw_matches_to_frame(matches: list[RawMatch]) -> pd.DataFrame:
    """Provider records as a DataFrame, for validation and quick inspection.

    pandas earns its place here: the transform step drops duplicate fixture
    ids, coerces the goal columns to a nullable integer type and sorts by
    kick-off, all of which are one-liners on a frame and fiddly in a loop.
    """
    if not matches:
        return pd.DataFrame()

    frame = pd.DataFrame([vars(m) for m in matches])
    frame = frame.drop_duplicates(subset=["external_id"], keep="last")
    frame["home_goals"] = pd.to_numeric(frame["home_goals"], errors="coerce").astype("Int64")
    frame["away_goals"] = pd.to_numeric(frame["away_goals"], errors="coerce").astype("Int64")

    for column in ("market_line", "market_odds_over", "market_odds_under"):
        if column not in frame.columns:
            frame[column] = None
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    # A match cannot be finished without a score; downgrade anything that is.
    incomplete = frame["status"].eq("finished") & (
        frame["home_goals"].isna() | frame["away_goals"].isna()
    )
    frame.loc[incomplete, "status"] = "scheduled"

    return frame.sort_values("match_date").reset_index(drop=True)


def upsert_teams(db: Session, teams: list[RawTeam], source: str) -> tuple[dict[str, int], IngestReport]:
    """Insert or update teams, returning a map from external id to row id."""
    report = IngestReport()
    existing = {
        team.external_id: team
        for team in db.execute(select(Team).where(Team.source == source)).scalars().all()
        if team.external_id
    }

    for raw in teams:
        row = existing.get(raw.external_id)
        if row is None:
            row = Team(external_id=raw.external_id, source=source)
            db.add(row)
            report.teams_created += 1
        else:
            report.teams_updated += 1

        row.name = raw.name
        row.short_name = raw.short_name
        row.league = raw.league
        row.country = raw.country
        row.crest_url = raw.crest_url
        existing[raw.external_id] = row

    db.commit()
    return {ext_id: row.id for ext_id, row in existing.items()}, report


def upsert_matches(
    db: Session, matches: list[RawMatch], team_ids: dict[str, int], source: str
) -> IngestReport:
    """Insert or update fixtures and results."""
    report = IngestReport()
    frame = raw_matches_to_frame(matches)
    if frame.empty:
        return report

    existing = {
        match.external_id: match
        for match in db.execute(select(Match).where(Match.source == source)).scalars().all()
        if match.external_id
    }

    for record in frame.to_dict(orient="records"):
        home_id = team_ids.get(record["home_external_id"])
        away_id = team_ids.get(record["away_external_id"])
        if home_id is None or away_id is None or home_id == away_id:
            # Happens when the teams endpoint and the matches endpoint
            # disagree, for example a cup fixture against a team outside the
            # league. Skipping keeps the foreign keys valid.
            report.matches_skipped += 1
            continue

        row = existing.get(record["external_id"])
        if row is None:
            row = Match(external_id=record["external_id"], source=source)
            db.add(row)
            report.matches_created += 1
        else:
            report.matches_updated += 1

        home_goals = record["home_goals"]
        away_goals = record["away_goals"]

        row.home_team_id = home_id
        row.away_team_id = away_id
        row.match_date = record["match_date"]
        row.league = record["league"]
        row.season = record.get("season")
        row.matchday = record.get("matchday")
        row.status = MatchStatus(record["status"])
        row.home_goals = None if pd.isna(home_goals) else int(home_goals)
        row.away_goals = None if pd.isna(away_goals) else int(away_goals)

        # Only overwrite a stored price when the feed actually carries one, so
        # a source without odds cannot wipe prices a previous run captured.
        for field_name in ("market_line", "market_odds_over", "market_odds_under"):
            value = record.get(field_name)
            if value is not None and not pd.isna(value):
                setattr(row, field_name, float(value))

        existing[record["external_id"]] = row

    db.commit()
    return report


def ingest_competition(
    db: Session,
    provider: FootballDataProvider,
    competition: str,
    season: str | None = None,
) -> IngestReport:
    """Fetch one competition and load it into the database."""
    logger.info("ingesting competition=%s season=%s via %s", competition, season, provider.name)

    teams = provider.fetch_teams(competition, season)
    team_ids, team_report = upsert_teams(db, teams, provider.name)
    logger.info("%s teams resolved", len(team_ids))

    matches = provider.fetch_matches(competition, season)
    match_report = upsert_matches(db, matches, team_ids, provider.name)

    report = IngestReport(
        teams_created=team_report.teams_created,
        teams_updated=team_report.teams_updated,
        matches_created=match_report.matches_created,
        matches_updated=match_report.matches_updated,
        matches_skipped=match_report.matches_skipped,
    )
    logger.info("competition=%s done: %s", competition, report)
    return report
