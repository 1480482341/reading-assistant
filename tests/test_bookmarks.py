import pytest
from fastapi.testclient import TestClient

from app.bookmarks import add_bookmark, delete_bookmark, list_bookmarks
from app.db import init_db
from app.main import create_app

TEXT = "First paragraph here.\n\nSecond paragraph."


def _conn(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(id,url,title,text) VALUES(1,'u','t',?)", (TEXT,))
    conn.commit()
    return conn


def test_add_and_list_bookmarks_in_order(tmp_path):
    conn = _conn(tmp_path)
    first = add_bookmark(conn, 1, 0, 0.25, "First paragraph")
    second = add_bookmark(conn, 1, 1, 0.0, "Second paragraph")
    rows = list_bookmarks(conn, 1)
    assert [r["id"] for r in rows] == [first, second]
    assert rows[0]["offset_ratio"] == 0.25


def test_offset_ratio_is_clamped(tmp_path):
    conn = _conn(tmp_path)
    add_bookmark(conn, 1, 0, 5.0, "x")
    add_bookmark(conn, 1, 0, -1.0, "y")
    ratios = [r["offset_ratio"] for r in list_bookmarks(conn, 1)]
    assert ratios == [1.0, 0.0]


def test_label_is_truncated_to_80_chars(tmp_path):
    conn = _conn(tmp_path)
    add_bookmark(conn, 1, 0, 0.0, "z" * 200)
    assert len(list_bookmarks(conn, 1)[0]["label"]) == 80


def test_para_index_out_of_range_rejected(tmp_path):
    with pytest.raises(ValueError):
        add_bookmark(_conn(tmp_path), 1, 7, 0.0, "x")


def test_delete_bookmark_returns_false_when_missing(tmp_path):
    assert delete_bookmark(_conn(tmp_path), 999) is False


def test_bookmark_api_roundtrip(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','t',?,'ready')", (TEXT,))
    conn.commit()
    conn.close()
    c = TestClient(create_app(db))
    bid = c.post("/api/articles/1/bookmarks",
                 json={"para_index": 1, "offset_ratio": 0.5, "label": "Second"}).json()["id"]
    rows = c.get("/api/articles/1/bookmarks").json()
    assert rows[0]["label"] == "Second"
    assert c.delete(f"/api/bookmarks/{bid}").status_code == 200
    assert c.get("/api/articles/1/bookmarks").json() == []


def test_bookmark_for_unknown_article_returns_404(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    c = TestClient(create_app(db))
    assert c.post("/api/articles/9/bookmarks",
                  json={"para_index": 0, "offset_ratio": 0, "label": "x"}).status_code == 404
