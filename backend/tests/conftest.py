"""Shared pytest fixtures.

The API tests run against an in-memory SQLite database so they need neither a
PostgreSQL server nor any API key. The environment is set before the app
modules import, because the settings object is cached at import time.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATA_PROVIDER", "football-data")

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Match, MatchStatus, Team  # noqa: E402


@pytest.fixture
def db_session():
    """A fresh in-memory database per test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db_session):
    """A TestClient wired to the same in-memory session."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_db(db_session):
    """Four teams, a block of finished matches and one upcoming fixture."""
    teams = [
        Team(name=f"Team {i}", short_name=f"T{i}", league="Test League")
        for i in range(1, 5)
    ]
    db_session.add_all(teams)
    db_session.commit()
    for team in teams:
        db_session.refresh(team)

    ids = [team.id for team in teams]
    start = datetime.now(timezone.utc) - timedelta(days=120)

    scorelines = [
        (0, 1, 3, 0),
        (2, 3, 2, 1),
        (1, 0, 1, 1),
        (3, 2, 0, 2),
        (0, 2, 2, 0),
        (1, 3, 3, 1),
        (2, 0, 1, 2),
        (3, 1, 0, 1),
    ]

    finished: list[Match] = []
    for block in range(4):
        for index, (home, away, home_goals, away_goals) in enumerate(scorelines):
            finished.append(
                Match(
                    home_team_id=ids[home],
                    away_team_id=ids[away],
                    match_date=start + timedelta(days=block * 7 + index),
                    league="Test League",
                    status=MatchStatus.FINISHED,
                    home_goals=home_goals,
                    away_goals=away_goals,
                )
            )

    upcoming = Match(
        home_team_id=ids[0],
        away_team_id=ids[3],
        match_date=datetime.now(timezone.utc) + timedelta(days=3),
        league="Test League",
        status=MatchStatus.SCHEDULED,
        market_line=2.5,
        market_odds_over=1.90,
        market_odds_under=1.95,
    )

    db_session.add_all(finished + [upcoming])
    db_session.commit()
    db_session.refresh(upcoming)

    return {"teams": teams, "team_ids": ids, "upcoming_id": upcoming.id}
