"""Tests for the matchday view, the calendar and the freshness stamp."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Match, MatchStatus


def test_calendar_lists_only_days_that_have_matches(client, seeded_db):
    body = client.get("/api/matches/calendar").json()

    assert body["earliest"] is not None
    assert body["latest"] is not None
    assert len(body["days"]) > 0

    for day in body["days"]:
        assert day["total"] == day["scheduled"] + day["finished"]
        assert day["total"] > 0

    dates = [day["date"] for day in body["days"]]
    assert dates == sorted(dates)


def test_calendar_is_empty_without_matches(client, db_session):
    body = client.get("/api/matches/calendar").json()

    assert body["earliest"] is None
    assert body["days"] == []


def test_match_day_defaults_to_the_upcoming_fixture(client, seeded_db, db_session):
    upcoming = db_session.get(Match, seeded_db["upcoming_id"])
    body = client.get("/api/matches/day").json()

    # The only scheduled match is three days out, so that is the day to open on.
    assert body["day"] == upcoming.match_date.date().isoformat()
    assert [m["match"]["id"] for m in body["matches"]] == [upcoming.id]


def test_match_day_accepts_an_explicit_day(client, seeded_db, db_session):
    finished = (
        db_session.query(Match)
        .filter(Match.status == MatchStatus.FINISHED)
        .order_by(Match.match_date.asc())
        .first()
    )
    day = finished.match_date.date().isoformat()

    body = client.get("/api/matches/day", params={"day": day}).json()

    assert body["day"] == day
    assert len(body["matches"]) >= 1
    assert all(m["match"]["match_date"].startswith(day) for m in body["matches"])


def test_a_day_with_no_football_returns_an_empty_list(client, seeded_db):
    body = client.get("/api/matches/day", params={"day": "1999-01-01"}).json()

    assert body["day"] == "1999-01-01"
    assert body["matches"] == []
    # The neighbours still point at real days, so the arrows keep working.
    assert body["next_day"] is not None


def test_neighbour_days_skip_days_without_football(client, seeded_db):
    body = client.get("/api/matches/day").json()
    day = body["day"]

    assert body["previous_day"] is None or body["previous_day"] < day
    assert body["next_day"] is None or body["next_day"] > day


def test_a_finished_match_is_predicted_without_seeing_its_own_result(
    client, seeded_db, db_session
):
    """A past day must show what the model would have said before kick-off."""
    finished = (
        db_session.query(Match)
        .filter(Match.status == MatchStatus.FINISHED)
        .order_by(Match.match_date.desc())
        .first()
    )
    day = finished.match_date.date().isoformat()

    body = client.get("/api/matches/day", params={"day": day}).json()
    summary = next(m for m in body["matches"] if m["match"]["id"] == finished.id)

    assert summary["point_in_time"] is True
    # Every match on the day is excluded from its own fit, so the sample is
    # smaller than the full history.
    total_finished = (
        db_session.query(Match).filter(Match.status == MatchStatus.FINISHED).count()
    )
    assert summary["actual_total_goals"] == finished.home_goals + finished.away_goals
    assert total_finished > 0


def test_an_upcoming_match_is_not_flagged_point_in_time(client, seeded_db):
    body = client.get("/api/matches/day").json()

    assert body["matches"][0]["point_in_time"] is False
    assert body["matches"][0]["actual_total_goals"] is None
    assert body["matches"][0]["model_correct"] is None


def test_a_finished_match_reports_whether_the_model_was_right(
    client, seeded_db, db_session
):
    finished = (
        db_session.query(Match)
        .filter(Match.status == MatchStatus.FINISHED)
        .order_by(Match.match_date.desc())
        .first()
    )
    day = finished.match_date.date().isoformat()

    summary = next(
        m
        for m in client.get("/api/matches/day", params={"day": day}).json()["matches"]
        if m["match"]["id"] == finished.id
    )

    total = finished.home_goals + finished.away_goals
    assert summary["actual_result"] == ("OVER" if total > 2.5 else "UNDER")
    if summary["lean"] in {"OVER", "UNDER"}:
        assert summary["model_correct"] == (summary["lean"] == summary["actual_result"])
    else:
        assert summary["model_correct"] is None


def test_predictions_can_be_switched_off_for_a_cheap_listing(client, seeded_db):
    body = client.get(
        "/api/matches/day", params={"include_prediction": False}
    ).json()

    assert body["matches"][0]["expected_total_goals"] is None
    assert body["matches"][0]["lean"] is None


def test_freshness_reports_the_stored_data_age(client, seeded_db):
    freshness = client.get("/api/matches/day").json()["freshness"]

    assert freshness["server_time"] is not None
    assert freshness["latest_result_at"] is not None
    assert freshness["next_kickoff_at"] is not None


def test_range_returns_matches_between_two_days(client, seeded_db, db_session):
    first = (
        db_session.query(Match)
        .order_by(Match.match_date.asc())
        .first()
        .match_date.date()
    )
    body = client.get(
        "/api/matches/range",
        params={
            "date_from": first.isoformat(),
            "date_to": (first + timedelta(days=10)).isoformat(),
        },
    ).json()

    assert len(body) > 0
    dates = [m["match"]["match_date"] for m in body]
    assert dates == sorted(dates)


def test_range_rejects_a_backwards_window(client, seeded_db):
    response = client.get(
        "/api/matches/range",
        params={"date_from": "2025-01-10", "date_to": "2025-01-01"},
    )

    assert response.status_code == 422


def test_range_rejects_an_oversized_window(client, seeded_db):
    response = client.get(
        "/api/matches/range",
        params={"date_from": "2020-01-01", "date_to": "2025-01-01"},
    )

    assert response.status_code == 422
    assert "60 days" in response.json()["detail"]


def test_upcoming_still_works_alongside_the_day_view(client, seeded_db):
    body = client.get("/api/matches/upcoming").json()

    assert len(body) == 1
    assert body[0]["match"]["status"] == "scheduled"


def test_prediction_endpoint_defaults_to_honest_for_a_played_match(
    client, seeded_db, db_session
):
    """The detail page of a past match must not show a model that saw the score."""
    finished = (
        db_session.query(Match)
        .filter(Match.status == MatchStatus.FINISHED)
        .order_by(Match.match_date.desc())
        .first()
    )

    honest = client.get(f"/api/matches/{finished.id}/prediction").json()
    peeking = client.get(
        f"/api/matches/{finished.id}/prediction", params={"point_in_time": False}
    ).json()

    # The honest fit sees strictly fewer matches than the peeking one.
    assert honest["sample_matches"] < peeking["sample_matches"]


def test_prediction_endpoint_uses_everything_for_an_upcoming_match(
    client, seeded_db
):
    body = client.get(
        f"/api/matches/{seeded_db['upcoming_id']}/prediction"
    ).json()

    assert body["sample_matches"] == 32
