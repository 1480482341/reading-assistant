from pathlib import Path

from app.db import init_db
from app.sources import extract_text, fetch_items, ingest_article

FIX = Path(__file__).parent / "fixtures"


def test_parses_rss_items():
    items = fetch_items((FIX / "sample.rss").read_bytes())
    assert len(items) == 2
    assert items[0]["title"]


def test_extracts_body_without_navigation():
    text = extract_text((FIX / "sample_article.html").read_text(encoding="utf-8"))
    assert "algorithmic trading" in text
    assert "Subscribe" not in text


def test_short_extraction_is_rejected(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert ingest_article(conn, "u1", "t", "s", "tech", "<html><body>hi</body></html>", "") is None


def test_rfc_date_is_normalized_on_ingest(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    html = (FIX / "sample_article.html").read_text(encoding="utf-8")
    article_id = ingest_article(conn, "u3", "t", "s", "tech", html,
                                "Wed, 04 Nov 2026 15:32:52 +0000")
    row = conn.execute("SELECT published_at FROM articles WHERE id = ?",
                       (article_id,)).fetchone()
    assert row["published_at"] == "2026-11-04"


def test_same_url_is_not_duplicated(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    html = (FIX / "sample_article.html").read_text(encoding="utf-8")
    a = ingest_article(conn, "u2", "t", "s", "tech", html, "")
    b = ingest_article(conn, "u2", "t", "s", "tech", html, "")
    assert a is not None
    assert a == b
