"""Unit tests for the walk-forward backtest.

The most important test in this file is the look-ahead guard: if the engine
ever let a match influence its own prediction, every accuracy number the
project reports would be fiction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.analytics.backtest import (
    DEFAULT_LINE,
    BacktestRecord,
    DatedMatch,
    NotEnoughHistoryError,
    walk_forward,
)
from app.analytics.poisson_model import (
    compute_league_averages,
    compute_team_strengths,
    predict_match,
)

START = datetime(2024, 8, 1, tzinfo=timezone.utc)


def build_matches(
    count: int = 120,
    *,
    with_odds: bool = False,
    scorelines: list[tuple[int, int, int, int]] | None = None,
) -> list[DatedMatch]:
    """A four-team league played one match per day."""
    scorelines = scorelines or [
        (1, 2, 3, 0),
        (2, 3, 1, 1),
        (3, 4, 2, 1),
        (4, 1, 0, 2),
        (2, 1, 1, 2),
        (3, 1, 0, 1),
        (1, 3, 2, 2),
        (4, 2, 1, 3),
    ]

    matches: list[DatedMatch] = []
    for index in range(count):
        home, away, home_goals, away_goals = scorelines[index % len(scorelines)]
        matches.append(
            DatedMatch(
                match_id=index + 1,
                kickoff=START + timedelta(days=index),
                league="Test League",
                home_team_id=home,
                away_team_id=away,
                home_goals=home_goals,
                away_goals=away_goals,
                home_name=f"Team {home}",
                away_name=f"Team {away}",
                market_line=DEFAULT_LINE if with_odds else None,
                market_odds_over=1.95 if with_odds else None,
                market_odds_under=1.95 if with_odds else None,
            )
        )
    return matches


# --------------------------------------------------------------------------- #
# The look-ahead guard
# --------------------------------------------------------------------------- #
def test_prediction_uses_only_matches_before_kickoff():
    """Each prediction must equal one refitted by hand on the prefix alone."""
    matches = build_matches(90)
    report = walk_forward(matches, min_train_matches=60, last_n=20)

    ordered = sorted(matches, key=lambda m: (m.kickoff, m.match_id))

    for offset, record in enumerate(report.records):
        target = ordered[60 + offset]
        assert record.match_id == target.match_id

        prefix = [m.as_result() for m in ordered[: 60 + offset]]
        league = compute_league_averages(prefix)
        strengths = compute_team_strengths(prefix, league, last_n=20)
        expected = predict_match(
            target.home_team_id,
            target.away_team_id,
            strengths,
            league,
            lines=[DEFAULT_LINE],
        )

        assert record.prob_over == pytest.approx(expected.lines[DEFAULT_LINE].prob_over)
        assert record.predicted_total_goals == pytest.approx(expected.expected_total_goals)


def test_changing_a_future_result_does_not_change_an_earlier_prediction():
    """Rewriting the last match must leave every earlier prediction untouched."""
    matches = build_matches(80)
    baseline = walk_forward(matches, min_train_matches=60)

    tampered = list(matches)
    last = tampered[-1]
    tampered[-1] = DatedMatch(
        match_id=last.match_id,
        kickoff=last.kickoff,
        league=last.league,
        home_team_id=last.home_team_id,
        away_team_id=last.away_team_id,
        home_goals=9,  # an absurd result that would wreck any fit that saw it
        away_goals=9,
        home_name=last.home_name,
        away_name=last.away_name,
    )
    after = walk_forward(tampered, min_train_matches=60)

    # Every record except the tampered one is identical.
    for before_record, after_record in zip(baseline.records[:-1], after.records[:-1]):
        assert before_record.prob_over == pytest.approx(after_record.prob_over)

    # And the last prediction itself is unchanged, because its own result
    # cannot reach its own fit; only the actual score differs.
    assert baseline.records[-1].prob_over == pytest.approx(after.records[-1].prob_over)
    assert after.records[-1].actual_total_goals == 18


def test_matches_are_sorted_so_a_bad_input_order_cannot_leak_the_future():
    matches = build_matches(80)
    shuffled = list(reversed(matches))

    in_order = walk_forward(matches, min_train_matches=60)
    reversed_input = walk_forward(shuffled, min_train_matches=60)

    assert [r.match_id for r in in_order.records] == [
        r.match_id for r in reversed_input.records
    ]
    assert in_order.brier == pytest.approx(reversed_input.brier)


def test_training_set_grows_by_one_each_step():
    report = walk_forward(build_matches(75), min_train_matches=60)

    sizes = [record.train_size for record in report.records]
    assert sizes == list(range(60, 75))


def test_rolling_window_keeps_the_training_size_fixed():
    report = walk_forward(
        build_matches(100), min_train_matches=60, window="rolling", train_window=40
    )

    assert {record.train_size for record in report.records} == {40}


# --------------------------------------------------------------------------- #
# Guard rails
# --------------------------------------------------------------------------- #
def test_too_little_history_is_refused():
    with pytest.raises(NotEnoughHistoryError):
        walk_forward(build_matches(30), min_train_matches=60)


def test_rolling_without_a_window_is_refused():
    with pytest.raises(ValueError):
        walk_forward(build_matches(80), window="rolling")


def test_tiny_training_window_is_refused():
    with pytest.raises(ValueError):
        walk_forward(build_matches(80), min_train_matches=5)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def test_every_match_after_the_warmup_is_tested():
    report = walk_forward(build_matches(100), min_train_matches=60)

    assert report.tested == 40
    assert all(0.0 <= record.prob_over <= 1.0 for record in report.records)


def test_baselines_are_scored_on_the_same_matches():
    report = walk_forward(build_matches(100), min_train_matches=60)
    cards = report.scorecards()

    names = [card.name for card in cards]
    assert "โมเดล" in names[0]
    assert len(cards) >= 4
    assert all(card.samples == report.tested for card in cards[:4])


def test_market_baseline_appears_only_when_odds_exist():
    without = walk_forward(build_matches(100), min_train_matches=60)
    with_odds = walk_forward(
        build_matches(100, with_odds=True), min_train_matches=60
    )

    assert len(without.scorecards()) == 4
    assert len(with_odds.scorecards()) == 6
    assert with_odds.records[0].market_prob_over == pytest.approx(0.5)


def test_brier_is_zero_for_a_perfect_forecast():
    """A sanity check on the scoring itself, not on the model."""
    report = walk_forward(build_matches(80), min_train_matches=60)
    record = report.records[0]

    perfect = BacktestRecord(
        **{
            **record.__dict__,
            "prob_over": 1.0 if record.actual_over else 0.0,
        }
    )
    report.records = [perfect]

    assert report.brier == pytest.approx(0.0, abs=1e-8)


def test_skill_score_is_positive_when_the_model_beats_the_baseline():
    report = walk_forward(build_matches(120), min_train_matches=60)
    cards = report.scorecards()
    model, base_rate = cards[0], cards[2]

    skill = model.skill_against(base_rate)
    # Not asserting the model wins, only that the arithmetic has the right sign.
    assert (skill > 0) == (model.brier < base_rate.brier)


def test_neutral_picks_are_excluded_from_accuracy():
    report = walk_forward(build_matches(100), min_train_matches=60)

    assert len(report.scored) <= report.tested
    assert all(record.correct is not None for record in report.scored)
    assert all(record.pick != "NEUTRAL" for record in report.scored)


def test_calibration_bins_cover_every_record():
    report = walk_forward(build_matches(120), min_train_matches=60)

    assert sum(bucket.samples for bucket in report.calibration()) == report.tested
    assert all(0.0 <= bucket.actual_rate <= 1.0 for bucket in report.calibration())


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #
def test_profit_is_none_when_no_price_was_stored():
    report = walk_forward(build_matches(80), min_train_matches=60)

    assert report.priced_picks == []
    assert report.roi == 0.0


def test_flat_staking_profit_matches_the_price():
    report = walk_forward(build_matches(100, with_odds=True), min_train_matches=60)

    for record in report.priced_picks:
        expected = 0.95 if record.correct else -1.0
        assert record.profit() == pytest.approx(expected)

    assert report.profit == pytest.approx(
        sum(record.profit() for record in report.priced_picks)
    )


def test_roi_is_profit_per_unit_staked():
    report = walk_forward(build_matches(100, with_odds=True), min_train_matches=60)

    if report.priced_picks:
        assert report.roi == pytest.approx(report.profit / len(report.priced_picks))


def test_goal_error_metrics_are_non_negative():
    report = walk_forward(build_matches(100), min_train_matches=60)

    assert report.mean_absolute_goal_error >= 0
    assert report.rmse_goals >= report.mean_absolute_goal_error - 1e-9
