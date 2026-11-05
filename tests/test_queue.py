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
