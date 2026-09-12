"""Seed a demo database so the app runs before any API key is configured.

Results are simulated from per-team attack and defense ratings, not scraped,
so nothing here is real data. That is deliberate: it exercises every screen
without needing an upstream account, and it cannot be mistaken for genuine
historical results.

    python -m scripts.seed_demo --reset
"""

from __future__ import annotations

import argparse
import logging
import random
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import delete

from app.analytics.poisson_model import InsufficientDataError
from app.database import Base, SessionLocal, engine, init_db
from app.models import Match, MatchStatus, Prediction, Team, TeamStats
from app import services

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("seed")

LEAGUE = "Demo Premier Division"

# (name, short name, attack rating, defense rating). Higher attack scores more;
# higher defense concedes more. All invented.
DEMO_TEAMS: list[tuple[str, str, float, float]] = [
    ("Riverside United", "RIV", 1.45, 0.75),
    ("Northgate City", "NOR", 1.38, 0.82),
    ("Kingsbury Athletic", "KIN", 1.25, 0.90),
    ("Ashford Rovers", "ASH", 1.15, 0.95),
    ("Eastvale Town", "EAS", 1.10, 1.00),
    ("Harborough FC", "HAR", 1.05, 1.05),
    ("Westbrook County", "WES", 1.00, 1.05),
    ("Marlowe Wanderers", "MAR", 0.95, 1.10),
    ("Stonebridge FC", "STO", 0.92, 1.12),
    ("Fairhaven Albion", "FAI", 0.88, 1.15),
    ("Greyfield Park", "GRE", 0.85, 1.22),
    ("Oakmoor Rangers", "OAK", 0.78, 1.35),
]

HOME_ADVANTAGE = 1.18
BASE_HOME_GOALS = 1.45
BASE_AWAY_GOALS = 1.15


def reset_tables() -> None:
    """Drop every row so a re-seed does not stack duplicates."""
    with SessionLocal() as db:
        for model in (Prediction, TeamStats, Match, Team):
            db.execute(delete(model))
        db.commit()
    logger.info("cleared existing rows")


def create_teams(db) -> list[Team]:
    teams = [
        Team(
            name=name,
            short_name=short,
            league=LEAGUE,
            country="Demoland",
            external_id=f"demo-{index}",
            source="demo-seed",
        )
        for index, (name, short, _, _) in enumerate(DEMO_TEAMS, start=1)
    ]
    db.add_all(teams)
    db.commit()
    for team in teams:
        db.refresh(team)
    logger.info("created %s teams", len(teams))
    return teams


def simulate_goals(rng: np.random.Generator, attack: float, defense: float, base: float) -> int:
    """One side's goals, drawn from a Poisson with a rating-driven mean."""
    lam = max(base * attack * defense, 0.15)
    return int(rng.poisson(lam))


def round_robin_fixtures(team_count: int) -> list[list[tuple[int, int]]]:
    """A double round robin as a list of rounds of (home index, away index)."""
    indices = list(range(team_count))
    rounds: list[list[tuple[int, int]]] = []

    for leg in range(2):
        rotation = indices[:]
        for _ in range(team_count - 1):
            pairs = [
                (rotation[i], rotation[team_count - 1 - i]) for i in range(team_count // 2)
            ]
            rounds.append([(a, b) if leg == 0 else (b, a) for a, b in pairs])
            rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]

    return rounds


def seed_matches(db, teams: list[Team], *, seed: int = 20240801) -> tuple[int, int]:
    """Play out past rounds and leave the next few rounds scheduled."""
    rng = np.random.default_rng(seed)
    random.seed(seed)

    ratings = {team.id: DEMO_TEAMS[i][2:] for i, team in enumerate(teams)}
    rounds = round_robin_fixtures(len(teams))

    # Everything up to three rounds from the end has been played.
    played_rounds = len(rounds) - 3
    kickoff = datetime.now(timezone.utc) - timedelta(days=7 * played_rounds)

    finished = scheduled = 0
    rows: list[Match] = []

    for round_index, fixtures in enumerate(rounds):
        round_date = kickoff + timedelta(days=7 * round_index)
        is_played = round_index < played_rounds

        for slot, (home_index, away_index) in enumerate(fixtures):
            home, away = teams[home_index], teams[away_index]
            home_attack, home_defense = ratings[home.id]
            away_attack, away_defense = ratings[away.id]

            match_date = round_date + timedelta(hours=12 + slot * 2)
            match = Match(
                home_team_id=home.id,
                away_team_id=away.id,
                match_date=match_date,
                league=LEAGUE,
                season="2024",
                matchday=round_index + 1,
                external_id=f"demo-m-{round_index}-{slot}",
                source="demo-seed",
            )

            if is_played:
                match.status = MatchStatus.FINISHED
                match.home_goals = simulate_goals(
                    rng, home_attack * HOME_ADVANTAGE, away_defense, BASE_HOME_GOALS
                )
                match.away_goals = simulate_goals(
                    rng, away_attack, home_defense, BASE_AWAY_GOALS
                )
                finished += 1
            else:
                match.status = MatchStatus.SCHEDULED
                # A plausible market: 2.5 priced near even with a 5% margin.
                match.market_line = 2.5
                match.market_odds_over = round(random.uniform(1.72, 2.20), 2)
                match.market_odds_under = round(random.uniform(1.70, 2.15), 2)
                scheduled += 1

            rows.append(match)

    db.add_all(rows)
    db.commit()
    logger.info("created %s finished and %s scheduled matches", finished, scheduled)
    return finished, scheduled


def seed_predictions(db, *, backfill: int = 60) -> int:
    """Store point-in-time predictions for past matches, to fill the backtest.

    Each one is fitted only on matches that finished before its own kick-off,
    so the accuracy page is not reporting on a model that already saw the
    answer.
    """
    from sqlalchemy import select

    finished = (
        db.execute(
            select(Match)
            .where(Match.status == MatchStatus.FINISHED)
            .order_by(Match.match_date.desc())
            .limit(backfill)
        )
        .scalars()
        .all()
    )

    stored = 0
    for match in finished:
        try:
            prediction, sample = services.run_model_for_match(db, match, point_in_time=True)
        except InsufficientDataError:
            continue
        services.store_prediction(db, match, prediction, sample)
        stored += 1

    upcoming = services.upcoming_matches(db, days=60, limit=200)
    for match in upcoming:
        try:
            prediction, sample = services.run_model_for_match(db, match)
        except InsufficientDataError:
            continue
        services.store_prediction(db, match, prediction, sample)
        stored += 1

    logger.info("stored %s predictions", stored)
    return stored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed demo data")
    parser.add_argument("--reset", action="store_true", help="delete existing rows first")
    parser.add_argument("--drop-all", action="store_true", help="drop and recreate all tables")
    parser.add_argument("--seed", type=int, default=20240801, help="random seed")
    args = parser.parse_args(argv)

    if args.drop_all:
        Base.metadata.drop_all(bind=engine)
        logger.info("dropped all tables")

    init_db()
    if args.reset and not args.drop_all:
        reset_tables()

    with SessionLocal() as db:
        teams = create_teams(db)
        seed_matches(db, teams, seed=args.seed)
        services.rebuild_team_stats(db)
        seed_predictions(db)

    logger.info("demo data ready; start the API with: uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
