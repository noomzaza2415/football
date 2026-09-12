"""Ingest entry point, designed to be run from cron or Task Scheduler.

    python -m app.pipeline.run_ingest --seasons 2023 2024
    python -m app.pipeline.run_ingest --competitions PL BL1 --refresh-predictions

Exits non-zero when nothing could be ingested, so a scheduler can alert on it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from app.analytics.poisson_model import InsufficientDataError
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.pipeline.etl import ingest_competition
from app.pipeline.providers.api_football import ApiFootballProvider
from app.pipeline.providers.base import FootballDataProvider, ProviderError
from app.pipeline.providers.football_data import FootballDataOrgProvider
from app.pipeline.providers.football_data_uk import FootballDataUkProvider
from app import services

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s"
)
logger = logging.getLogger("ingest")


def build_provider(name: str) -> FootballDataProvider:
    if name == "football-data":
        return FootballDataOrgProvider()
    if name == "api-football":
        return ApiFootballProvider()
    if name == "football-data-uk":
        return FootballDataUkProvider()
    raise ProviderError(f"unknown provider {name!r}")


def default_seasons(count: int) -> list[str]:
    """Season start years, most recent first.

    A football season is labelled by the year it starts, and the new one
    begins in July, so before July the current season still started last year.
    """
    now = datetime.now()
    current_start = now.year if now.month >= 7 else now.year - 1
    return [str(current_start - offset) for offset in range(count)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Ingest football results and fixtures")
    parser.add_argument(
        "--provider",
        default=settings.data_provider,
        choices=["football-data", "api-football", "football-data-uk"],
        help="which upstream API to read (default from DATA_PROVIDER)",
    )
    parser.add_argument(
        "--competitions",
        nargs="+",
        default=settings.competition_list,
        help="competition codes or league ids (default from COMPETITIONS)",
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=None,
        help="season start years, e.g. 2023 2024 (default: the last SEASONS_BACK)",
    )
    parser.add_argument(
        "--skip-stats",
        action="store_true",
        help="do not rebuild team_stats after loading",
    )
    parser.add_argument(
        "--refresh-predictions",
        action="store_true",
        help="also store a fresh prediction for every upcoming match",
    )
    parser.add_argument(
        "--prediction-days",
        type=int,
        default=14,
        help="how far ahead to refresh predictions (default 14)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()

    seasons = args.seasons or default_seasons(settings.seasons_back)
    logger.info(
        "provider=%s competitions=%s seasons=%s",
        args.provider,
        args.competitions,
        seasons,
    )

    try:
        provider = build_provider(args.provider)
    except ProviderError as exc:
        logger.error("cannot start: %s", exc)
        return 2

    init_db()
    succeeded = 0

    with SessionLocal() as db:
        for competition in args.competitions:
            for season in seasons:
                try:
                    report = ingest_competition(db, provider, competition, season)
                    logger.info("%s %s: %s", competition, season, report)
                    succeeded += 1
                except ProviderError as exc:
                    # One competition failing must not abandon the others.
                    logger.error("%s %s failed: %s", competition, season, exc)

        if succeeded == 0:
            logger.error("no competition could be ingested")
            return 1

        if not args.skip_stats:
            updated = services.rebuild_team_stats(db)
            logger.info("team_stats rebuilt for %s teams", updated)

        if args.refresh_predictions:
            matches = services.upcoming_matches(db, days=args.prediction_days, limit=200)
            stored = 0
            for match in matches:
                try:
                    prediction, sample = services.run_model_for_match(db, match)
                except InsufficientDataError as exc:
                    logger.warning("skipping match %s: %s", match.id, exc)
                    continue
                services.store_prediction(db, match, prediction, sample)
                stored += 1
            logger.info("stored %s predictions", stored)

    logger.info("ingest finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
