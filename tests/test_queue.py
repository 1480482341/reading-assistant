from app.db import init_db
from app.sources import pick_today


def _seed(conn):
    for i, topic in enumerate(["tech", "tech", "history", "humanities", "history"]):
        conn.execute(
            "INSERT INTO articles(url,title,topic,text,status) VALUES(?,?,?,?,?)",
            (f"u{i}", f"t{i}", topic, "body", "ready"),
        )
    conn.commit()


def test_rotates_topics(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _seed(conn)
    topics = [a["topic"] for a in pick_today(conn, limit=3)]
    assert topics == ["tech", "history", "humanities"]


def test_skips_already_read(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _seed(conn)
    conn.execute(
        "UPDATE articles SET status='read' WHERE topic='history' "
        "AND id=(SELECT MIN(id) FROM articles WHERE topic='history')"
    )
    conn.commit()
    topics = [a["topic"] for a in pick_today(conn, limit=3)]
    assert "history" in topics and len(topics) == 3


def test_empty_library_returns_empty_list(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert pick_today(conn) == []


def test_pick_today_skips_finished_articles(tmp_path):
    from app.sources import pick_today
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,topic,text,status,published_at) "
                 "VALUES('a','Read','tech','t','read','2026-11-05')")
    conn.execute("INSERT INTO articles(url,title,topic,text,status,published_at) "
                 "VALUES('b','Fresh','tech','t','pending','2026-11-04')")
    conn.commit()
    assert [a["title"] for a in pick_today(conn)] == ["Fresh"]


def test_mark_read_endpoint_and_missing_article(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','text','pending')")
    conn.commit()
    conn.close()
    c = TestClient(create_app(db))
    assert c.post("/api/articles/1/read").status_code == 200
    assert c.post("/api/articles/99/read").status_code == 404
