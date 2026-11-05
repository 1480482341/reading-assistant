from pathlib import Path

from app.db import init_db
from app.sources import fetch_items, extract_text, ingest_article

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


def test_same_url_is_not_duplicated(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    html = (FIX / "sample_article.html").read_text(encoding="utf-8")
    a = ingest_article(conn, "u2", "t", "s", "tech", html, "")
    b = ingest_article(conn, "u2", "t", "s", "tech", html, "")
    assert a == b
