"""Unit tests for the team_stats aggregation."""

from __future__ import annotations

import pytest

from app.analytics.poisson_model import MatchResult
from app.analytics.stats_builder import (
    build_all_team_stats,
    build_team_stats,
    form_string,
    team_match_view,
)

HISTORY = [
    MatchResult(1, 2, 3, 0),  # team 1 home win
    MatchResult(2, 1, 1, 1),  # team 1 away draw
    MatchResult(1, 3, 2, 1),  # team 1 home win
    MatchResult(3, 1, 2, 0),  # team 1 away loss
    MatchResult(1, 2, 0, 0),  # team 1 home draw
]


def test_team_match_view_orients_goals_to_the_team():
    view = team_match_view(HISTORY, 1)

    assert len(view) == 5
    assert view[0].is_home and view[0].goals_for == 3
    assert not view[1].is_home and view[1].goals_for == 1
    assert view[3].goals_for == 0 and view[3].goals_against == 2


def test_form_string_is_most_recent_last():
    assert form_string(HISTORY, 1) == "WDWLD"


def test_form_string_respects_the_window():
    assert form_string(HISTORY, 1, window=3) == "WLD"


def test_form_string_is_empty_for_an_unknown_team():
    assert form_string(HISTORY, 99) == ""


def test_averages_are_split_by_venue():
    row = build_team_stats(HISTORY, 1)

    # Home: 3, 2, 0 scored and 0, 1, 0 conceded.
    assert row.avg_goals_scored_home == pytest.approx(5 / 3)
    assert row.avg_goals_conceded_home == pytest.approx(1 / 3)
    # Away: 1 and 0 scored, 1 and 2 conceded.
    assert row.avg_goals_scored_away == pytest.approx(0.5)
    assert row.avg_goals_conceded_away == pytest.approx(1.5)
    assert row.matches_played_home == 3
    assert row.matches_played_away == 2


def test_over_rate_and_btts_rate():
    row = build_team_stats(HISTORY, 1)

    # Totals are 3, 2, 3, 2, 0; two of the five clear 2.5.
    assert row.over_2_5_rate == pytest.approx(0.4)
    # Both sides scored only in the 1-1 and the 2-1.
    assert row.btts_rate == pytest.approx(0.4)


def test_form_points_count_three_for_a_win():
    row = build_team_stats(HISTORY, 1)

    # W D W L D over the last five.
    assert row.form_points_last_5 == 3 + 1 + 3 + 0 + 1


def test_unknown_team_returns_an_empty_row():
    row = build_team_stats(HISTORY, 99)

    assert row.matches_played == 0
    assert row.form_last_5 == ""
    assert row.attack_strength_home == 1.0


def test_build_all_covers_every_team_and_carries_strengths():
    rows = build_all_team_stats(HISTORY)

    assert set(rows) == {1, 2, 3}
    assert rows[1].sample_matches == 5
    # The strengths come from the Poisson fit, not the defaults.
    assert rows[1].attack_strength_home > 0


def test_build_all_on_empty_history_returns_nothing():
    assert build_all_team_stats([]) == {}
