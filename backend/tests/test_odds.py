"""Unit tests for the odds helpers."""

from __future__ import annotations

import pytest

from app.analytics.odds import (
    InvalidOddsError,
    ValueAssessment,
    assess_value,
    bookmaker_margin,
    fair_odds,
    implied_probability,
    kelly_fraction,
    overround,
    remove_vig,
)


def test_even_money_implies_half():
    assert implied_probability(2.0) == pytest.approx(0.5)


def test_implied_probability_of_a_short_price():
    assert implied_probability(1.25) == pytest.approx(0.8)


def test_implied_probability_rejects_impossible_odds():
    with pytest.raises(InvalidOddsError):
        implied_probability(0.95)
    with pytest.raises(InvalidOddsError):
        implied_probability(None)


def test_fair_odds_inverts_implied_probability():
    assert fair_odds(0.5) == pytest.approx(2.0)
    assert fair_odds(implied_probability(1.83)) == pytest.approx(1.83)


def test_fair_odds_of_an_impossible_probability_is_none():
    assert fair_odds(0.0) is None
    assert fair_odds(1.5) is None


def test_overround_exceeds_one_for_a_real_market():
    book = overround([1.90, 1.90])

    assert book > 1.0
    assert book == pytest.approx(2 / 1.9)


def test_bookmaker_margin_is_the_surplus():
    assert bookmaker_margin([2.0, 2.0]) == pytest.approx(0.0)
    assert bookmaker_margin([1.90, 1.90]) == pytest.approx(2 / 1.9 - 1)


def test_remove_vig_normalises_to_one():
    probabilities = remove_vig([1.80, 2.05])

    assert sum(probabilities) == pytest.approx(1.0)
    assert probabilities[0] > probabilities[1]  # the shorter price is likelier


def test_remove_vig_of_a_balanced_market_is_a_coin_flip():
    assert remove_vig([1.90, 1.90]) == pytest.approx([0.5, 0.5])


def test_assess_value_finds_a_positive_edge():
    # The market prices Over at 2.00 (50%) but the model says 60%.
    assessment = assess_value("OVER", 2.00, 0.60, opposite_odds=2.00)

    assert assessment.fair_market_probability == pytest.approx(0.5)
    assert assessment.edge == pytest.approx(0.10)
    assert assessment.expected_value == pytest.approx(0.20)
    assert assessment.is_value


def test_assess_value_flags_a_negative_edge():
    assessment = assess_value("UNDER", 1.80, 0.40, opposite_odds=2.10)

    assert assessment.edge < 0
    assert assessment.expected_value < 0
    assert not assessment.is_value


def test_assess_value_without_the_opposite_price_keeps_the_margin():
    assessment = assess_value("OVER", 1.90, 0.55)

    assert assessment.fair_market_probability == pytest.approx(implied_probability(1.90))


def test_assess_value_rejects_an_out_of_range_probability():
    with pytest.raises(ValueError):
        assess_value("OVER", 2.0, 1.4)


def test_expected_value_is_zero_at_the_fair_price():
    assessment = assess_value("OVER", 2.0, 0.5)

    assert assessment.expected_value == pytest.approx(0.0)
    assert not assessment.is_value


def test_kelly_is_zero_without_an_edge():
    assert kelly_fraction(0.45, 2.00) == 0.0
    assert kelly_fraction(0.50, 2.00) == pytest.approx(0.0)


def test_kelly_is_capped():
    assert kelly_fraction(0.95, 3.00, cap=0.05) == pytest.approx(0.05)


def test_kelly_matches_the_formula_below_the_cap():
    # p=0.55, b=1.0 gives (0.55 * 1 - 0.45) / 1 = 0.10, capped here at 0.25.
    assert kelly_fraction(0.55, 2.00, cap=0.25) == pytest.approx(0.10)


def test_value_assessment_is_a_plain_dataclass():
    assessment = assess_value("OVER", 2.0, 0.55)

    assert isinstance(assessment, ValueAssessment)
    assert assessment.selection == "OVER"
    assert assessment.decimal_odds == 2.0
