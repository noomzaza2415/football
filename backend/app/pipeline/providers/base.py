"""Provider interface and the normalised records every provider returns.

Adding a new data source means implementing :class:`FootballDataProvider`
and returning these two dataclasses. Nothing downstream of this module knows
which upstream API the rows came from.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime


class ProviderError(RuntimeError):
    """Raised when the upstream API refuses or returns something unusable."""


class MissingApiKeyError(ProviderError):
    """Raised when the configured provider has no API key in the environment."""


@dataclass(frozen=True)
class RawTeam:
    """A team as the provider describes it, before it reaches the database."""

    external_id: str
    name: str
    league: str
    short_name: str | None = None
    country: str | None = None
    crest_url: str | None = None


@dataclass(frozen=True)
class RawMatch:
    """One fixture or result, normalised across providers."""

    external_id: str
    league: str
    match_date: datetime
    home_external_id: str
    away_external_id: str
    home_name: str
    away_name: str
    status: str  # scheduled | finished | postponed | cancelled
    home_goals: int | None = None
    away_goals: int | None = None
    season: str | None = None
    matchday: int | None = None

    # Closing Over/Under prices, when the source publishes them. Only
    # football-data.co.uk does on a free tier, so these are usually None.
    market_line: float | None = None
    market_odds_over: float | None = None
    market_odds_under: float | None = None

    @property
    def is_finished(self) -> bool:
        return self.status == "finished" and self.home_goals is not None


class FootballDataProvider(abc.ABC):
    """Everything the ETL needs from an upstream source."""

    #: Written into ``teams.source`` / ``matches.source`` so rows can be traced.
    name: str = "unknown"

    @abc.abstractmethod
    def fetch_teams(self, competition: str, season: str | None = None) -> list[RawTeam]:
        """Every team in one competition."""

    @abc.abstractmethod
    def fetch_matches(
        self, competition: str, season: str | None = None
    ) -> list[RawMatch]:
        """Every fixture and result in one competition and season."""
