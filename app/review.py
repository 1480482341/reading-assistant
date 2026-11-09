import sqlite3
from datetime import date, timedelta

INTERVALS = [0, 3, 7]
LAST_BUCKET = len(INTERVALS) - 1
GRADUATE_AFTER = 2


def _due(now: str, days: int) -> str:
    return (date.fromisoformat(now) + timedelta(days=days)).isoformat()


def ensure_review(conn: sqlite3.Connection, entry_id: int, now: str) -> None:
    existing = conn.execute(
        "SELECT 1 FROM review WHERE entry_id = ?", (entry_id,)
    ).fetchone()
    if existing:
        return
    conn.execute(
        "INSERT INTO review(entry_id, bucket, due_at, last_seen_at, "
        "consecutive_known, graduated) VALUES(?, 0, ?, ?, 0, 0)",
        (entry_id, now, now),
    )
    conn.commit()


def grade(conn: sqlite3.Connection, entry_id: int, known: bool, now: str) -> None:
    row = conn.execute("SELECT * FROM review WHERE entry_id = ?", (entry_id,)).fetchone()
    if row is None:
        ensure_review(conn, entry_id, now)
        row = conn.execute("SELECT * FROM review WHERE entry_id = ?", (entry_id,)).fetchone()

    if known:
        bucket = min(row["bucket"] + 1, LAST_BUCKET)
        consecutive = row["consecutive_known"] + 1 if bucket == LAST_BUCKET else 0
        graduated = 1 if consecutive >= GRADUATE_AFTER else 0
    else:
        bucket, consecutive, graduated = 0, 0, 0

    conn.execute(
        "UPDATE review SET bucket = ?, due_at = ?, last_seen_at = ?, "
        "consecutive_known = ?, graduated = ? WHERE entry_id = ?",
        (bucket, _due(now, INTERVALS[bucket]), now, consecutive, graduated, entry_id),
    )
    conn.commit()


def due_queue(conn: sqlite3.Connection, now: str, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.entry_id, e.kind, e.lemma, e.category, r.bucket, r.due_at, "
        "COALESCE(o.gloss, '') AS gloss, COALESCE(o.sentence, '') AS sentence, "
        "(SELECT COUNT(*) FROM occurrences o2 WHERE o2.entry_id = e.id) AS count "
        "FROM review r JOIN entries e ON e.id = r.entry_id "
        "LEFT JOIN occurrences o ON o.id = "
        "(SELECT MAX(id) FROM occurrences WHERE entry_id = e.id) "
        "WHERE r.graduated = 0 AND r.due_at <= ? "
        "ORDER BY count DESC, r.due_at ASC LIMIT ?",
        (now, limit),
    ).fetchall()
