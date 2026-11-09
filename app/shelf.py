"""Shelf and reading history for articles."""
import sqlite3


def add_to_shelf(conn: sqlite3.Connection, article_id: int, now: str) -> None:
    """Add an article to the shelf, keeping the first added_at on repeats.

    Args:
        conn: Database connection.
        article_id: Article id.
        now: ISO timestamp provided by the caller.
    """
    conn.execute(
        "INSERT OR IGNORE INTO shelf(article_id, added_at) VALUES(?, ?)",
        (article_id, now),
    )
    conn.commit()


def remove_from_shelf(conn: sqlite3.Connection, article_id: int) -> bool:
    """Remove an article from the shelf.

    Args:
        conn: Database connection.
        article_id: Article id.

    Returns:
        True when a row was deleted, False when the article was not shelved.
    """
    cur = conn.execute("DELETE FROM shelf WHERE article_id = ?", (article_id,))
    conn.commit()
    return cur.rowcount > 0


def in_shelf(conn: sqlite3.Connection, article_id: int) -> bool:
    """Return True when the article is on the shelf."""
    row = conn.execute("SELECT 1 FROM shelf WHERE article_id = ?",
                       (article_id,)).fetchone()
    return row is not None


def shelf_rows(conn: sqlite3.Connection) -> list[dict]:
    """List shelved articles, newest added_at first, with annotation and
    bookmark counts."""
    rows = conn.execute(
        "SELECT a.id, a.title, a.title_zh, a.source, a.topic, a.status, "
        "s.added_at, "
        "(SELECT COUNT(*) FROM annotations an WHERE an.article_id = a.id) "
        "AS annotation_count, "
        "(SELECT COUNT(*) FROM bookmarks bk WHERE bk.article_id = a.id) "
        "AS bookmark_count "
        "FROM shelf s JOIN articles a ON a.id = s.article_id "
        "ORDER BY s.added_at DESC, a.id DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def record_open(conn: sqlite3.Connection, article_id: int, now: str) -> None:
    """Record an article open, bumping open_count and last_opened.

    Args:
        conn: Database connection.
        article_id: Article id.
        now: ISO timestamp provided by the caller.
    """
    cur = conn.execute(
        "UPDATE reading_history SET open_count = open_count + 1, "
        "last_opened = ? WHERE article_id = ?",
        (now, article_id),
    )
    if cur.rowcount == 0:
        conn.execute(
            "INSERT INTO reading_history(article_id, open_count, "
            "first_opened, last_opened) VALUES(?, 1, ?, ?)",
            (article_id, now, now),
        )
    conn.commit()


def history_rows(conn: sqlite3.Connection) -> list[dict]:
    """List reading history, most recently opened first, with the counts and
    shelf state the shelf page renders."""
    rows = conn.execute(
        "SELECT a.id, a.title, a.title_zh, a.source, a.topic, a.status, "
        "h.open_count, h.last_opened, "
        "EXISTS(SELECT 1 FROM shelf s WHERE s.article_id = a.id) AS in_shelf, "
        "(SELECT COUNT(*) FROM annotations an WHERE an.article_id = a.id) "
        "AS annotation_count, "
        "(SELECT COUNT(*) FROM bookmarks bk WHERE bk.article_id = a.id) "
        "AS bookmark_count "
        "FROM reading_history h JOIN articles a ON a.id = h.article_id "
        "ORDER BY h.last_opened DESC, a.id DESC"
    ).fetchall()
    return [{**dict(row), "in_shelf": bool(row["in_shelf"])} for row in rows]
