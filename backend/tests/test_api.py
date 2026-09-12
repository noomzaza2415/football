"""Smoke tests for the HTTP surface, against an in-memory database."""

from __future__ import annotations

import pytest


def test_health_reports_counts(client, seeded_db):
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["teams"] == 4
    assert body["finished_matches"] == 32


def test_root_carries_the_disclaimer(client):
    body = client.get("/").json()

    assert "เพื่อการศึกษา" in body["disclaimer"]


def test_list_teams(client, seeded_db):
    teams = client.get("/api/teams").json()

    assert len(teams) == 4
    assert teams[0]["league"] == "Test League"


def test_team_search_filters_by_name(client, seeded_db):
    teams = client.get("/api/teams", params={"search": "Team 1"}).json()

    assert len(teams) == 1
    assert teams[0]["name"] == "Team 1"


def test_unknown_team_returns_404(client, seeded_db):
    assert client.get("/api/teams/9999").status_code == 404


def test_team_stats_are_empty_until_rebuilt(client, seeded_db):
    team_id = seeded_db["team_ids"][0]

    body = client.get(f"/api/teams/{team_id}/stats").json()
    assert body["stats"] is None

    assert client.post("/api/teams/rebuild-stats").status_code == 200

    body = client.get(f"/api/teams/{team_id}/stats").json()
    assert body["stats"]["matches_played"] > 0
    assert len(body["stats"]["form_last_5"]) == 5


def test_upcoming_returns_a_summary(client, seeded_db):
    matches = client.get("/api/matches/upcoming").json()

    assert len(matches) == 1
    summary = matches[0]
    assert summary["match"]["status"] == "scheduled"
    assert summary["expected_total_goals"] > 0
    assert summary["lean"] in {"OVER", "UNDER", "NEUTRAL"}
    assert 0 <= summary["prob_over_2_5"] <= 1


def test_prediction_endpoint_returns_the_full_bundle(client, seeded_db):
    match_id = seeded_db["upcoming_id"]

    body = client.get(f"/api/matches/{match_id}/prediction").json()

    assert body["expected_total_goals"] == pytest.approx(
        body["expected_home_goals"] + body["expected_away_goals"]
    )
    assert {line["line"] for line in body["lines"]} == {1.5, 2.5, 3.5}

    total = sum(bucket["probability"] for bucket in body["total_goals_distribution"])
    assert total == pytest.approx(1.0, abs=1e-3)

    outcome = body["prob_home_win"] + body["prob_draw"] + body["prob_away_win"]
    assert outcome == pytest.approx(1.0, abs=1e-6)

    assert body["disclaimer"]
    assert len(body["top_scorelines"]) == 6


def test_prediction_includes_the_market_comparison(client, seeded_db):
    match_id = seeded_db["upcoming_id"]

    comparison = client.get(f"/api/matches/{match_id}/prediction").json()["market_comparison"]

    assert {item["selection"] for item in comparison} == {"OVER", "UNDER"}
    over = next(item for item in comparison if item["selection"] == "OVER")
    under = next(item for item in comparison if item["selection"] == "UNDER")
    # Removing the margin makes the two fair probabilities add to one.
    assert over["fair_market_probability"] + under["fair_market_probability"] == pytest.approx(1.0)
    assert over["edge"] == pytest.approx(over["model_probability"] - over["fair_market_probability"])


def test_prediction_for_an_unknown_match_is_404(client, seeded_db):
    assert client.get("/api/matches/9999/prediction").status_code == 404


def test_refresh_prediction_stores_a_row(client, seeded_db):
    match_id = seeded_db["upcoming_id"]

    assert client.get("/api/health").json()["predictions"] == 0

    response = client.post(f"/api/matches/{match_id}/refresh-prediction", json={})
    assert response.status_code == 201
    assert response.json()["created_at"] is not None

    assert client.get("/api/health").json()["predictions"] == 1


def test_refresh_prediction_honours_custom_lines(client, seeded_db):
    match_id = seeded_db["upcoming_id"]

    body = client.post(
        f"/api/matches/{match_id}/refresh-prediction",
        json={"lines": [0.5, 2.5], "last_n": 10, "rho": 0.0},
    ).json()

    assert {line["line"] for line in body["lines"]} == {0.5, 2.5}


def test_history_is_empty_before_any_prediction(client, seeded_db):
    body = client.get("/api/predictions/history").json()

    assert body["total"] == 0
    assert body["accuracy"] == 0.0


def test_history_scores_predictions_against_real_results(client, seeded_db, db_session):
    from app.models import Match

    finished = db_session.query(Match).filter(Match.home_goals.is_not(None)).limit(5).all()
    for match in finished:
        assert client.post(f"/api/matches/{match.id}/refresh-prediction", json={}).status_code == 201

    body = client.get("/api/predictions/history").json()

    assert body["total"] == 5
    assert 0.0 <= body["accuracy"] <= 1.0
    assert body["brier_score"] >= 0.0
    assert body["mean_absolute_goal_error"] >= 0.0
    for item in body["items"]:
        assert item["model_pick"] in {"OVER", "UNDER", "NEUTRAL"}
        assert item["actual_total_goals"] == item["actual_home_goals"] + item["actual_away_goals"]
