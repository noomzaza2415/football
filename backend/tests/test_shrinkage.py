"""Unit tests for the shrinkage step.

Shrinkage exists because walk-forward testing showed the raw strength ratios
carrying more estimation noise than signal. The properties tested here are the
ones that make the change safe: it never overshoots past average, it trusts
larger samples more, and the two extremes reproduce the two forecasters the
backtest already compares.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.analytics.poisson_model import (
    MAX_STRENGTH,
    MIN_STRENGTH,
    LeagueAverages,
    MatchResult,
    _shrink,
    _shrinkage_constant,
    compute_league_averages,
    compute_team_strengths,
    expected_goals,
)


def varied_league(repeats: int = 6) -> list[MatchResult]:
    """Four teams with genuinely different scoring rates."""
    scorelines = [
        (1, 2, 4, 0),
        (1, 3, 3, 1),
        (1, 4, 5, 0),
        (2, 1, 1, 3),
        (2, 3, 1, 1),
        (2, 4, 2, 0),
        (3, 1, 0, 2),
        (3, 2, 1, 1),
        (3, 4, 1, 0),
        (4, 1, 0, 3),
        (4, 2, 0, 2),
        (4, 3, 0, 1),
    ]
    return [
        MatchResult(h, a, hg, ag)
        for _ in range(repeats)
        for h, a, hg, ag in scorelines
    ]


def identical_league(repeats: int = 8) -> list[MatchResult]:
    """Four teams that are all exactly the same, so any spread is noise."""
    rng = np.random.default_rng(11)
    pairs = [(1, 2), (3, 4), (2, 1), (4, 3), (1, 3), (2, 4), (3, 1), (4, 2)]
    return [
        MatchResult(h, a, int(rng.poisson(1.5)), int(rng.poisson(1.2)))
        for _ in range(repeats)
        for h, a in pairs
    ]


# --------------------------------------------------------------------------- #
# The shrink function itself
# --------------------------------------------------------------------------- #
def test_zero_constant_leaves_the_ratio_alone():
    assert _shrink(1.6, 10, 0.0) == pytest.approx(1.6)
    assert _shrink(0.5, 3, 0.0) == pytest.approx(0.5)


def test_infinite_constant_shrinks_all_the_way_to_average():
    assert _shrink(2.4, 50, math.inf) == pytest.approx(1.0)
    assert _shrink(0.3, 50, math.inf) == pytest.approx(1.0)


def test_shrinkage_moves_toward_one_but_never_past_it():
    above = _shrink(1.8, 10, 10.0)
    below = _shrink(0.4, 10, 10.0)

    assert 1.0 < above < 1.8
    assert 0.4 < below < 1.0


def test_more_matches_means_less_shrinkage():
    few = _shrink(1.8, 5, 20.0)
    many = _shrink(1.8, 80, 20.0)

    assert abs(many - 1.0) > abs(few - 1.0)
    assert many < 1.8


def test_the_constant_is_the_sample_size_that_halves_the_gap():
    # k = n / (n + c), so at n == c the ratio moves exactly halfway to 1.0.
    assert _shrink(1.8, 20, 20.0) == pytest.approx(1.4)


def test_shrunk_values_are_still_clamped():
    assert _shrink(99.0, 1000, 1.0) <= MAX_STRENGTH
    assert _shrink(0.0001, 1000, 1.0) >= MIN_STRENGTH


# --------------------------------------------------------------------------- #
# Choosing the constant
# --------------------------------------------------------------------------- #
def test_mode_none_disables_shrinkage():
    assert _shrinkage_constant({1: (1.5, 10)}, 1.4, None) == 0.0


def test_an_explicit_number_is_used_as_given():
    assert _shrinkage_constant({1: (1.5, 10)}, 1.4, 12.0) == 12.0


def test_a_negative_constant_is_refused():
    with pytest.raises(ValueError):
        _shrinkage_constant({1: (1.5, 10)}, 1.4, -1.0)


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        _shrinkage_constant({1: (1.5, 10)}, 1.4, "aggressive")


def test_auto_needs_several_teams():
    assert math.isinf(_shrinkage_constant({1: (1.5, 10)}, 1.4, "auto"))


def test_auto_returns_a_finite_constant_when_teams_really_differ():
    entries = {
        1: (1.60, 30),
        2: (1.10, 30),
        3: (0.85, 30),
        4: (0.50, 30),
    }
    constant = _shrinkage_constant(entries, 1.5, "auto")

    assert 0 < constant < math.inf


def test_auto_shrinks_everything_when_the_spread_is_only_noise():
    # Four teams a hair apart on three matches each: the spread is smaller than
    # the Poisson noise those three matches carry.
    entries = {1: (1.02, 3), 2: (0.99, 3), 3: (1.01, 3), 4: (0.98, 3)}

    assert math.isinf(_shrinkage_constant(entries, 1.5, "auto"))


def test_auto_trusts_a_large_spread_more_than_a_small_one():
    wide = {1: (1.8, 30), 2: (1.2, 30), 3: (0.8, 30), 4: (0.4, 30)}
    narrow = {1: (1.15, 30), 2: (1.05, 30), 3: (0.95, 30), 4: (0.85, 30)}

    # A smaller constant means more of the raw ratio survives.
    assert _shrinkage_constant(wide, 1.5, "auto") < _shrinkage_constant(narrow, 1.5, "auto")


# --------------------------------------------------------------------------- #
# End to end through compute_team_strengths
# --------------------------------------------------------------------------- #
def test_shrinkage_is_off_by_default_so_existing_behaviour_is_unchanged():
    history = varied_league()

    default = compute_team_strengths(history)
    explicit_off = compute_team_strengths(history, shrinkage=None)

    assert default[1].attack_home == pytest.approx(explicit_off[1].attack_home)


def test_auto_pulls_every_strength_toward_average():
    history = varied_league()
    league = compute_league_averages(history)

    raw = compute_team_strengths(history, league, shrinkage=None)
    shrunk = compute_team_strengths(history, league, shrinkage="auto")

    for team_id, strength in shrunk.items():
        for field in ("attack_home", "defense_home", "attack_away", "defense_away"):
            raw_value = getattr(raw[team_id], field)
            shrunk_value = getattr(strength, field)
            assert abs(shrunk_value - 1.0) <= abs(raw_value - 1.0) + 1e-9


def test_shrinkage_preserves_the_ordering_of_teams():
    history = varied_league()
    league = compute_league_averages(history)

    raw = compute_team_strengths(history, league, shrinkage=None)
    shrunk = compute_team_strengths(history, league, shrinkage="auto")

    # Team 1 scores freely, team 4 does not; shrinking must not swap them.
    assert (raw[1].attack_home > raw[4].attack_home) == (
        shrunk[1].attack_home > shrunk[4].attack_home
    )


def test_a_league_of_clones_collapses_to_average():
    history = identical_league()

    shrunk = compute_team_strengths(history, shrinkage="auto")

    for strength in shrunk.values():
        assert strength.attack_home == pytest.approx(1.0, abs=0.05)
        assert strength.attack_away == pytest.approx(1.0, abs=0.05)


def test_full_shrinkage_makes_expected_goals_equal_the_league_average():
    """The k = 0 extreme must reproduce the league-only baseline exactly."""
    history = varied_league()
    league = compute_league_averages(history)

    strengths = compute_team_strengths(history, league, shrinkage=math.inf)
    lambda_home, lambda_away = expected_goals(strengths[1], strengths[4], league)

    assert lambda_home == pytest.approx(league.home_goals)
    assert lambda_away == pytest.approx(league.away_goals)


def test_a_large_constant_shrinks_more_than_a_small_one():
    history = varied_league()
    league = compute_league_averages(history)

    light = compute_team_strengths(history, league, shrinkage=5.0)
    heavy = compute_team_strengths(history, league, shrinkage=100.0)

    assert abs(heavy[1].attack_home - 1.0) < abs(light[1].attack_home - 1.0)


def test_shrinkage_narrows_the_spread_of_expected_totals():
    """The point of the change: fewer extreme expected totals, less noise."""
    history = varied_league()
    league = compute_league_averages(history)

    def totals(shrinkage) -> list[float]:
        strengths = compute_team_strengths(history, league, shrinkage=shrinkage)
        return [
            sum(expected_goals(strengths[h], strengths[a], league))
            for h in strengths
            for a in strengths
            if h != a
        ]

    assert np.std(totals("auto")) < np.std(totals(None))
