"""Tests for the football-data.co.uk CSV provider.

This source is the only free one carrying real Over/Under prices, so the
parsing of those columns is what matters most here, along with the identity
rules: no API key, no upstream ids, so team names and fixture keys have to be
stable across re-runs or the ingest duplicates everything.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.pipeline.providers.base import ProviderError
from app.pipeline.providers.football_data_uk import (
    FootballDataUkProvider,
    _first_price,
    _parse_kickoff,
    season_code,
    season_of,
)

RESULTS_CSV = """Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365>2.5,B365<2.5,Avg>2.5,Avg<2.5,AvgC>2.5,AvgC<2.5
E0,16/08/2024,20:00,Man United,Fulham,1,0,H,1.53,2.50,1.53,2.52,1.60,2.38
E0,17/08/2024,12:30,Ipswich,Liverpool,0,2,A,1.80,2.00,1.78,2.05,1.75,2.10
E0,17/08/2024,15:00,Arsenal,Wolves,2,0,H,1.44,2.75,1.45,2.72,,
"""

# The rolling fixtures file: no goal columns at all, several divisions mixed.
FIXTURES_CSV = """Div,Date,Time,HomeTeam,AwayTeam,B365>2.5,B365<2.5,Avg>2.5,Avg<2.5
E0,13/09/2026,15:00,Chelsea,Everton,1.70,2.10,1.72,2.08
E0,14/09/2026,17:30,Arsenal,Man United,1.65,2.20,1.66,2.18
D1,13/09/2026,14:30,Bayern Munich,Dortmund,1.40,2.90,1.42,2.85
"""


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.text = text[:200]


@pytest.fixture
def provider(monkeypatch):
    """A client whose downloads are served from the fixtures above."""
    requested: list[str] = []

    def fake_get(url, timeout=None, follow_redirects=None):
        requested.append(url)
        if url.endswith("fixtures.csv"):
            return FakeResponse(FIXTURES_CSV)
        if url.endswith(".csv"):
            return FakeResponse(RESULTS_CSV)
        return FakeResponse("", status_code=404)

    monkeypatch.setattr("app.pipeline.providers.football_data_uk.httpx.get", fake_get)
    client = FootballDataUkProvider()
    client.requested = requested  # type: ignore[attr-defined]
    return client


# --------------------------------------------------------------------------- #
# Season arithmetic
# --------------------------------------------------------------------------- #
def test_season_code_builds_the_directory_name():
    assert season_code(2024) == "2425"
    assert season_code("2019") == "1920"
    # The turn of the century has to wrap, not go negative.
    assert season_code(1999) == "9900"
    assert season_code(2009) == "0910"


def test_season_of_puts_the_new_year_in_the_previous_season():
    assert season_of(datetime(2025, 5, 25, tzinfo=timezone.utc)) == "2024"
    assert season_of(datetime(2024, 8, 16, tzinfo=timezone.utc)) == "2024"
    assert season_of(datetime(2024, 6, 30, tzinfo=timezone.utc)) == "2023"
    assert season_of(datetime(2024, 7, 1, tzinfo=timezone.utc)) == "2024"


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def test_kickoff_parses_both_date_formats():
    assert _parse_kickoff("16/08/2024", "20:00").hour == 20
    assert _parse_kickoff("16/08/24", "20:00").year == 2024


def test_kickoff_survives_a_missing_time():
    parsed = _parse_kickoff("16/08/2024", None)

    assert parsed.hour == 0
    assert parsed.tzinfo is timezone.utc


def test_kickoff_rejects_junk():
    assert _parse_kickoff("", "20:00") is None
    assert _parse_kickoff("not a date", "20:00") is None


def test_price_prefers_the_closing_column():
    row = {"AvgC>2.5": 1.60, "Avg>2.5": 1.53, "B365>2.5": 1.50}

    assert _first_price(row, ["AvgC>2.5", "Avg>2.5", "B365>2.5"]) == 1.60


def test_price_falls_back_when_the_closing_column_is_blank():
    row = {"AvgC>2.5": float("nan"), "Avg>2.5": 1.53}

    assert _first_price(row, ["AvgC>2.5", "Avg>2.5"]) == 1.53


def test_price_ignores_impossible_values():
    assert _first_price({"Avg>2.5": 0.5}, ["Avg>2.5"]) is None
    assert _first_price({"Avg>2.5": "n/a"}, ["Avg>2.5"]) is None
    assert _first_price({}, ["Avg>2.5"]) is None


# --------------------------------------------------------------------------- #
# Teams
# --------------------------------------------------------------------------- #
def test_teams_are_derived_from_the_results_file(provider):
    teams = provider.fetch_teams("E0", "2024")

    assert {t.name for t in teams} == {
        "Man United",
        "Fulham",
        "Ipswich",
        "Liverpool",
        "Arsenal",
        "Wolves",
    }
    assert all(t.league == "Premier League" for t in teams)
    assert all(t.country == "England" for t in teams)


def test_team_ids_are_namespaced_by_division(provider):
    arsenal = next(t for t in provider.fetch_teams("E0", "2024") if t.name == "Arsenal")

    assert arsenal.external_id == "E0:Arsenal"


def test_the_season_directory_is_requested(provider):
    provider.fetch_teams("E0", "2024")

    assert provider.requested[0].endswith("/mmz4281/2425/E0.csv")


# --------------------------------------------------------------------------- #
# Matches and prices
# --------------------------------------------------------------------------- #
def test_results_carry_goals_and_closing_prices(provider):
    matches = provider.fetch_matches("E0", "2024")
    first = next(m for m in matches if m.home_name == "Man United")

    assert first.status == "finished"
    assert first.home_goals == 1
    assert first.away_goals == 0
    assert first.market_line == 2.5
    assert first.market_odds_over == 1.60  # closing, not the 1.53 opening
    assert first.market_odds_under == 2.38
    assert first.season == "2024"


def test_a_blank_closing_column_falls_back_to_an_opening_price(provider):
    arsenal = next(
        m for m in provider.fetch_matches("E0", "2024") if m.home_name == "Arsenal"
    )

    # The closing average is blank for this row, so the next column in the
    # preference order wins: the opening market average, not the single book.
    assert arsenal.market_odds_over == 1.45
    assert arsenal.market_odds_under == 2.72
    assert arsenal.market_line == 2.5


def test_fixtures_are_included_and_marked_scheduled(provider):
    matches = provider.fetch_matches("E0", "2024")
    chelsea = next(m for m in matches if m.home_name == "Chelsea")

    assert chelsea.status == "scheduled"
    assert chelsea.home_goals is None
    assert chelsea.market_odds_over == 1.72
    assert not chelsea.is_finished


def test_fixtures_from_other_divisions_are_excluded(provider):
    names = {m.home_name for m in provider.fetch_matches("E0", "2024")}

    assert "Bayern Munich" not in names


def test_fixtures_take_their_season_from_their_own_date(provider):
    """A rolling fixtures file must not inherit the ingested season.

    Ingesting several seasons calls this once per season. If an upcoming
    fixture were stamped with the requested season, every ingest would create
    another copy of it under a new key.
    """
    chelsea_2024 = next(
        m for m in provider.fetch_matches("E0", "2024") if m.home_name == "Chelsea"
    )
    chelsea_2022 = next(
        m for m in provider.fetch_matches("E0", "2022") if m.home_name == "Chelsea"
    )

    assert chelsea_2024.season == "2026"
    assert chelsea_2024.external_id == chelsea_2022.external_id


def test_ingesting_many_seasons_yields_one_row_per_fixture(provider):
    seen: set[str] = set()
    for season in ("2022", "2023", "2024"):
        seen.update(
            m.external_id
            for m in provider.fetch_matches("E0", season)
            if m.status == "scheduled"
        )

    # Two upcoming E0 fixtures, however many seasons were ingested.
    assert len(seen) == 2


def test_fixtures_can_be_switched_off(monkeypatch, provider):
    provider.include_fixtures = False

    names = {m.home_name for m in provider.fetch_matches("E0", "2024")}

    assert "Chelsea" not in names


def test_match_keys_are_stable_across_runs(provider):
    first = provider.fetch_matches("E0", "2024")
    second = provider.fetch_matches("E0", "2024")

    assert [m.external_id for m in first] == [m.external_id for m in second]
    assert len({m.external_id for m in first}) == len(first)


def test_a_missing_season_file_is_explained(monkeypatch):
    monkeypatch.setattr(
        "app.pipeline.providers.football_data_uk.httpx.get",
        lambda url, timeout=None, follow_redirects=None: FakeResponse("", 404),
    )

    with pytest.raises(ProviderError, match="does not exist"):
        FootballDataUkProvider().fetch_teams("ZZ", "2024")


def test_a_file_without_the_expected_columns_is_refused(monkeypatch):
    monkeypatch.setattr(
        "app.pipeline.providers.football_data_uk.httpx.get",
        lambda url, timeout=None, follow_redirects=None: FakeResponse("a,b\n1,2\n"),
    )

    with pytest.raises(ProviderError, match="missing expected columns"):
        FootballDataUkProvider().fetch_teams("E0", "2024")


def test_a_broken_fixtures_file_does_not_break_the_ingest(monkeypatch):
    def fake_get(url, timeout=None, follow_redirects=None):
        if url.endswith("fixtures.csv"):
            return FakeResponse("", 500)
        return FakeResponse(RESULTS_CSV)

    monkeypatch.setattr("app.pipeline.providers.football_data_uk.httpx.get", fake_get)

    matches = FootballDataUkProvider().fetch_matches("E0", "2024")

    assert len(matches) == 3
    assert all(m.status == "finished" for m in matches)
