from app.db import init_db
from app.review import due_queue, ensure_review, grade

NOW = "2026-11-05"


def _entry(conn):
    return conn.execute(
        "INSERT INTO entries(kind,lemma) VALUES('word','run') RETURNING id"
    ).fetchone()["id"]


def test_new_entry_due_today(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    e = _entry(conn)
    ensure_review(conn, e, NOW)
    assert len(due_queue(conn, NOW)) == 1


def test_known_advances_bucket(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    e = _entry(conn)
    ensure_review(conn, e, NOW)
    grade(conn, e, True, NOW)
    row = conn.execute("SELECT bucket FROM review WHERE entry_id=?", (e,)).fetchone()
    assert row["bucket"] == 1
    assert due_queue(conn, NOW) == []


def test_unknown_resets_to_zero(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    e = _entry(conn)
    ensure_review(conn, e, NOW)
    grade(conn, e, True, NOW)
    grade(conn, e, False, NOW)
    row = conn.execute(
        "SELECT bucket, consecutive_known FROM review WHERE entry_id=?", (e,)
    ).fetchone()
    assert row["bucket"] == 0 and row["consecutive_known"] == 0


def test_two_known_at_last_bucket_graduates(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    e = _entry(conn)
    ensure_review(conn, e, NOW)
    for _ in range(4):
        grade(conn, e, True, NOW)
    row = conn.execute("SELECT graduated FROM review WHERE entry_id=?", (e,)).fetchone()
    assert row["graduated"] == 1
    assert due_queue(conn, NOW) == []
