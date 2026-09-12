"""Tests for the news reader and the exports.

The feeds are never fetched here: every test feeds a recorded document to the
parser. A unit test that depends on a live news site fails for reasons that
have nothing to do with this code.
"""

from __future__ import annotations

from datetime import timezone

import httpx
import pytest

from app.pipeline import news as news_lib

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Football</title>
    <item>
      <title>Liverpool beat Fulham in five-goal thriller</title>
      <link>https://example.com/a</link>
      <description>&lt;p&gt;A &lt;b&gt;chaotic&lt;/b&gt; night at Anfield.&lt;/p&gt;</description>
      <pubDate>Sat, 12 Sep 2026 20:30:00 GMT</pubDate>
    </item>
    <item>
      <title>Manchester United striker ruled out for a month</title>
      <link>https://example.com/b</link>
      <description>Injury news ahead of the weekend.</description>
      <pubDate>Sat, 12 Sep 2026 08:00:00 GMT</pubDate>
    </item>
    <item>
      <title>No link here so this one is skipped</title>
      <pubDate>Sat, 12 Sep 2026 07:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Football</title>
  <entry>
    <title>Arsenal held at home</title>
    <link href="https://example.com/atom-1"/>
    <summary>Points dropped in north London.</summary>
    <updated>2026-09-12T18:00:00Z</updated>
  </entry>
</feed>
"""

SOURCE = news_lib.SOURCES[0]


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def test_rss_items_are_parsed():
    items = news_lib.parse_feed(SOURCE, RSS)

    assert len(items) == 2  # the item with no link is dropped
    first = items[0]
    assert first.title.startswith("Liverpool beat Fulham")
    assert first.url == "https://example.com/a"
    assert first.source == SOURCE.name
    assert first.published_at.tzinfo is not None


def test_markup_is_stripped_from_summaries():
    summary = news_lib.parse_feed(SOURCE, RSS)[0].summary

    assert "<b>" not in summary
    assert "chaotic" in summary


def test_atom_entries_are_parsed():
    items = news_lib.parse_feed(SOURCE, ATOM)

    assert len(items) == 1
    assert items[0].url == "https://example.com/atom-1"
    assert items[0].title == "Arsenal held at home"
    assert items[0].published_at.astimezone(timezone.utc).hour == 18


def test_a_malformed_feed_yields_nothing():
    assert news_lib.parse_feed(SOURCE, b"this is not xml") == []


def test_dates_that_cannot_be_parsed_become_none():
    assert news_lib._parse_date("not a date") is None
    assert news_lib._parse_date(None) is None
    assert news_lib._parse_date("2026-09-12T18:00:00Z") is not None


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def test_a_failing_feed_returns_nothing_rather_than_raising(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("dns failure")

    monkeypatch.setattr("app.pipeline.news.httpx.get", boom)

    assert news_lib.fetch_source(SOURCE) == []


def test_an_error_status_returns_nothing(monkeypatch):
    class Response:
        status_code = 503
        content = b""

    monkeypatch.setattr(
        "app.pipeline.news.httpx.get", lambda *a, **k: Response()
    )

    assert news_lib.fetch_source(SOURCE) == []


def test_fetch_news_sorts_newest_first(monkeypatch):
    class Response:
        status_code = 200
        content = RSS

    monkeypatch.setattr("app.pipeline.news.httpx.get", lambda *a, **k: Response())

    items = news_lib.fetch_news(keys=[SOURCE.key], limit=10)

    assert len(items) == 2
    assert items[0].published_at > items[1].published_at


def test_football_keywords_match_football_coverage():
    football = news_lib.NewsItem(
        source="x",
        source_key="x",
        language="th",
        scope="Thailand",
        title="ลิเวอร์พูลบุกชนะในศึกพรีเมียร์ลีก",
        url="https://example.com/1",
        summary=None,
        published_at=None,
    )
    volleyball = news_lib.NewsItem(
        source="x",
        source_key="x",
        language="th",
        scope="Thailand",
        title="วอลเลย์บอลสาวไทยคว้าชัย",
        url="https://example.com/2",
        summary=None,
        published_at=None,
    )

    assert news_lib.is_football(football)
    assert not news_lib.is_football(volleyball)


def test_combined_sport_feeds_are_filtered(monkeypatch):
    """A general sport feed must not push other sports into a football app."""
    # A bytes literal cannot hold Thai, so build it from text.
    mixed = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
        <item><title>ศึกพรีเมียร์ลีกนัดสำคัญ</title><link>https://example.com/f</link></item>
        <item><title>มวยไทยศึกใหญ่สุดสัปดาห์</title><link>https://example.com/m</link></item>
        </channel></rss>""".encode("utf-8")

    class Response:
        status_code = 200
        content = mixed

    monkeypatch.setattr("app.pipeline.news.httpx.get", lambda *a, **k: Response())

    sport_feed = next(s for s in news_lib.SOURCES if s.topic == "sport")
    items = news_lib.fetch_news(keys=[sport_feed.key], limit=10)

    assert len(items) == 1
    assert "พรีเมียร์ลีก" in items[0].title


def test_every_source_declares_a_known_topic():
    assert {source.topic for source in news_lib.SOURCES} <= {"football", "sport"}


def test_language_filter_selects_feeds(monkeypatch):
    class Response:
        status_code = 200
        content = RSS

    monkeypatch.setattr("app.pipeline.news.httpx.get", lambda *a, **k: Response())

    thai = news_lib.fetch_news(language="th", limit=50)
    english = news_lib.fetch_news(language="en", limit=50)

    thai_feeds = [s for s in news_lib.SOURCES if s.language == "th"]
    # Both fixture items read as football, so none are filtered out.
    assert len(thai) == 2 * len(thai_feeds)
    assert len(english) > 0
    assert all(item.language == "th" for item in thai)


# --------------------------------------------------------------------------- #
# Matching a fixture to headlines
# --------------------------------------------------------------------------- #
def test_search_terms_expand_the_data_feed_spelling():
    terms = news_lib.team_search_terms("Man United")

    assert "Manchester United" in terms
    assert "Man United" in terms


def test_search_terms_drop_the_apostrophe():
    terms = news_lib.team_search_terms("Nott'm Forest")

    assert "Nottingham Forest" in terms


def test_search_terms_keep_the_distinctive_word():
    assert "Bournemouth" in news_lib.team_search_terms("Bournemouth")


def test_items_match_on_either_team(monkeypatch):
    class Response:
        status_code = 200
        content = RSS

    monkeypatch.setattr("app.pipeline.news.httpx.get", lambda *a, **k: Response())

    items = news_lib.news_for_match("Liverpool", "Fulham", limit=5)

    assert len(items) >= 1
    assert any("Liverpool" in item.title for item in items)


def test_an_unrelated_fixture_matches_nothing(monkeypatch):
    class Response:
        status_code = 200
        content = RSS

    monkeypatch.setattr("app.pipeline.news.httpx.get", lambda *a, **k: Response())

    assert news_lib.news_for_match("Oakmoor Rangers", "Greyfield Park") == []


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
def test_sources_endpoint_lists_both_languages(client):
    sources = client.get("/api/news/sources").json()

    languages = {source["language"] for source in sources}
    assert {"th", "en"} <= languages
    assert all(source["url"].startswith("http") for source in sources)


def test_news_endpoint_carries_the_not_model_input_note(client, monkeypatch):
    class Response:
        status_code = 200
        content = RSS

    monkeypatch.setattr("app.pipeline.news.httpx.get", lambda *a, **k: Response())

    body = client.get("/api/news", params={"limit": 5}).json()

    assert "โมเดล" in body["note"]
    assert len(body["items"]) <= 5


def test_an_unknown_source_is_rejected(client):
    response = client.get("/api/news", params={"source": "not-a-feed"})

    assert response.status_code == 422


def test_news_for_an_unknown_match_is_404(client, seeded_db):
    assert client.get("/api/news/match/999999").status_code == 404
