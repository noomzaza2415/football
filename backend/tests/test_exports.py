"""Tests for the spreadsheet exports."""

from __future__ import annotations

import csv
import io

import pytest

from app import exporters


def _parse(body: str) -> tuple[list[str], list[list[str]]]:
    text = body.lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    return rows[0], rows[1:]


def test_every_table_has_a_builder():
    assert set(exporters.TABLES) == set(exporters.TABLE_OPTIONS)


def test_matches_table_covers_result_and_prices(db_session, seeded_db):
    header, rows = exporters.matches_table(db_session)

    assert "total_goals" in header
    assert "odds_over" in header
    assert len(rows) == 33  # 32 finished plus the one upcoming

    # Date and time are separate columns so a spreadsheet can sort on them.
    assert header.index("date") < header.index("time")


def test_matches_table_marks_the_over_under_result(db_session, seeded_db):
    header, rows = exporters.matches_table(db_session)
    index = {name: i for i, name in enumerate(header)}

    for row in rows:
        total = row[index["total_goals"]]
        result = row[index["result_2_5"]]
        if total == "":
            assert result == ""
        else:
            assert result == ("OVER" if int(total) > 2.5 else "UNDER")


def test_team_stats_table_is_empty_before_a_rebuild(db_session, seeded_db):
    _, rows = exporters.team_stats_table(db_session)

    assert rows == []


def test_team_stats_table_fills_after_a_rebuild(client, db_session, seeded_db):
    client.post("/api/teams/rebuild-stats")

    header, rows = exporters.team_stats_table(db_session)

    assert len(rows) == 4
    assert "attack_strength_home" in header


def test_predictions_table_pairs_the_forecast_with_the_result(
    client, db_session, seeded_db
):
    from app.models import Match

    finished = db_session.query(Match).filter(Match.home_goals.is_not(None)).first()
    client.post(f"/api/matches/{finished.id}/refresh-prediction", json={})

    header, rows = exporters.predictions_table(db_session)

    assert len(rows) == 1
    index = {name: i for i, name in enumerate(header)}
    assert rows[0][index["actual_result"]] in {"OVER", "UNDER"}
    assert float(rows[0][index["prob_over_2_5"]]) >= 0


def test_backtest_table_has_one_row_per_tested_match(db_session, seeded_db):
    header, rows = exporters.backtest_table(db_session, min_train_matches=20)

    assert len(rows) == 12
    assert "prob_over" in header
    assert "correct" in header


def test_build_table_ignores_options_a_table_does_not_take(db_session, seeded_db):
    # team_stats accepts nothing; passing a league must not raise.
    header, _ = exporters.build_table(db_session, "team_stats", league="Test League")

    assert header[0] == "team_id"


def test_build_table_rejects_an_unknown_name(db_session):
    with pytest.raises(KeyError):
        exporters.build_table(db_session, "nope")


def test_to_csv_quotes_awkward_values():
    body = exporters.to_csv(["a", "b"], [["has,comma", 'has"quote']])

    header, rows = _parse(body)
    assert header == ["a", "b"]
    assert rows[0] == ["has,comma", 'has"quote']


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
def test_export_index_lists_the_tables(client, seeded_db):
    body = client.get("/api/export").json()

    assert set(body["tables"]) == set(exporters.TABLES)
    assert all(path.endswith(".csv") for path in body["csv"])


def test_csv_endpoint_returns_a_download(client, seeded_db):
    response = client.get("/api/export/matches.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    # The BOM is what makes Excel and Sheets read it as UTF-8.
    assert response.text.startswith("﻿")

    header, rows = _parse(response.text)
    assert header[0] == "match_id"
    assert len(rows) == 33


def test_csv_endpoint_honours_the_league_filter(client, seeded_db):
    matching = client.get("/api/export/matches.csv", params={"league": "Test League"})
    other = client.get("/api/export/matches.csv", params={"league": "Nowhere"})

    assert len(_parse(matching.text)[1]) == 33
    assert _parse(other.text)[1] == []


def test_unknown_table_is_404(client, seeded_db):
    response = client.get("/api/export/nope.csv")

    assert response.status_code == 404
    assert "unknown table" in response.json()["detail"]


def test_backtest_csv_reports_too_little_history(client, seeded_db):
    response = client.get(
        "/api/export/backtest.csv", params={"min_train_matches": 5000}
    )

    assert response.status_code == 409
