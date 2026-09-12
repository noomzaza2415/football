"""SQLAlchemy ORM models: teams, matches, team_stats, predictions."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MatchStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class Team(Base):
    __tablename__ = "teams"
    # ``league`` already carries index=True below, which generates
    # ix_teams_league, so it must not be declared a second time here.
    __table_args__ = (UniqueConstraint("external_id", "source", name="uq_teams_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(60))
    league: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    country: Mapped[str | None] = mapped_column(String(60))
    crest_url: Mapped[str | None] = mapped_column(String(400))

    # Identity in the upstream provider, so ingestion is idempotent.
    external_id: Mapped[str | None] = mapped_column(String(60), index=True)
    source: Mapped[str | None] = mapped_column(String(40))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    home_matches: Mapped[list["Match"]] = relationship(
        back_populates="home_team", foreign_keys="Match.home_team_id"
    )
    away_matches: Mapped[list["Match"]] = relationship(
        back_populates="away_team", foreign_keys="Match.away_team_id"
    )
    stats: Mapped["TeamStats | None"] = relationship(
        back_populates="team", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Team {self.id} {self.name!r}>"


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_matches_external"),
        CheckConstraint("home_team_id <> away_team_id", name="ck_matches_distinct_teams"),
        Index("ix_matches_league_date", "league", "match_date"),
        Index("ix_matches_status_date", "status", "match_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    home_team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    away_team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    league: Mapped[str] = mapped_column(String(60), nullable=False)
    season: Mapped[str | None] = mapped_column(String(20))
    matchday: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, name="match_status", native_enum=False),
        nullable=False,
        default=MatchStatus.SCHEDULED,
    )
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)

    # Closing market prices, when the provider supplies them.
    market_line: Mapped[float | None] = mapped_column(Float)
    market_odds_over: Mapped[float | None] = mapped_column(Float)
    market_odds_under: Mapped[float | None] = mapped_column(Float)

    external_id: Mapped[str | None] = mapped_column(String(60), index=True)
    source: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    home_team: Mapped[Team] = relationship(
        back_populates="home_matches", foreign_keys=[home_team_id]
    )
    away_team: Mapped[Team] = relationship(
        back_populates="away_matches", foreign_keys=[away_team_id]
    )
    predictions: Mapped[list["Prediction"]] = relationship(
        back_populates="match", cascade="all, delete-orphan", order_by="Prediction.created_at"
    )

    @property
    def is_finished(self) -> bool:
        return (
            self.status == MatchStatus.FINISHED
            and self.home_goals is not None
            and self.away_goals is not None
        )

    @property
    def total_goals(self) -> int | None:
        if self.home_goals is None or self.away_goals is None:
            return None
        return self.home_goals + self.away_goals

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Match {self.id} {self.home_team_id}v{self.away_team_id} {self.status.value}>"


class TeamStats(Base):
    """Materialised aggregates, rebuilt from ``matches`` by the ETL step."""

    __tablename__ = "team_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    matches_played: Mapped[int] = mapped_column(Integer, default=0)
    matches_played_home: Mapped[int] = mapped_column(Integer, default=0)
    matches_played_away: Mapped[int] = mapped_column(Integer, default=0)

    avg_goals_scored_home: Mapped[float] = mapped_column(Float, default=0.0)
    avg_goals_scored_away: Mapped[float] = mapped_column(Float, default=0.0)
    avg_goals_conceded_home: Mapped[float] = mapped_column(Float, default=0.0)
    avg_goals_conceded_away: Mapped[float] = mapped_column(Float, default=0.0)
    avg_total_goals: Mapped[float] = mapped_column(Float, default=0.0)

    over_2_5_rate: Mapped[float] = mapped_column(Float, default=0.0)
    btts_rate: Mapped[float] = mapped_column(Float, default=0.0)

    form_last_5: Mapped[str] = mapped_column(String(10), default="")
    form_points_last_5: Mapped[int] = mapped_column(Integer, default=0)

    attack_strength_home: Mapped[float] = mapped_column(Float, default=1.0)
    attack_strength_away: Mapped[float] = mapped_column(Float, default=1.0)
    defense_strength_home: Mapped[float] = mapped_column(Float, default=1.0)
    defense_strength_away: Mapped[float] = mapped_column(Float, default=1.0)

    sample_matches: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    team: Mapped[Team] = relationship(back_populates="stats")


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (Index("ix_predictions_match_created", "match_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )

    expected_home_goals: Mapped[float] = mapped_column(Float, nullable=False)
    expected_away_goals: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_total_goals: Mapped[float] = mapped_column(Float, nullable=False)

    prob_over_1_5: Mapped[float] = mapped_column(Float, default=0.0)
    prob_under_1_5: Mapped[float] = mapped_column(Float, default=0.0)
    prob_over_2_5: Mapped[float] = mapped_column(Float, nullable=False)
    prob_under_2_5: Mapped[float] = mapped_column(Float, nullable=False)
    prob_over_3_5: Mapped[float] = mapped_column(Float, default=0.0)
    prob_under_3_5: Mapped[float] = mapped_column(Float, default=0.0)

    prob_home_win: Mapped[float] = mapped_column(Float, default=0.0)
    prob_draw: Mapped[float] = mapped_column(Float, default=0.0)
    prob_away_win: Mapped[float] = mapped_column(Float, default=0.0)

    most_likely_home_goals: Mapped[int | None] = mapped_column(Integer)
    most_likely_away_goals: Mapped[int | None] = mapped_column(Integer)

    # P(total == n) as {"0": 0.07, "1": 0.18, ...}; JSON keeps the schema
    # portable across PostgreSQL and the SQLite used in tests.
    total_goals_distribution: Mapped[dict | None] = mapped_column(JSON)

    sample_matches: Mapped[int] = mapped_column(Integer, default=0)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    match: Mapped[Match] = relationship(back_populates="predictions")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Prediction match={self.match_id} xG={self.predicted_total_goals:.2f}>"
