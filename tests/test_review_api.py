from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app


def test_empty_queue_returns_list(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/api/review/queue")
    assert r.status_code == 200 and r.json() == []


def test_grading_moves_entry(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO entries(kind,lemma) VALUES('word','run')")
    conn.execute(
        "INSERT INTO review(entry_id,bucket,due_at,consecutive_known,graduated) "
        "VALUES(1,0,'2026-11-05',0,0)"
    )
    conn.commit()
    conn.close()
    c = TestClient(create_app(db))
    assert c.post("/api/review/1", json={"known": True}).status_code == 200
    assert c.get("/api/review/queue").json() == []


def test_review_page_serves(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/review")
    assert r.status_code == 200
    assert "review-card" in r.text
