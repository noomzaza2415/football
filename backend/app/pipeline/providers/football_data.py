"""football-data.org (v4) provider.

The free tier allows 10 requests per minute across a handful of
competitions, which is why the client sleeps between calls. The API key is
read from ``FOOTBALL_DATA_API_KEY`` and sent in the ``X-Auth-Token`` header.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import httpx

from app.config import get_settings
from app.pipeline.providers.base import (
    FootballDataProvider,
    MissingApiKeyError,
    ProviderError,
    RawMatch,
    RawTeam,
)

logger = logging.getLogger(__name__)

STATUS_MAP = {
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
    "IN_PLAY": "scheduled",
    "PAUSED": "scheduled",
    "FINISHED": "finished",
    "POSTPONED": "postponed",
    "SUSPENDED": "postponed",
    "CANCELLED": "cancelled",
    "AWARDED": "finished",
}


def _parse_datetime(value: str) -> datetime:
    # football-data.org returns "2024-08-16T19:00:00Z".
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FootballDataOrgProvider(FootballDataProvider):
    name = "football-data.org"

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.football_data_api_key
        self.base_url = (base_url or settings.football_data_base_url).rstrip("/")
        self.timeout = settings.request_timeout_seconds
        self.sleep_seconds = settings.rate_limit_sleep_seconds

        if not self.api_key:
            raise MissingApiKeyError(
                "FOOTBALL_DATA_API_KEY is not set; add it to your .env file"
            )

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {"X-Auth-Token": self.api_key}
        logger.info("GET %s params=%s", url, params or {})

        try:
            response = httpx.get(url, headers=headers, params=params, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"request to {url} failed: {exc}") from exc

        if response.status_code == 429:
            raise ProviderError(
                "football-data.org rate limit hit; wait a minute or reduce COMPETITIONS"
            )
        if response.status_code == 403:
            raise ProviderError(
                "football-data.org rejected the API key, or the plan does not cover "
                f"this competition ({url})"
            )
        if response.status_code >= 400:
            raise ProviderError(f"{url} returned {response.status_code}: {response.text[:200]}")

        # Stay inside the free-tier rate limit without needing a scheduler.
        time.sleep(self.sleep_seconds)
        return response.json()

    def fetch_teams(self, competition: str, season: str | None = None) -> list[RawTeam]:
        params = {"season": season} if season else None
        payload = self._get(f"competitions/{competition}/teams", params)

        competition_name = payload.get("competition", {}).get("name", competition)
        area = payload.get("area", {}).get("name")

        return [
            RawTeam(
                external_id=str(team["id"]),
                name=team.get("name") or team.get("shortName") or "Unknown",
                short_name=team.get("shortName") or team.get("tla"),
                league=competition_name,
                country=team.get("area", {}).get("name") or area,
                crest_url=team.get("crest"),
            )
            for team in payload.get("teams", [])
        ]

    def fetch_matches(self, competition: str, season: str | None = None) -> list[RawMatch]:
        params = {"season": season} if season else None
        payload = self._get(f"competitions/{competition}/matches", params)

        competition_name = payload.get("competition", {}).get("name", competition)
        matches: list[RawMatch] = []

        for item in payload.get("matches", []):
            home = item.get("homeTeam") or {}
            away = item.get("awayTeam") or {}
            if not home.get("id") or not away.get("id"):
                continue  # knockout placeholder, no teams drawn yet

            full_time = (item.get("score") or {}).get("fullTime") or {}
            status = STATUS_MAP.get(item.get("status", ""), "scheduled")

            matches.append(
                RawMatch(
                    external_id=str(item["id"]),
                    league=competition_name,
                    match_date=_parse_datetime(item["utcDate"]),
                    home_external_id=str(home["id"]),
                    away_external_id=str(away["id"]),
                    home_name=home.get("name") or "Unknown",
                    away_name=away.get("name") or "Unknown",
                    status=status,
                    home_goals=full_time.get("home"),
                    away_goals=full_time.get("away"),
                    season=str((item.get("season") or {}).get("startDate", ""))[:4] or season,
                    matchday=item.get("matchday"),
                )
            )

        return matches
