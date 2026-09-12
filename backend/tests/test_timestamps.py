"""Every timestamp the API emits must carry a timezone.

SQLite cannot store a timestamp offset, so values read back from it are naive.
Serialising one of those without a suffix makes a browser parse it as local
time, which shifts every kick-off by the viewer's UTC offset: a 15:00 UTC match
rendered as 15:00 in Bangkok rather than 22:00. These tests are the guard
against that regressing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from app.schemas import _as_utc_iso

TIMESTAMP_KEYS = {
    "match_date",
    "created_at",
    "updated_at",
    "kickoff",
    "published_at",
    "server_time",
    "last_ingest_at",
    "latest_result_at",
    "next_kickoff_at",
    "earliest",
    "latest",
}


#: A trailing offset, as +07:00, -0500 or the Z that means UTC.
OFFSET = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def has_timezone(value: str) -> bool:
    """Whether an ISO string states its offset."""
    return OFFSET.search(value) is not None


def walk_timestamps(payload, path: str = ""):
    """Yield every (path, value) pair whose key names a timestamp."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            here = f"{path}.{key}" if path else key
            if key in TIMESTAMP_KEYS and isinstance(value, str):
                yield here, value
            else:
                yield from walk_timestamps(value, here)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            yield from walk_timestamps(item, f"{path}[{index}]")


# --------------------------------------------------------------------------- #
# The serialiser itself
# --------------------------------------------------------------------------- #
def test_a_naive_timestamp_is_treated_as_utc():
    assert _as_utc_iso(datetime(2026, 9, 12, 15, 0)) == "2026-09-12T15:00:00Z"


def test_an_aware_timestamp_is_converted_to_utc():
    from datetime import timedelta

    bangkok = timezone(timedelta(hours=7))
    assert (
        _as_utc_iso(datetime(2026, 9, 12, 22, 0, tzinfo=bangkok))
        == "2026-09-12T15:00:00Z"
    )


def test_a_utc_timestamp_survives_unchanged():
    assert (
        _as_utc_iso(datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc))
        == "2026-09-12T15:00:00Z"
    )


# --------------------------------------------------------------------------- #
# Across the API
# --------------------------------------------------------------------------- #
def test_the_helper_recognises_every_offset_spelling():
    assert has_timezone("2026-09-12T15:00:00Z")
    assert has_timezone("2026-09-12T22:00:00+07:00")
    assert has_timezone("2026-09-12T10:00:00-0500")
    assert not has_timezone("2026-09-12T15:00:00")
    assert not has_timezone("2026-09-12T15:00:00.123456")


@pytest.mark.parametrize(
    "path",
    [
        "/api/matches/day",
        "/api/matches/upcoming",
        "/api/matches/calendar",
    ],
)
def test_endpoints_emit_only_timezone_aware_timestamps(client, seeded_db, path):
    payload = client.get(path).json()

    found = list(walk_timestamps(payload))
    assert found, f"{path} returned no timestamps to check"
    for where, value in found:
        assert has_timezone(value), f"{path} {where} has no timezone: {value}"


def test_the_history_endpoint_is_aware(client, seeded_db, db_session):
    """History is empty until something is stored, so store one first."""
    from app.models import Match

    finished = db_session.query(Match).filter(Match.home_goals.is_not(None)).first()
    client.post(f"/api/matches/{finished.id}/refresh-prediction", json={})

    payload = client.get("/api/predictions/history").json()

    found = list(walk_timestamps(payload))
    assert found
    for where, value in found:
        assert has_timezone(value), f"{where} has no timezone: {value}"


def test_the_prediction_endpoint_is_aware(client, seeded_db):
    payload = client.get(
        f"/api/matches/{seeded_db['upcoming_id']}/prediction"
    ).json()

    for where, value in walk_timestamps(payload):
        assert has_timezone(value), f"{where} has no timezone: {value}"


def test_a_stored_prediction_reports_an_aware_created_at(client, seeded_db):
    body = client.post(
        f"/api/matches/{seeded_db['upcoming_id']}/refresh-prediction", json={}
    ).json()

    assert body["created_at"] is not None
    assert has_timezone(body["created_at"])


def test_the_kickoff_time_is_not_shifted(client, seeded_db, db_session):
    """The emitted instant must be the one stored, not one offset by a timezone."""
    from app.models import Match

    match = db_session.get(Match, seeded_db["upcoming_id"])
    emitted = client.get(f"/api/matches/{match.id}").json()["match_date"]

    stored = match.match_date
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)

    assert datetime.fromisoformat(emitted.replace("Z", "+00:00")) == stored
