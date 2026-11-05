import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.collect import ingest_text, collect_new
from app.main import create_app


def test_ingest_text_creates_article(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = ingest_text(conn, "Pasted", "world " * 500, "manual")
    assert conn.execute("SELECT title FROM articles WHERE id=?", (aid,)).fetchone()["title"] == "Pasted"


def test_ingest_rejects_empty_text(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    with pytest.raises(ValueError):
        ingest_text(conn, "Empty", "   ", "manual")


def test_health_reports_missing_model(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    monkeypatch.setattr("app.main.shutil.which", lambda name: None)
    r = TestClient(create_app(db)).get("/api/health")
    assert r.json()["claude_available"] is False


FEED = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Essay</title><link>https://aeon.co/essays/one</link></item>
<item><title>Video</title><link>https://aeon.co/videos/two</link></item>
</channel></rss>"""


def test_collect_new_filters_links_by_source_pattern(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO sources(name, feed_url, topic, link_pattern, enabled) "
                 "VALUES('Aeon', 'https://feed', 'humanities', '/essays/', 1)")
    conn.commit()
    monkeypatch.setattr("app.collect.fetch_bytes",
                        lambda url, timeout=30: FEED if url == "https://feed"
                        else ("<html><body><p>" + "word " * 500 + "</p></body></html>").encode())
    collect_new(conn)
    rows = conn.execute("SELECT url FROM articles").fetchall()
    assert [r["url"] for r in rows] == ["https://aeon.co/essays/one"]


def test_ingest_endpoint_accepts_pasted_text(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    c = TestClient(create_app(db))
    r = c.post("/api/articles/ingest", json={"title": "Pasted", "text": "world " * 500})
    assert r.status_code == 200
    assert r.json()["article_id"] > 0
    assert c.post("/api/articles/ingest", json={}).status_code == 400


def test_analyze_pending_retries_stuck_running(tmp_path, monkeypatch):
    from app.analyze import analyze_article
    from app.collect import analyze_pending
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','short text','pending')")
    conn.execute("INSERT INTO analysis(article_id,status) VALUES(1,'running')")
    conn.commit()
    monkeypatch.setattr("app.collect.analyze_article",
                        lambda c, i, runner=None: c.execute(
                            "UPDATE analysis SET status='ready' WHERE article_id=?", (i,)))
    assert analyze_pending(conn) == 1
    assert conn.execute("SELECT status FROM analysis WHERE article_id=1").fetchone()["status"] == "ready"


def test_ingest_endpoint_accepts_pdf_path(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    monkeypatch.setattr("app.main.ingest_pdf", lambda conn, path, topic="manual": 7)
    c = TestClient(create_app(db))
    r = c.post("/api/articles/ingest", json={"pdf_path": "C:/tmp/x.pdf"})
    assert r.json() == {"article_id": 7}


def test_collect_skips_known_urls_before_downloading(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(url,title,text) VALUES('https://aeon.co/essays/one','Old','word ' * 500)")
    conn.execute("INSERT INTO sources(name, feed_url, topic, link_pattern, enabled) "
                 "VALUES('Aeon', 'https://feed', 'humanities', '/essays/', 1)")
    conn.commit()
    fetched = []

    def fake_fetch(url, timeout=30):
        fetched.append(url)
        if url == "https://feed":
            return FEED
        return ("<html><body><p>" + "word " * 500 + "</p></body></html>").encode()

    monkeypatch.setattr("app.collect.fetch_bytes", fake_fetch)
    collect_new(conn)
    assert "https://aeon.co/essays/one" not in fetched
