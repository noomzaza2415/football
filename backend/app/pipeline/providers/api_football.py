"""API-Football (api-sports.io v3) provider.

Competitions are numeric league ids here, not letter codes: 39 is the Premier
League, 140 La Liga, 135 Serie A, 78 Bundesliga, 61 Ligue 1. The key goes in
``API_FOOTBALL_API_KEY`` and is sent as ``x-apisports-key``.
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

# API-Football reports a short status code per fixture.
FINISHED_CODES = {"FT", "AET", "PEN", "WO"}
CANCELLED_CODES = {"CANC", "ABD", "AWD"}
POSTPONED_CODES = {"PST", "SUSP", "INT"}


def _map_status(short_code: str) -> str:
    if short_code in FINISHED_CODES:
        return "finished"
    if short_code in CANCELLED_CODES:
        return "cancelled"
    if short_code in POSTPONED_CODES:
        return "postponed"
    return "scheduled"


class ApiFootballProvider(FootballDataProvider):
    name = "api-football"

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.api_football_api_key
        self.base_url = (base_url or settings.api_football_base_url).rstrip("/")
        self.timeout = settings.request_timeout_seconds
        self.sleep_seconds = max(settings.rate_limit_sleep_seconds / 3, 0.5)

        if not self.api_key:
            raise MissingApiKeyError(
                "API_FOOTBALL_API_KEY is not set; add it to your .env file"
            )

    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {"x-apisports-key": self.api_key}
        logger.info("GET %s params=%s", url, params)

        try:
            response = httpx.get(url, headers=headers, params=params, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"request to {url} failed: {exc}") from exc

        if response.status_code == 429:
            raise ProviderError("API-Football rate limit hit; slow the ingest down")
        if response.status_code >= 400:
            raise ProviderError(f"{url} returned {response.status_code}: {response.text[:200]}")

        payload = response.json()
        # A successful call returns an empty list here. A failure returns either
        # a dict keyed by field or, occasionally, a non-empty list of strings.
        errors = payload.get("errors")
        if errors:
            raise ProviderError(f"API-Football error: {errors}")

        time.sleep(self.sleep_seconds)
        return payload

    def _get_all_pages(self, path: str, params: dict) -> list[dict]:
        """Every page of a paged endpoint, concatenated.

        Fixtures for a whole season usually fit on one page, but a wide date
        range or a busy league does not. Reading only the first page would
        silently drop matches, which is worse than failing outright.
        """
        first = self._get(path, {**params, "page": 1})
        items = list(first.get("response", []))

        paging = first.get("paging") or {}
        total_pages = int(paging.get("total") or 1)

        for page in range(2, total_pages + 1):
            payload = self._get(path, {**params, "page": page})
            items.extend(payload.get("response", []))

        return items

    def fetch_teams(self, competition: str, season: str | None = None) -> list[RawTeam]:
        season = season or str(datetime.now().year)
        items = self._get_all_pages("teams", {"league": competition, "season": season})

        teams: list[RawTeam] = []
        for item in items:
            team = item.get("team") or {}
            if not team.get("id"):
                continue
            teams.append(
                RawTeam(
                    external_id=str(team["id"]),
                    name=team.get("name") or "Unknown",
                    short_name=team.get("code"),
                    league=str(competition),
                    country=team.get("country"),
                    crest_url=team.get("logo"),
                )
            )
        return teams

    def fetch_matches(self, competition: str, season: str | None = None) -> list[RawMatch]:
        season = season or str(datetime.now().year)
        items = self._get_all_pages("fixtures", {"league": competition, "season": season})

        matches: list[RawMatch] = []
        for item in items:
            fixture = item.get("fixture") or {}
            teams = item.get("teams") or {}
            goals = item.get("goals") or {}
            league = item.get("league") or {}

            home = teams.get("home") or {}
            away = teams.get("away") or {}
            if not fixture.get("id") or not home.get("id") or not away.get("id"):
                continue

            status = _map_status((fixture.get("status") or {}).get("short", ""))
            matches.append(
                RawMatch(
                    external_id=str(fixture["id"]),
                    league=league.get("name") or str(competition),
                    match_date=datetime.fromisoformat(fixture["date"]),
                    home_external_id=str(home["id"]),
                    away_external_id=str(away["id"]),
                    home_name=home.get("name") or "Unknown",
                    away_name=away.get("name") or "Unknown",
                    status=status,
                    home_goals=goals.get("home"),
                    away_goals=goals.get("away"),
                    season=str(league.get("season") or season),
                    matchday=None,
                )
            )
        return matches
