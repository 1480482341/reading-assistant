import sqlite3

import feedparser
import trafilatura

MIN_WORDS = 400

DEFAULT_SOURCES = [
    ("Quanta Magazine", "https://www.quantamagazine.org/feed/", "tech", ""),
    ("JSTOR Daily", "https://daily.jstor.org/feed/", "history", ""),
    ("Aeon", "https://aeon.co/feed.rss", "humanities", "/essays/"),
]


def fetch_items(feed_xml: bytes) -> list[dict]:
    parsed = feedparser.parse(feed_xml)
    items = []
    for entry in parsed.entries:
        items.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "summary": entry.get("summary", ""),
        })
    return items


def extract_text(html: str) -> str:
    text = trafilatura.extract(html, include_comments=False, include_tables=False)
    return text or ""


def ingest_article(conn: sqlite3.Connection, url: str, title: str, source: str,
                   topic: str, html: str, published_at: str) -> int | None:
    existing = conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()
    if existing:
        return existing["id"]

    text = extract_text(html)
    words = len(text.split())
    if words < MIN_WORDS:
        return None

    row = conn.execute(
        "INSERT INTO articles(url, title, source, topic, published_at, raw_html, text, "
        "word_count, status) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending') RETURNING id",
        (url, title, source, topic, published_at, html, text, words),
    ).fetchone()
    conn.commit()
    return row["id"]


TOPIC_ORDER = ["tech", "history", "humanities"]


def pick_today(conn: sqlite3.Connection, limit: int = 5) -> list[dict]:
    picks: list[dict] = []
    seen: set[int] = set()
    while len(picks) < limit:
        progressed = False
        for topic in TOPIC_ORDER:
            if len(picks) >= limit:
                break
            rows = conn.execute(
                "SELECT id, title, topic, status FROM articles "
                "WHERE topic = ? AND status IN ('ready', 'pending') "
                "ORDER BY published_at DESC, id DESC",
                (topic,),
            ).fetchall()
            for row in rows:
                if row["id"] not in seen:
                    seen.add(row["id"])
                    picks.append(dict(row))
                    progressed = True
                    break
        if not progressed:
            break
    return picks


def seed_sources(conn: sqlite3.Connection) -> None:
    for name, feed_url, topic, link_pattern in DEFAULT_SOURCES:
        conn.execute(
            "INSERT INTO sources(name, feed_url, topic, link_pattern, enabled) "
            "VALUES(?, ?, ?, ?, 1) ON CONFLICT(feed_url) DO NOTHING",
            (name, feed_url, topic, link_pattern),
        )
    conn.commit()
