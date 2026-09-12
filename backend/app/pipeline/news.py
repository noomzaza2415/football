"""Football news headlines from public RSS feeds.

Why RSS and not scraping
------------------------
RSS and Atom feeds are published by these sites specifically to be read by
other software. Scraping their HTML is brittle, generally against their terms,
and breaks every time a page is redesigned. Everything here reads a declared
feed and nothing else.

Why this does not feed the model
-------------------------------
The Poisson model consumes goals. There is no defined path from a sentence like
"the striker is a doubt" to a change in expected goals, and inventing one would
produce numbers nobody could check. The walk-forward backtest already shows the
model has no edge over a league average; adding an unvalidated adjustment on
top would make it worse and, worse still, unmeasurable.

So headlines are shown as **context for the person reading the page**, next to
the model output and clearly separated from it. If injuries are to reach the
model, the route is structured injury data plus an adjustment whose value is
demonstrated by the backtest, not free text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10.0
MAX_ITEMS_PER_FEED = 25
MAX_SUMMARY_CHARS = 400

ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass(frozen=True)
class NewsSource:
    """One publisher's feed.

    ``topic`` matters: several Thai publishers only offer a combined sport feed,
    so boxing and volleyball arrive alongside football. Items from those feeds
    are filtered by keyword, which a football-only feed does not need.
    """

    key: str
    name: str
    url: str
    language: str
    scope: str  # "world" or a country name
    topic: str = "football"  # "football" or "sport"


#: Public feeds, each declared by its publisher. Thai and international mixed,
#: because a Thai reader wants both. Every URL here was checked to return 200,
#: parse as XML and contain items; guessed feed addresses tend to 404.
SOURCES: tuple[NewsSource, ...] = (
    NewsSource(
        key="bbc",
        name="BBC Sport Football",
        url="https://feeds.bbci.co.uk/sport/football/rss.xml",
        language="en",
        scope="world",
    ),
    NewsSource(
        key="skysports",
        name="Sky Sports Football",
        url="https://www.skysports.com/rss/11095",
        language="en",
        scope="world",
    ),
    NewsSource(
        key="guardian",
        name="The Guardian Football",
        url="https://www.theguardian.com/football/rss",
        language="en",
        scope="world",
    ),
    NewsSource(
        key="thairath",
        name="ไทยรัฐ กีฬา",
        url="https://www.thairath.co.th/rss/sport",
        language="th",
        scope="Thailand",
        topic="sport",
    ),
    NewsSource(
        key="khaosod",
        name="ข่าวสด กีฬา",
        url="https://www.khaosod.co.th/sports/feed",
        language="th",
        scope="Thailand",
        topic="sport",
    ),
    NewsSource(
        key="matichon",
        name="มติชน กีฬา",
        url="https://www.matichon.co.th/sport/feed",
        language="th",
        scope="Thailand",
        topic="sport",
    ),
    NewsSource(
        key="bangkokpost",
        name="Bangkok Post Sports",
        url="https://www.bangkokpost.com/rss/data/sports.xml",
        language="en",
        scope="Thailand",
        topic="sport",
    ),
)

#: Words that mark an item as football, for the combined sport feeds. Kept to
#: terms distinctive enough not to fire on other sports: "ลีก" and "league"
#: appear in football coverage constantly and rarely elsewhere in these feeds.
FOOTBALL_KEYWORDS: tuple[str, ...] = (
    "ฟุตบอล",
    "พรีเมียร์ลีก",
    "ลาลีกา",
    "กัลโช่",
    "เซเรีย",
    "บุนเดสลีกา",
    "ลีกเอิง",
    "ยูฟ่า",
    "แชมเปียนส์ลีก",
    "ยูโรปาลีก",
    "ไทยลีก",
    "เอฟเอคัพ",
    "กองหน้า",
    "กองกลาง",
    "กองหลัง",
    "ผู้รักษาประตู",
    "ยิงประตู",
    "แข้ง",
    "football",
    "soccer",
    "premier league",
    "la liga",
    "serie a",
    "bundesliga",
    "ligue 1",
    "champions league",
    "europa league",
    "striker",
    "midfielder",
    "goalkeeper",
    "five-goal",
    "goal",
)


def is_football(item: "NewsItem") -> bool:
    """Whether a combined sport item looks like football coverage."""
    return item.mentions(list(FOOTBALL_KEYWORDS))


SOURCES_BY_KEY = {source.key: source for source in SOURCES}


@dataclass(frozen=True)
class NewsItem:
    """One headline, normalised across RSS and Atom."""

    source: str
    source_key: str
    language: str
    scope: str
    title: str
    url: str
    summary: str | None
    published_at: datetime | None

    def mentions(self, terms: list[str]) -> bool:
        """Whether any of ``terms`` appears in the title or summary."""
        haystack = f"{self.title} {self.summary or ''}".lower()
        return any(term.lower() in haystack for term in terms if term)


def _strip_html(text: str | None) -> str | None:
    """Feed summaries carry markup and entities; the UI wants neither."""
    if not text:
        return None
    without_tags = re.sub(r"<[^>]+>", " ", text)
    collapsed = re.sub(r"\s+", " ", without_tags).strip()
    if not collapsed:
        return None
    return collapsed[:MAX_SUMMARY_CHARS]


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _text(element, *names: str) -> str | None:
    for name in names:
        found = element.find(name)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return None


def parse_feed(source: NewsSource, body: bytes) -> list[NewsItem]:
    """Turn one feed document into items. Handles both RSS and Atom."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        logger.warning("%s: malformed feed (%s)", source.key, exc)
        return []

    entries = root.findall(".//item") or root.findall(f".//{ATOM}entry")
    items: list[NewsItem] = []

    for entry in entries[:MAX_ITEMS_PER_FEED]:
        title = _text(entry, "title", f"{ATOM}title")
        if not title:
            continue

        url = _text(entry, "link", "guid")
        if not url:
            # Atom puts the address in an attribute rather than the text.
            link = entry.find(f"{ATOM}link")
            url = link.get("href") if link is not None else None
        if not url or not url.startswith("http"):
            continue

        items.append(
            NewsItem(
                source=source.name,
                source_key=source.key,
                language=source.language,
                scope=source.scope,
                title=_strip_html(title) or title,
                url=url,
                summary=_strip_html(
                    _text(entry, "description", f"{ATOM}summary", f"{ATOM}content")
                ),
                published_at=_parse_date(
                    _text(entry, "pubDate", f"{ATOM}updated", f"{ATOM}published")
                ),
            )
        )

    return items


def fetch_source(source: NewsSource, *, timeout: float = REQUEST_TIMEOUT) -> list[NewsItem]:
    """One feed. A failure returns nothing rather than raising.

    A news panel is decoration around the analysis. One publisher being down
    must never take a match page with it.
    """
    try:
        response = httpx.get(
            source.url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "football-ou-analytics/1.0 (+RSS reader)"},
        )
    except httpx.HTTPError as exc:
        logger.warning("%s: request failed (%s)", source.key, exc)
        return []

    if response.status_code >= 400:
        logger.warning("%s: returned %s", source.key, response.status_code)
        return []

    return parse_feed(source, response.content)


def fetch_news(
    *,
    keys: list[str] | None = None,
    language: str | None = None,
    limit: int = 30,
) -> list[NewsItem]:
    """Headlines from several feeds, newest first."""
    selected = [
        source
        for source in SOURCES
        if (not keys or source.key in keys) and (not language or source.language == language)
    ]

    items: list[NewsItem] = []
    for source in selected:
        fetched = fetch_source(source)
        if source.topic == "sport":
            # A combined sport feed carries every sport; keep the football.
            fetched = [item for item in fetched if is_football(item)]
        items.extend(fetched)

    # Undated items sort last rather than crashing the comparison.
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    items.sort(key=lambda item: item.published_at or oldest, reverse=True)
    return items[:limit]


def team_search_terms(name: str) -> list[str]:
    """Search terms for a team, because feeds rarely use the data feed's spelling.

    football-data.co.uk writes "Man United" and "Nott'm Forest"; a headline says
    "Manchester United" or "Nottingham Forest". Matching on the distinctive word
    catches both without hand-maintaining a mapping table.
    """
    cleaned = name.replace("'", "").strip()
    terms = {cleaned}

    expansions = {
        "Man United": ["Manchester United", "Man Utd"],
        "Man City": ["Manchester City"],
        "Nottm Forest": ["Nottingham Forest", "Forest"],
        "Sheffield United": ["Sheffield Utd"],
        "Wolves": ["Wolverhampton"],
        "Spurs": ["Tottenham"],
        "Newcastle": ["Newcastle United"],
        "West Ham": ["West Ham United"],
        "Leeds": ["Leeds United"],
    }
    terms.update(expansions.get(cleaned, []))

    # The longest word is usually the identifying one: "Bournemouth", "Brentford".
    words = [word for word in re.split(r"\s+", cleaned) if len(word) > 4]
    if words:
        terms.add(max(words, key=len))

    return sorted(terms)


def news_for_match(
    home_team: str, away_team: str, *, limit: int = 8, language: str | None = None
) -> list[NewsItem]:
    """Headlines that name either side of one fixture."""
    terms = team_search_terms(home_team) + team_search_terms(away_team)
    everything = fetch_news(language=language, limit=200)
    return [item for item in everything if item.mentions(terms)][:limit]
