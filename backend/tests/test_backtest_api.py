"""The walk-forward backtest over HTTP."""

from __future__ import annotations

import pytest


def test_backtest_returns_a_summary(client, seeded_db):
    response = client.get("/api/predictions/backtest", params={"min_train_matches": 20})

    assert response.status_code == 200
    body = response.json()

    # 32 finished matches in the fixture, 20 used to warm up.
    assert body["tested"] == 12
    assert body["scored"] <= body["tested"]
    assert 0.0 <= body["accuracy"] <= 1.0
    assert body["mean_absolute_goal_error"] >= 0
    assert body["rmse_goals"] >= 0
    assert body["disclaimer"]


def test_backtest_scores_the_baselines(client, seeded_db):
    body = client.get(
        "/api/predictions/backtest", params={"min_train_matches": 20}
    ).json()

    names = [card["name"] for card in body["scorecards"]]
    assert len(names) == 4
    for card in body["scorecards"]:
        assert card["brier"] >= 0
        assert card["log_loss"] >= 0
        assert card["samples"] == body["tested"]


def test_records_are_omitted_unless_requested(client, seeded_db):
    without = client.get(
        "/api/predictions/backtest", params={"min_train_matches": 20}
    ).json()
    with_records = client.get(
        "/api/predictions/backtest",
        params={"min_train_matches": 20, "include_records": True},
    ).json()

    assert without["records"] == []
    assert len(with_records["records"]) == with_records["tested"]

    record = with_records["records"][0]
    assert record["model_pick"] in {"OVER", "UNDER", "NEUTRAL"}
    assert record["actual_total_goals"] == (
        record["actual_home_goals"] + record["actual_away_goals"]
    )
    # The training set can never include the match being predicted.
    assert record["train_size"] == 20


def test_rolling_window_is_accepted(client, seeded_db):
    body = client.get(
        "/api/predictions/backtest",
        params={
            "min_train_matches": 20,
            "window": "rolling",
            "train_window": 15,
            "include_records": True,
        },
    ).json()

    assert {record["train_size"] for record in body["records"]} == {15}


def test_rolling_without_a_window_is_rejected(client, seeded_db):
    response = client.get(
        "/api/predictions/backtest",
        params={"min_train_matches": 20, "window": "rolling"},
    )

    assert response.status_code == 422


def test_too_little_history_returns_409(client, seeded_db):
    response = client.get(
        "/api/predictions/backtest", params={"min_train_matches": 500}
    )

    assert response.status_code == 409
    assert "backtest" in response.json()["detail"]


def test_backtest_is_deterministic(client, seeded_db):
    first = client.get("/api/predictions/backtest", params={"min_train_matches": 20}).json()
    second = client.get("/api/predictions/backtest", params={"min_train_matches": 20}).json()

    assert first["accuracy"] == pytest.approx(second["accuracy"])
    assert first["scorecards"][0]["brier"] == pytest.approx(second["scorecards"][0]["brier"])
