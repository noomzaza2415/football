"""Unit tests for the Poisson goal model."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import poisson

from app.analytics.poisson_model import (
    DEFAULT_LINES,
    MAX_STRENGTH,
    MIN_STRENGTH,
    InsufficientDataError,
    LeagueAverages,
    MatchResult,
    TeamStrength,
    compute_league_averages,
    compute_team_strengths,
    dixon_coles_tau,
    expected_goals,
    match_outcome_probabilities,
    most_likely_scoreline,
    over_under_probability,
    over_under_table,
    predict_from_history,
    predict_match,
    score_matrix,
    total_goals_distribution,
)

TOL = 1e-9


def build_history(rounds: int = 6) -> list[MatchResult]:
    """A tiny four-team league where team 1 is strong and team 4 is weak."""
    history: list[MatchResult] = []
    scorelines = [
        (1, 2, 3, 0),
        (3, 4, 2, 1),
        (2, 1, 1, 1),
        (4, 3, 0, 2),
        (1, 3, 2, 0),
        (2, 4, 3, 1),
        (3, 1, 1, 2),
        (4, 2, 0, 1),
    ]
    for _ in range(rounds):
        for home, away, home_goals, away_goals in scorelines:
            history.append(MatchResult(home, away, home_goals, away_goals))
    return history


# --------------------------------------------------------------------------- #
# League averages
# --------------------------------------------------------------------------- #
def test_league_averages_split_home_and_away():
    matches = [
        MatchResult(1, 2, 2, 1),
        MatchResult(3, 4, 1, 0),
        MatchResult(2, 1, 0, 2),
    ]
    league = compute_league_averages(matches)

    assert league.home_goals == pytest.approx(1.0)
    assert league.away_goals == pytest.approx(1.0)
    assert league.total_goals == pytest.approx(2.0)
    assert league.matches == 3


def test_league_averages_reject_empty_input():
    with pytest.raises(InsufficientDataError):
        compute_league_averages([])


# --------------------------------------------------------------------------- #
# Team strengths
# --------------------------------------------------------------------------- #
def test_strength_of_exactly_average_team_is_one():
    # Every team scores 1 at home and 1 away, so nobody deviates from average.
    matches = [
        MatchResult(1, 2, 1, 1),
        MatchResult(2, 1, 1, 1),
        MatchResult(1, 2, 1, 1),
        MatchResult(2, 1, 1, 1),
        MatchResult(1, 2, 1, 1),
        MatchResult(2, 1, 1, 1),
    ]
    strengths = compute_team_strengths(matches, min_matches=3)

    for strength in strengths.values():
        assert strength.attack_home == pytest.approx(1.0)
        assert strength.attack_away == pytest.approx(1.0)
        assert strength.defense_home == pytest.approx(1.0)
        assert strength.defense_away == pytest.approx(1.0)


def test_strong_team_outranks_weak_team():
    strengths = compute_team_strengths(build_history(), min_matches=3)

    assert strengths[1].attack_home > strengths[4].attack_home
    # Lower defense number means fewer goals conceded.
    assert strengths[1].defense_home < strengths[4].defense_home


def test_team_below_min_matches_falls_back_to_neutral():
    matches = [
        MatchResult(1, 2, 2, 1),
        MatchResult(1, 2, 1, 0),
        MatchResult(1, 2, 3, 1),
        MatchResult(1, 3, 2, 0),
    ]
    # Team 2 has never played at home, team 3 has one away game only.
    strengths = compute_team_strengths(matches, min_matches=3)

    assert strengths[2].attack_home == 1.0
    assert strengths[2].defense_home == 1.0
    assert strengths[3].attack_away == 1.0


def test_strengths_are_clamped_to_a_sane_range():
    # Team 1 wins 9-0 every week; the ratio must still be capped.
    matches = [MatchResult(1, 2, 9, 0) for _ in range(5)]
    matches += [MatchResult(3, 4, 1, 1) for _ in range(5)]
    strengths = compute_team_strengths(matches, min_matches=3)

    for strength in strengths.values():
        for value in (
            strength.attack_home,
            strength.attack_away,
            strength.defense_home,
            strength.defense_away,
        ):
            assert MIN_STRENGTH <= value <= MAX_STRENGTH


def test_last_n_window_tracks_recent_form():
    old = [MatchResult(1, 2, 0, 0) for _ in range(10)]
    recent = [MatchResult(1, 2, 4, 0) for _ in range(5)]
    history = old + recent

    windowed = compute_team_strengths(history, last_n=5, min_matches=3)
    full = compute_team_strengths(history, last_n=None, min_matches=3)

    assert windowed[1].attack_home > full[1].attack_home


def test_strengths_reject_empty_input():
    with pytest.raises(InsufficientDataError):
        compute_team_strengths([])


# --------------------------------------------------------------------------- #
# Expected goals
# --------------------------------------------------------------------------- #
def test_expected_goals_for_neutral_teams_equal_league_average():
    league = LeagueAverages(home_goals=1.5, away_goals=1.1, matches=100)
    neutral = TeamStrength(1, 1.0, 1.0, 1.0, 1.0)

    lambda_home, lambda_away = expected_goals(neutral, neutral, league)

    assert lambda_home == pytest.approx(1.5)
    assert lambda_away == pytest.approx(1.1)


def test_expected_goals_multiply_attack_by_opponent_defense():
    league = LeagueAverages(home_goals=1.5, away_goals=1.0, matches=100)
    home = TeamStrength(1, attack_home=1.4, defense_home=0.8, attack_away=1.0, defense_away=1.0)
    away = TeamStrength(2, attack_home=1.0, defense_home=1.0, attack_away=0.9, defense_away=1.2)

    lambda_home, lambda_away = expected_goals(home, away, league)

    assert lambda_home == pytest.approx(1.4 * 1.2 * 1.5)
    assert lambda_away == pytest.approx(0.9 * 0.8 * 1.0)


def test_expected_goals_handle_unknown_teams():
    league = LeagueAverages(home_goals=1.4, away_goals=1.1, matches=50)

    lambda_home, lambda_away = expected_goals(None, None, league)

    assert lambda_home == pytest.approx(1.4)
    assert lambda_away == pytest.approx(1.1)


# --------------------------------------------------------------------------- #
# Score matrix
# --------------------------------------------------------------------------- #
def test_score_matrix_sums_to_one():
    matrix = score_matrix(1.6, 1.2, max_goals=6)

    assert matrix.shape == (7, 7)
    assert matrix.sum() == pytest.approx(1.0, abs=TOL)
    assert (matrix >= 0).all()


def test_score_matrix_matches_independent_poisson_before_renormalisation():
    lambda_home, lambda_away = 1.7, 1.1
    matrix = score_matrix(lambda_home, lambda_away, max_goals=10)

    # With a 10 goal grid the truncated mass is tiny, so the renormalised cell
    # should still be within a whisker of the raw product of the two pmfs.
    raw = poisson.pmf(2, lambda_home) * poisson.pmf(1, lambda_away)
    assert matrix[2][1] == pytest.approx(raw, rel=1e-4)


def test_score_matrix_rejects_non_positive_lambda():
    with pytest.raises(ValueError):
        score_matrix(0.0, 1.2)
    with pytest.raises(ValueError):
        score_matrix(1.2, -0.5)


def test_larger_max_goals_changes_the_tail_only_slightly():
    small = over_under_probability(score_matrix(1.5, 1.3, max_goals=6), 2.5)
    large = over_under_probability(score_matrix(1.5, 1.3, max_goals=12), 2.5)

    assert small.prob_over == pytest.approx(large.prob_over, abs=0.01)


# --------------------------------------------------------------------------- #
# Dixon-Coles
# --------------------------------------------------------------------------- #
def test_dixon_coles_tau_is_neutral_for_high_scores():
    assert dixon_coles_tau(2, 1, 1.5, 1.2, -0.1) == 1.0
    assert dixon_coles_tau(0, 3, 1.5, 1.2, -0.1) == 1.0


def test_negative_rho_lifts_the_draw_probabilities():
    plain = score_matrix(1.4, 1.2, max_goals=8, rho=0.0)
    corrected = score_matrix(1.4, 1.2, max_goals=8, rho=-0.1)

    assert corrected[0][0] > plain[0][0]
    assert corrected[1][1] > plain[1][1]
    assert corrected.sum() == pytest.approx(1.0, abs=TOL)


# --------------------------------------------------------------------------- #
# Totals and Over/Under
# --------------------------------------------------------------------------- #
def test_total_goals_distribution_sums_to_one():
    distribution = total_goals_distribution(score_matrix(1.5, 1.5, max_goals=6))

    assert sum(distribution.values()) == pytest.approx(1.0, abs=TOL)
    assert set(distribution) == set(range(13))


def test_over_and_under_are_complementary_on_a_half_line():
    matrix = score_matrix(1.6, 1.4)
    result = over_under_probability(matrix, 2.5)

    assert result.prob_push == pytest.approx(0.0, abs=TOL)
    assert result.prob_over + result.prob_under == pytest.approx(1.0, abs=TOL)


def test_whole_number_line_produces_a_push():
    matrix = score_matrix(1.6, 1.4)
    result = over_under_probability(matrix, 2.0)

    assert result.prob_push > 0.0
    total = result.prob_over + result.prob_under + result.prob_push
    assert total == pytest.approx(1.0, abs=TOL)


def test_over_probability_falls_as_the_line_rises():
    matrix = score_matrix(1.5, 1.3)
    table = over_under_table(matrix, DEFAULT_LINES)

    assert table[1.5].prob_over > table[2.5].prob_over > table[3.5].prob_over


def test_higher_expected_goals_raise_the_over_probability():
    low = over_under_probability(score_matrix(0.9, 0.8), 2.5)
    high = over_under_probability(score_matrix(2.2, 1.9), 2.5)

    assert high.prob_over > low.prob_over


def test_over_under_probability_rejects_a_non_positive_line():
    with pytest.raises(ValueError):
        over_under_probability(score_matrix(1.5, 1.2), 0.0)


def test_fair_odds_are_the_reciprocal_of_the_probability():
    result = over_under_probability(score_matrix(1.5, 1.3), 2.5)

    assert result.fair_odds_over == pytest.approx(1 / result.prob_over)
    assert result.fair_odds_under == pytest.approx(1 / result.prob_under)


def test_over_2_5_matches_a_hand_computed_value():
    # With both lambdas at 1.0, P(total <= 2) for a Poisson(2) total is
    # e^-2 * (1 + 2 + 2) = 5 * e^-2, so P(over 2.5) = 1 - 5 * e^-2.
    matrix = score_matrix(1.0, 1.0, max_goals=14)
    result = over_under_probability(matrix, 2.5)

    assert result.prob_over == pytest.approx(1 - 5 * math.exp(-2), abs=1e-6)


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #
def test_match_outcome_probabilities_sum_to_one():
    home, draw, away = match_outcome_probabilities(score_matrix(1.7, 1.1))

    assert home + draw + away == pytest.approx(1.0, abs=TOL)
    assert home > away  # the home side has the larger lambda


def test_equal_lambdas_give_symmetric_outcomes():
    home, _, away = match_outcome_probabilities(score_matrix(1.3, 1.3))

    assert home == pytest.approx(away, abs=TOL)


def test_most_likely_scoreline_favours_the_stronger_side():
    home_goals, away_goals = most_likely_scoreline(score_matrix(2.4, 0.7))

    assert home_goals > away_goals


# --------------------------------------------------------------------------- #
# End to end
# --------------------------------------------------------------------------- #
def test_predict_match_returns_a_consistent_bundle():
    history = build_history()
    league = compute_league_averages(history)
    strengths = compute_team_strengths(history, league)

    prediction = predict_match(1, 4, strengths, league)

    assert prediction.expected_total_goals == pytest.approx(
        prediction.expected_home_goals + prediction.expected_away_goals
    )
    assert prediction.score_matrix.sum() == pytest.approx(1.0, abs=TOL)
    assert set(prediction.lines) == set(DEFAULT_LINES)
    assert sum(prediction.total_goals_distribution.values()) == pytest.approx(1.0, abs=TOL)
    assert (
        prediction.prob_home_win + prediction.prob_draw + prediction.prob_away_win
    ) == pytest.approx(1.0, abs=TOL)
    assert prediction.model_version


def test_strong_home_side_is_favoured_over_a_weak_visitor():
    history = build_history()

    strong_at_home = predict_from_history(1, 4, history)
    weak_at_home = predict_from_history(4, 1, history)

    assert strong_at_home.prob_home_win > weak_at_home.prob_home_win
    assert strong_at_home.expected_home_goals > weak_at_home.expected_home_goals


def test_prediction_is_deterministic():
    history = build_history()

    first = predict_from_history(1, 2, history)
    second = predict_from_history(1, 2, history)

    assert first.expected_home_goals == second.expected_home_goals
    assert np.allclose(first.score_matrix, second.score_matrix)


def test_custom_lines_are_honoured():
    prediction = predict_from_history(1, 2, build_history(), lines=[0.5, 4.5])

    assert set(prediction.lines) == {0.5, 4.5}
    assert prediction.lines[0.5].prob_over > prediction.lines[4.5].prob_over
