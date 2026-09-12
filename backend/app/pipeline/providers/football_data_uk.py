"""football-data.co.uk CSV provider.

This source needs no API key and no account. It publishes one CSV per division
per season of finished matches, plus a rolling ``fixtures.csv`` of matches due
in the next week.

It matters here for one reason the API providers do not cover on their free
tiers: it carries **real bookmaker prices for Over/Under 2.5**, including
closing prices. Without those, the market comparison on the match page and the
market baseline in the backtest have nothing real to compare against.

Division codes are letters, not numbers: E0 is the Premier League, E1 the
Championship, D1 the Bundesliga, SP1 La Liga, I1 Serie A, F1 Ligue 1.

Teams have no upstream id here, so the team name is the identity. Within one
country the names are consistent across seasons ("Man United" every time),
which is enough to key an upsert on.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from io import StringIO

import httpx
import pandas as pd

from app.config import get_settings
from app.pipeline.providers.base import (
    FootballDataProvider,
    ProviderError,
    RawMatch,
    RawTeam,
)

logger = logging.getLogger(__name__)

#: Division code to a readable league name, so the UI shows something sensible.
DIVISIONS: dict[str, tuple[str, str]] = {
    "E0": ("Premier League", "England"),
    "E1": ("Championship", "England"),
    "E2": ("League One", "England"),
    "E3": ("League Two", "England"),
    "SC0": ("Scottish Premiership", "Scotland"),
    "D1": ("Bundesliga", "Germany"),
    "D2": ("2. Bundesliga", "Germany"),
    "SP1": ("La Liga", "Spain"),
    "SP2": ("La Liga 2", "Spain"),
    "I1": ("Serie A", "Italy"),
    "I2": ("Serie B", "Italy"),
    "F1": ("Ligue 1", "France"),
    "F2": ("Ligue 2", "France"),
    "N1": ("Eredivisie", "Netherlands"),
    "B1": ("Jupiler League", "Belgium"),
    "P1": ("Liga Portugal", "Portugal"),
    "T1": ("Super Lig", "Turkey"),
    "G1": ("Super League", "Greece"),
}

#: Over/Under 2.5 price columns, best first. The ``C`` forms are closing
#: prices, which are the ones worth judging a model against; the others are
#: opening prices and are only a fallback.
OVER_COLUMNS = ["AvgC>2.5", "PC>2.5", "B365C>2.5", "Avg>2.5", "P>2.5", "B365>2.5"]
UNDER_COLUMNS = ["AvgC<2.5", "PC<2.5", "B365C<2.5", "Avg<2.5", "P<2.5", "B365<2.5"]

REQUIRED_COLUMNS = {"Date", "HomeTeam", "AwayTeam"}


def season_of(kickoff: datetime) -> str:
    """Which season a kick-off belongs to, as its start year.

    A season starts in July, so a match in May 2025 belongs to season 2024.
    """
    return str(kickoff.year if kickoff.month >= 7 else kickoff.year - 1)


def season_code(season: str | int) -> str:
    """Season start year to the directory name: 2024 becomes '2425'."""
    start = int(str(season)[:4])
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def _parse_kickoff(date_text: str, time_text: str | None) -> datetime | None:
    """Combine the Date and Time columns into an aware UTC datetime.

    Dates are ``dd/mm/yyyy`` in recent files and ``dd/mm/yy`` in older ones.
    Time is missing entirely before about 2019.
    """
    date_text = (date_text or "").strip()
    if not date_text:
        return None

    parsed: datetime | None = None
    for pattern in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            parsed = datetime.strptime(date_text, pattern)
            break
        except ValueError:
            continue
    if parsed is None:
        return None

    time_text = (time_text or "").strip()
    if time_text:
        try:
            clock = datetime.strptime(time_text, "%H:%M")
            parsed = parsed.replace(hour=clock.hour, minute=clock.minute)
        except ValueError:
            pass

    # The files are published in UK local time; treating them as UTC shifts a
    # kick-off by at most an hour, which changes no ordering that matters here.
    return parsed.replace(tzinfo=timezone.utc)


def _first_price(row: dict, columns: list[str]) -> float | None:
    """The best available price from a preference-ordered list of columns."""
    for column in columns:
        value = row.get(column)
        if value is None or pd.isna(value):
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price >= 1.01:
            return price
    return None


class FootballDataUkProvider(FootballDataProvider):
    name = "football-data.co.uk"

    def __init__(self, base_url: str | None = None, include_fixtures: bool = True) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.football_data_uk_base_url).rstrip("/")
        self.timeout = settings.request_timeout_seconds
        self.include_fixtures = include_fixtures
        # No API key: this source is public. Nothing to validate here.

    # --- transport --------------------------------------------------------
    def _get_csv(self, path: str) -> pd.DataFrame:
        url = f"{self.base_url}/{path.lstrip('/')}"
        logger.info("GET %s", url)

        try:
            response = httpx.get(url, timeout=self.timeout, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise ProviderError(f"request to {url} failed: {exc}") from exc

        if response.status_code == 404:
            raise ProviderError(
                f"{url} does not exist; check the division code and the season"
            )
        if response.status_code >= 400:
            raise ProviderError(f"{url} returned {response.status_code}")

        # The files carry a BOM and a few trailing blank columns.
        text = response.content.decode("utf-8-sig", errors="replace")
        try:
            frame = pd.read_csv(StringIO(text), on_bad_lines="skip")
        except Exception as exc:  # pandas raises several unrelated types here
            raise ProviderError(f"could not parse {url} as CSV: {exc}") from exc

        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        missing = REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise ProviderError(f"{url} is missing expected columns: {sorted(missing)}")
        return frame

    def _results_frame(self, competition: str, season: str) -> pd.DataFrame:
        return self._get_csv(f"mmz4281/{season_code(season)}/{competition.upper()}.csv")

    def _fixtures_frame(self, competition: str) -> pd.DataFrame:
        """Upcoming matches, filtered to one division. Never fatal."""
        try:
            frame = self._get_csv("fixtures.csv")
        except ProviderError as exc:
            logger.warning("could not load upcoming fixtures: %s", exc)
            return pd.DataFrame()

        if "Div" not in frame.columns:
            return pd.DataFrame()
        return frame[frame["Div"].astype(str).str.upper() == competition.upper()]

    # --- interface --------------------------------------------------------
    def fetch_teams(self, competition: str, season: str | None = None) -> list[RawTeam]:
        """Teams are derived from the results file; there is no team endpoint."""
        season = season or str(datetime.now().year)
        frame = self._results_frame(competition, season)

        league, country = DIVISIONS.get(
            competition.upper(), (competition.upper(), None)
        )

        names = pd.concat([frame["HomeTeam"], frame["AwayTeam"]]).dropna().unique()
        return [
            RawTeam(
                external_id=f"{competition.upper()}:{name}",
                name=str(name),
                short_name=None,
                league=league,
                country=country,
                crest_url=None,
            )
            for name in sorted(str(n) for n in names)
        ]

    def fetch_matches(self, competition: str, season: str | None = None) -> list[RawMatch]:
        season = season or str(datetime.now().year)
        competition = competition.upper()
        league, _ = DIVISIONS.get(competition, (competition, None))

        matches = self._rows_to_matches(
            self._results_frame(competition, season), competition, league, season
        )

        if self.include_fixtures:
            # fixtures.csv is a single rolling file of matches due this week,
            # so its rows belong to whatever season they fall in, not to the
            # season being ingested. Stamping them with the requested season
            # would create one copy of every upcoming fixture per season
            # ingested.
            upcoming = self._rows_to_matches(
                self._fixtures_frame(competition), competition, league, season=None
            )
            known = {match.external_id for match in matches}
            matches.extend(m for m in upcoming if m.external_id not in known)

        return matches

    def _rows_to_matches(
        self, frame: pd.DataFrame, competition: str, league: str, season: str | None
    ) -> list[RawMatch]:
        if frame.empty:
            return []

        matches: list[RawMatch] = []
        for row in frame.to_dict(orient="records"):
            home = str(row.get("HomeTeam") or "").strip()
            away = str(row.get("AwayTeam") or "").strip()
            if not home or not away or home == away:
                continue

            kickoff = _parse_kickoff(str(row.get("Date") or ""), row.get("Time"))
            if kickoff is None:
                continue

            home_goals = row.get("FTHG")
            away_goals = row.get("FTAG")
            played = not (
                home_goals is None
                or away_goals is None
                or pd.isna(home_goals)
                or pd.isna(away_goals)
            )

            # season=None means derive it from the kick-off, which is what
            # keeps a rolling fixtures file from duplicating across ingests.
            row_season = season_of(kickoff) if season is None else str(season)[:4]

            over = _first_price(row, OVER_COLUMNS)
            under = _first_price(row, UNDER_COLUMNS)

            matches.append(
                RawMatch(
                    # No upstream id, so the fixture itself is the key. Teams
                    # meet at most once per venue per season, so this is unique
                    # and stable across re-runs.
                    external_id=f"{competition}:{row_season}:{home}:{away}",
                    league=league,
                    match_date=kickoff,
                    home_external_id=f"{competition}:{home}",
                    away_external_id=f"{competition}:{away}",
                    home_name=home,
                    away_name=away,
                    status="finished" if played else "scheduled",
                    home_goals=int(home_goals) if played else None,
                    away_goals=int(away_goals) if played else None,
                    season=row_season,
                    matchday=None,
                    market_line=2.5 if over and under else None,
                    market_odds_over=over,
                    market_odds_under=under,
                )
            )

        return matches
