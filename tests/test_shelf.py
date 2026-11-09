from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app
from app.shelf import (add_to_shelf, history_rows, in_shelf, record_open,
                       remove_from_shelf)

NOW = "2026-11-06T10:00:00"


def _conn(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','One','body','ready')")
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(2,'u2','Two','body','read')")
    conn.commit()
    return conn


def test_add_to_shelf_is_idempotent(tmp_path):
    conn = _conn(tmp_path)
    add_to_shelf(conn, 1, NOW)
    add_to_shelf(conn, 1, NOW)
    assert conn.execute("SELECT COUNT(*) AS c FROM shelf").fetchone()["c"] == 1
    assert in_shelf(conn, 1) is True


def test_remove_from_shelf(tmp_path):
    conn = _conn(tmp_path)
    add_to_shelf(conn, 1, NOW)
    assert remove_from_shelf(conn, 1) is True
    assert remove_from_shelf(conn, 1) is False
    assert in_shelf(conn, 1) is False


def test_record_open_counts_and_updates_last_opened(tmp_path):
    conn = _conn(tmp_path)
    record_open(conn, 1, "2026-11-01T09:00:00")
    record_open(conn, 1, "2026-11-02T09:00:00")
    row = conn.execute("SELECT * FROM reading_history WHERE article_id=1").fetchone()
    assert row["open_count"] == 2
    assert row["first_opened"] == "2026-11-01T09:00:00"
    assert row["last_opened"] == "2026-11-02T09:00:00"


def test_history_rows_include_counts_and_shelf_state(tmp_path):
    conn = _conn(tmp_path)
    add_to_shelf(conn, 1, NOW)
    record_open(conn, 1, NOW)
    conn.execute(
        "INSERT INTO annotations(article_id, para_index, start_offset, "
        "end_offset, quote, color) VALUES(1, 0, 0, 4, 'body', 'red')")
    conn.execute(
        "INSERT INTO bookmarks(article_id, para_index, offset_ratio, label) "
        "VALUES(1, 0, 0, 'mark')")
    conn.commit()

    row = history_rows(conn)[0]
    assert row["in_shelf"] is True
    assert row["annotation_count"] == 1
    assert row["bookmark_count"] == 1


def test_shelf_and_history_api(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','One','body','ready')")
    conn.commit()
    conn.close()
    c = TestClient(create_app(db))
    assert c.post("/api/shelf/1").status_code == 200
    shelf = c.get("/api/shelf").json()
    assert shelf[0]["id"] == 1 and shelf[0]["annotation_count"] == 0
    assert c.delete("/api/shelf/1").status_code == 200
    assert c.get("/api/shelf").json() == []

    assert c.post("/api/articles/1/open").status_code == 200
    hist = c.get("/api/history").json()
    assert hist[0]["id"] == 1 and hist[0]["open_count"] == 1


def test_shelf_unknown_article_returns_404(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    c = TestClient(create_app(db))
    assert c.post("/api/shelf/9").status_code == 404
