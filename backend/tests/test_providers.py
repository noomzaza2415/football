"""Provider parsing tests against recorded upstream payloads.

These clients have to survive real API responses, which are messier than the
happy path: knockout fixtures with no teams drawn yet, postponed matches,
scheduled matches whose score fields are null, and error envelopes that differ
in shape between success and failure.

Every payload below is shaped like the real thing. Nothing here touches the
network: ``httpx.get`` is replaced for the duration of each test.
"""

from __future__ import annotations

from datetime import timezone

import httpx
import pytest

from app.pipeline.providers.api_football import ApiFootballProvider
from app.pipeline.providers.base import MissingApiKeyError, ProviderError
from app.pipeline.providers.football_data import FootballDataOrgProvider


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text or str(payload)[:200]

    def json(self) -> dict:
        return self._payload


@pytest.fixture(autouse=True)
def no_rate_limit_sleep(monkeypatch):
    """The clients sleep to respect rate limits; tests should not wait."""
    monkeypatch.setattr("app.pipeline.providers.football_data.time.sleep", lambda _: None)
    monkeypatch.setattr("app.pipeline.providers.api_football.time.sleep", lambda _: None)


def patch_get(monkeypatch, module: str, payload, status_code: int = 200):
    """Replace httpx.get in one provider module and record the calls made."""
    calls: list[dict] = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        body = payload(len(calls) - 1) if callable(payload) else payload
        return FakeResponse(body, status_code)

    monkeypatch.setattr(f"app.pipeline.providers.{module}.httpx.get", fake_get)
    return calls


# --------------------------------------------------------------------------- #
# football-data.org
# --------------------------------------------------------------------------- #
FOOTBALL_DATA_TEAMS = {
    "count": 3,
    "filters": {"season": "2024"},
    "competition": {"id": 2021, "name": "Premier League", "code": "PL", "type": "LEAGUE"},
    "season": {"id": 2287, "startDate": "2024-08-16", "endDate": "2025-05-25"},
    "teams": [
        {
            "area": {"id": 2072, "name": "England", "code": "ENG"},
            "id": 57,
            "name": "Arsenal FC",
            "shortName": "Arsenal",
            "tla": "ARS",
            "crest": "https://crests.football-data.org/57.png",
        },
        {
            "area": {"id": 2072, "name": "England"},
            "id": 64,
            "name": "Liverpool FC",
            "shortName": "Liverpool",
            "tla": "LIV",
            "crest": "https://crests.football-data.org/64.png",
        },
        {
            # A team the upstream data is missing a short name for.
            "area": {"id": 2072, "name": "England"},
            "id": 351,
            "name": "Nottingham Forest FC",
            "shortName": None,
            "tla": "NOT",
            "crest": None,
        },
    ],
}

FOOTBALL_DATA_MATCHES = {
    "filters": {"season": "2024"},
    "resultSet": {"count": 5, "played": 2},
    "competition": {"id": 2021, "name": "Premier League", "code": "PL"},
    "matches": [
        {
            "id": 497364,
            "utcDate": "2024-08-16T19:00:00Z",
            "status": "FINISHED",
            "matchday": 1,
            "stage": "REGULAR_SEASON",
            "season": {"id": 2287, "startDate": "2024-08-16", "endDate": "2025-05-25"},
            "homeTeam": {"id": 351, "name": "Nottingham Forest FC", "tla": "NOT"},
            "awayTeam": {"id": 64, "name": "Liverpool FC", "tla": "LIV"},
            "score": {
                "winner": "AWAY_TEAM",
                "duration": "REGULAR",
                "fullTime": {"home": 0, "away": 3},
                "halfTime": {"home": 0, "away": 1},
            },
            "odds": {"msg": "Activate Odds-Package in User-Panel to retrieve odds."},
        },
        {
            "id": 497365,
            "utcDate": "2024-08-17T14:00:00Z",
            "status": "TIMED",
            "matchday": 2,
            "season": {"id": 2287, "startDate": "2024-08-16"},
            "homeTeam": {"id": 57, "name": "Arsenal FC", "tla": "ARS"},
            "awayTeam": {"id": 351, "name": "Nottingham Forest FC", "tla": "NOT"},
            "score": {
                "winner": None,
                "fullTime": {"home": None, "away": None},
                "halfTime": {"home": None, "away": None},
            },
        },
        {
            "id": 497366,
            "utcDate": "2024-08-18T13:00:00Z",
            "status": "POSTPONED",
            "matchday": 2,
            "season": {"id": 2287, "startDate": "2024-08-16"},
            "homeTeam": {"id": 64, "name": "Liverpool FC", "tla": "LIV"},
            "awayTeam": {"id": 57, "name": "Arsenal FC", "tla": "ARS"},
            "score": {"fullTime": {"home": None, "away": None}},
        },
        {
            # A cup round where the draw has not been made: no team ids.
            "id": 497367,
            "utcDate": "2024-09-01T13:00:00Z",
            "status": "SCHEDULED",
            "season": {"id": 2287, "startDate": "2024-08-16"},
            "homeTeam": {"id": None, "name": None},
            "awayTeam": {"id": None, "name": None},
            "score": {"fullTime": {"home": None, "away": None}},
        },
        {
            "id": 497368,
            "utcDate": "2024-08-19T19:00:00Z",
            "status": "AWARDED",
            "matchday": 1,
            "season": {"id": 2287, "startDate": "2024-08-16"},
            "homeTeam": {"id": 57, "name": "Arsenal FC"},
            "awayTeam": {"id": 351, "name": "Nottingham Forest FC"},
            "score": {"fullTime": {"home": 3, "away": 0}},
        },
    ],
}


def football_data_client() -> FootballDataOrgProvider:
    return FootballDataOrgProvider(api_key="test-key")


def test_football_data_requires_a_key():
    with pytest.raises(MissingApiKeyError):
        FootballDataOrgProvider(api_key=None)


def test_football_data_sends_the_key_in_the_auth_header(monkeypatch):
    calls = patch_get(monkeypatch, "football_data", FOOTBALL_DATA_TEAMS)

    football_data_client().fetch_teams("PL", "2024")

    assert calls[0]["headers"]["X-Auth-Token"] == "test-key"
    assert calls[0]["url"].endswith("/competitions/PL/teams")
    assert calls[0]["params"] == {"season": "2024"}


def test_football_data_parses_teams(monkeypatch):
    patch_get(monkeypatch, "football_data", FOOTBALL_DATA_TEAMS)

    teams = football_data_client().fetch_teams("PL", "2024")

    assert len(teams) == 3
    arsenal = teams[0]
    assert arsenal.external_id == "57"
    assert arsenal.name == "Arsenal FC"
    assert arsenal.short_name == "Arsenal"
    assert arsenal.league == "Premier League"
    assert arsenal.country == "England"
    assert arsenal.crest_url.endswith("57.png")


def test_football_data_falls_back_when_a_short_name_is_missing(monkeypatch):
    patch_get(monkeypatch, "football_data", FOOTBALL_DATA_TEAMS)

    forest = football_data_client().fetch_teams("PL", "2024")[2]

    assert forest.short_name == "NOT"
    assert forest.crest_url is None


def test_football_data_parses_matches(monkeypatch):
    patch_get(monkeypatch, "football_data", FOOTBALL_DATA_MATCHES)

    matches = football_data_client().fetch_matches("PL", "2024")

    # The undrawn cup tie is dropped; the other four survive.
    assert len(matches) == 4

    finished = matches[0]
    assert finished.external_id == "497364"
    assert finished.status == "finished"
    assert finished.home_goals == 0
    assert finished.away_goals == 3
    assert finished.home_external_id == "351"
    assert finished.away_external_id == "64"
    assert finished.league == "Premier League"
    assert finished.season == "2024"
    assert finished.matchday == 1
    assert finished.is_finished


def test_football_data_maps_status_values(monkeypatch):
    patch_get(monkeypatch, "football_data", FOOTBALL_DATA_MATCHES)

    by_id = {m.external_id: m for m in football_data_client().fetch_matches("PL", "2024")}

    assert by_id["497365"].status == "scheduled"  # TIMED
    assert by_id["497366"].status == "postponed"
    assert by_id["497368"].status == "finished"  # AWARDED
    assert by_id["497365"].home_goals is None
    assert not by_id["497365"].is_finished


def test_football_data_parses_kickoff_as_utc(monkeypatch):
    patch_get(monkeypatch, "football_data", FOOTBALL_DATA_MATCHES)

    kickoff = football_data_client().fetch_matches("PL", "2024")[0].match_date

    assert kickoff.tzinfo is not None
    assert kickoff.astimezone(timezone.utc).hour == 19
    assert kickoff.year == 2024


def test_football_data_explains_a_rejected_key(monkeypatch):
    patch_get(monkeypatch, "football_data", {}, status_code=403)

    with pytest.raises(ProviderError, match="rejected the API key"):
        football_data_client().fetch_teams("PL")


def test_football_data_explains_a_rate_limit(monkeypatch):
    patch_get(monkeypatch, "football_data", {}, status_code=429)

    with pytest.raises(ProviderError, match="rate limit"):
        football_data_client().fetch_teams("PL")


def test_football_data_wraps_a_transport_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr("app.pipeline.providers.football_data.httpx.get", boom)

    with pytest.raises(ProviderError, match="failed"):
        football_data_client().fetch_teams("PL")


# --------------------------------------------------------------------------- #
# API-Football
# --------------------------------------------------------------------------- #
API_FOOTBALL_TEAMS = {
    "get": "teams",
    "parameters": {"league": "39", "season": "2024"},
    "errors": [],
    "results": 2,
    "paging": {"current": 1, "total": 1},
    "response": [
        {
            "team": {
                "id": 33,
                "name": "Manchester United",
                "code": "MUN",
                "country": "England",
                "founded": 1878,
                "national": False,
                "logo": "https://media.api-sports.io/football/teams/33.png",
            },
            "venue": {"id": 556, "name": "Old Trafford"},
        },
        {
            "team": {
                "id": 40,
                "name": "Liverpool",
                "code": "LIV",
                "country": "England",
                "logo": "https://media.api-sports.io/football/teams/40.png",
            },
            "venue": {"id": 550, "name": "Anfield"},
        },
    ],
}

API_FOOTBALL_FIXTURES = {
    "get": "fixtures",
    "parameters": {"league": "39", "season": "2024"},
    "errors": [],
    "results": 3,
    "paging": {"current": 1, "total": 1},
    "response": [
        {
            "fixture": {
                "id": 1208021,
                "timezone": "UTC",
                "date": "2024-08-16T19:00:00+00:00",
                "timestamp": 1723834800,
                "status": {"long": "Match Finished", "short": "FT", "elapsed": 90},
            },
            "league": {
                "id": 39,
                "name": "Premier League",
                "country": "England",
                "season": 2024,
                "round": "Regular Season - 1",
            },
            "teams": {
                "home": {"id": 33, "name": "Manchester United", "winner": False},
                "away": {"id": 40, "name": "Liverpool", "winner": True},
            },
            "goals": {"home": 0, "away": 3},
            "score": {"halftime": {"home": 0, "away": 1}, "fulltime": {"home": 0, "away": 3}},
        },
        {
            "fixture": {
                "id": 1208022,
                "date": "2024-08-24T14:00:00+00:00",
                "status": {"long": "Not Started", "short": "NS", "elapsed": None},
            },
            "league": {"id": 39, "name": "Premier League", "season": 2024},
            "teams": {
                "home": {"id": 40, "name": "Liverpool"},
                "away": {"id": 33, "name": "Manchester United"},
            },
            "goals": {"home": None, "away": None},
            "score": {"fulltime": {"home": None, "away": None}},
        },
        {
            "fixture": {
                "id": 1208023,
                "date": "2024-09-01T13:00:00+00:00",
                "status": {"long": "Match Postponed", "short": "PST", "elapsed": None},
            },
            "league": {"id": 39, "name": "Premier League", "season": 2024},
            "teams": {
                "home": {"id": 33, "name": "Manchester United"},
                "away": {"id": 40, "name": "Liverpool"},
            },
            "goals": {"home": None, "away": None},
            "score": {"fulltime": {"home": None, "away": None}},
        },
    ],
}


def api_football_client() -> ApiFootballProvider:
    return ApiFootballProvider(api_key="test-key")


def test_api_football_requires_a_key():
    with pytest.raises(MissingApiKeyError):
        ApiFootballProvider(api_key=None)


def test_api_football_sends_the_key_in_its_own_header(monkeypatch):
    calls = patch_get(monkeypatch, "api_football", API_FOOTBALL_TEAMS)

    api_football_client().fetch_teams("39", "2024")

    assert calls[0]["headers"]["x-apisports-key"] == "test-key"
    assert calls[0]["params"]["league"] == "39"
    assert calls[0]["params"]["season"] == "2024"


def test_api_football_parses_teams(monkeypatch):
    patch_get(monkeypatch, "api_football", API_FOOTBALL_TEAMS)

    teams = api_football_client().fetch_teams("39", "2024")

    assert [team.external_id for team in teams] == ["33", "40"]
    assert teams[0].name == "Manchester United"
    assert teams[0].short_name == "MUN"
    assert teams[0].country == "England"
    assert teams[0].crest_url.endswith("33.png")


def test_api_football_parses_fixtures(monkeypatch):
    patch_get(monkeypatch, "api_football", API_FOOTBALL_FIXTURES)

    matches = api_football_client().fetch_matches("39", "2024")

    assert len(matches) == 3
    finished = matches[0]
    assert finished.external_id == "1208021"
    assert finished.status == "finished"
    assert finished.home_goals == 0
    assert finished.away_goals == 3
    assert finished.league == "Premier League"
    assert finished.season == "2024"
    assert finished.match_date.year == 2024


def test_api_football_maps_status_codes(monkeypatch):
    patch_get(monkeypatch, "api_football", API_FOOTBALL_FIXTURES)

    statuses = [m.status for m in api_football_client().fetch_matches("39", "2024")]

    assert statuses == ["finished", "scheduled", "postponed"]


def test_api_football_surfaces_an_error_envelope(monkeypatch):
    patch_get(
        monkeypatch,
        "api_football",
        {"errors": {"token": "Error/Missing application key."}, "response": []},
    )

    with pytest.raises(ProviderError, match="token"):
        api_football_client().fetch_teams("39", "2024")


def test_api_football_surfaces_an_error_list(monkeypatch):
    # The upstream sometimes returns errors as a list rather than a dict.
    patch_get(
        monkeypatch,
        "api_football",
        {"errors": ["Invalid league id"], "response": []},
    )

    with pytest.raises(ProviderError, match="Invalid league id"):
        api_football_client().fetch_teams("39", "2024")


def test_api_football_follows_paging(monkeypatch):
    """A league split across pages must come back whole, not truncated."""
    page_one = {
        "errors": [],
        "paging": {"current": 1, "total": 2},
        "response": API_FOOTBALL_FIXTURES["response"][:2],
    }
    page_two = {
        "errors": [],
        "paging": {"current": 2, "total": 2},
        "response": API_FOOTBALL_FIXTURES["response"][2:],
    }
    calls = patch_get(monkeypatch, "api_football", lambda index: [page_one, page_two][index])

    matches = api_football_client().fetch_matches("39", "2024")

    assert len(calls) == 2
    assert calls[1]["params"]["page"] == 2
    assert len(matches) == 3


def test_api_football_explains_a_rate_limit(monkeypatch):
    patch_get(monkeypatch, "api_football", {}, status_code=429)

    with pytest.raises(ProviderError, match="rate limit"):
        api_football_client().fetch_teams("39", "2024")
