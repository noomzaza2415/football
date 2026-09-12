"""Tests for the Apps Script push.

The awkward parts of talking to an Apps Script web app are all covered here,
because each one produces a confusing failure in practice: it answers 200 even
when it refuses, it redirects to another host to deliver the body, and a
deployment that is not open to Anyone returns a sign-in page in HTML rather than
an error status.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest

from scripts import push_to_sheets


class Reply:
    def __init__(self, body: str, status_code: int = 200) -> None:
        self.text = body
        self.status_code = status_code

    def json(self):
        return json.loads(self.text)


class _BorrowedSession:
    """Hand ``main`` the test session without letting it close it.

    ``main`` opens its own ``with SessionLocal() as db``, which would otherwise
    use the module-level engine and find no tables.
    """

    def __init__(self, session) -> None:
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc_info) -> bool:
        return False


@pytest.fixture
def command_db(monkeypatch, db_session):
    """Make the command read the same database the fixtures populate."""
    monkeypatch.setattr(
        push_to_sheets, "SessionLocal", lambda: _BorrowedSession(db_session)
    )
    return db_session


# --------------------------------------------------------------------------- #
# Value conversion
# --------------------------------------------------------------------------- #
def test_none_becomes_an_empty_cell():
    assert push_to_sheets.json_safe(None) == ""


def test_timestamps_become_iso_text():
    assert push_to_sheets.json_safe(date(2026, 9, 12)) == "2026-09-12"
    assert push_to_sheets.json_safe(
        datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc)
    ).startswith("2026-09-12T15:00:00")


def test_plain_values_pass_through():
    assert push_to_sheets.json_safe(3) == 3
    assert push_to_sheets.json_safe(2.5) == 2.5
    assert push_to_sheets.json_safe("OVER") == "OVER"
    assert push_to_sheets.json_safe(True) is True


def test_anything_else_is_stringified():
    class Odd:
        def __str__(self) -> str:
            return "odd"

    assert push_to_sheets.json_safe(Odd()) == "odd"


# --------------------------------------------------------------------------- #
# Building the payload
# --------------------------------------------------------------------------- #
def test_payload_tables_carry_a_header_and_rows(db_session, seeded_db):
    tables = push_to_sheets.build_payload_tables(
        db_session, ["matches"], league=None, min_train=20
    )

    assert len(tables) == 1
    table = tables[0]
    assert table["name"] == "matches"
    assert table["header"][0] == "match_id"
    assert len(table["rows"]) == 33
    # Every row must be the header's width, or Sheets rejects the range.
    assert all(len(row) == len(table["header"]) for row in table["rows"])


def test_payload_is_json_serialisable(db_session, seeded_db):
    tables = push_to_sheets.build_payload_tables(
        db_session, ["matches", "team_stats"], league=None, min_train=20
    )

    # This is the whole point of json_safe; a date left in place would raise.
    json.dumps({"token": "x", "tables": tables})


def test_a_table_that_cannot_be_built_is_skipped(db_session, seeded_db, caplog):
    tables = push_to_sheets.build_payload_tables(
        db_session, ["backtest", "matches"], league=None, min_train=5000
    )

    names = [table["name"] for table in tables]
    assert "backtest" not in names  # not enough history
    assert "matches" in names


# --------------------------------------------------------------------------- #
# Talking to the web app
# --------------------------------------------------------------------------- #
def test_a_successful_post_returns_the_parsed_reply(monkeypatch):
    sent = {}

    def fake_post(url, content=None, headers=None, timeout=None, follow_redirects=None):
        sent["url"] = url
        sent["body"] = json.loads(content)
        sent["follow_redirects"] = follow_redirects
        return Reply('{"ok": true, "written": [{"name": "matches", "rows": 3}]}')

    monkeypatch.setattr(push_to_sheets.httpx, "post", fake_post)

    reply = push_to_sheets.post("https://script.google.com/x/exec", {"token": "t"})

    assert reply["ok"] is True
    assert sent["body"]["token"] == "t"
    # Apps Script redirects to another host to deliver the body.
    assert sent["follow_redirects"] is True


def test_an_html_reply_explains_the_access_setting(monkeypatch):
    monkeypatch.setattr(
        push_to_sheets.httpx,
        "post",
        lambda *a, **k: Reply("<!DOCTYPE html><html>Sign in</html>"),
    )

    with pytest.raises(SystemExit) as exit_info:
        push_to_sheets.post("https://script.google.com/x/exec", {})

    assert "Anyone" in str(exit_info.value)


def test_a_transport_failure_is_reported(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(push_to_sheets.httpx, "post", boom)

    with pytest.raises(SystemExit):
        push_to_sheets.post("https://script.google.com/x/exec", {})


def test_an_error_status_is_reported(monkeypatch):
    monkeypatch.setattr(
        push_to_sheets.httpx, "post", lambda *a, **k: Reply("nope", status_code=403)
    )

    with pytest.raises(SystemExit) as exit_info:
        push_to_sheets.post("https://script.google.com/x/exec", {})

    assert "403" in str(exit_info.value)


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #
def test_dry_run_sends_nothing(monkeypatch, command_db, seeded_db):
    def must_not_be_called(*args, **kwargs):
        raise AssertionError("dry run must not send a request")

    monkeypatch.setattr(push_to_sheets.httpx, "post", must_not_be_called)

    assert push_to_sheets.main(["--dry-run", "--tables", "matches"]) == 0


def test_without_configuration_the_command_refuses(monkeypatch, command_db, seeded_db):
    monkeypatch.setattr(
        push_to_sheets.httpx,
        "post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not send")),
    )

    settings = push_to_sheets.get_settings()
    monkeypatch.setattr(settings, "google_apps_script_url", None)
    monkeypatch.setattr(settings, "google_apps_script_token", None)

    assert push_to_sheets.main(["--tables", "matches"]) == 2


def test_a_refusal_is_surfaced_with_the_token_hint(monkeypatch, command_db, seeded_db, caplog):
    monkeypatch.setattr(
        push_to_sheets.httpx,
        "post",
        lambda *a, **k: Reply('{"ok": false, "error": "unauthorised"}'),
    )

    settings = push_to_sheets.get_settings()
    monkeypatch.setattr(settings, "google_apps_script_url", "https://example.com/exec")
    monkeypatch.setattr(settings, "google_apps_script_token", "wrong")

    with caplog.at_level("ERROR"):
        assert push_to_sheets.main(["--tables", "matches"]) == 1

    assert "GOOGLE_APPS_SCRIPT_TOKEN" in caplog.text


def test_a_successful_push_reports_each_tab(monkeypatch, command_db, seeded_db, caplog):
    monkeypatch.setattr(
        push_to_sheets.httpx,
        "post",
        lambda *a, **k: Reply('{"ok": true, "written": [{"name": "matches", "rows": 33}]}'),
    )

    settings = push_to_sheets.get_settings()
    monkeypatch.setattr(settings, "google_apps_script_url", "https://example.com/exec")
    monkeypatch.setattr(settings, "google_apps_script_token", "right")

    with caplog.at_level("INFO"):
        assert push_to_sheets.main(["--tables", "matches"]) == 0

    assert "matches" in caplog.text


def test_ping_reports_the_spreadsheet(monkeypatch, caplog):
    monkeypatch.setattr(
        push_to_sheets.httpx,
        "get",
        lambda *a, **k: Reply('{"ok": true, "spreadsheet": "OU", "tabs": ["matches"]}'),
    )

    with caplog.at_level("INFO"):
        assert push_to_sheets.main(["--ping", "--url", "https://example.com/exec"]) == 0

    assert "OU" in caplog.text


def test_ping_explains_an_html_reply(monkeypatch, caplog):
    class Html:
        status_code = 200
        text = "<html></html>"

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(push_to_sheets.httpx, "get", lambda *a, **k: Html())

    with caplog.at_level("ERROR"):
        assert push_to_sheets.main(["--ping", "--url", "https://example.com/exec"]) == 1

    assert "Anyone" in caplog.text
