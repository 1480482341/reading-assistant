"""Bookmarks for reading positions within article paragraphs."""
import logging
import sqlite3

from app.annotations import split_paragraphs

MAX_LABEL_LENGTH = 80

logger = logging.getLogger(__name__)


def _load_paragraphs(conn: sqlite3.Connection, article_id: int) -> list[str]:
    """Return the article's paragraphs, or raise if the article is missing."""
    row = conn.execute("SELECT text FROM articles WHERE id = ?",
                       (article_id,)).fetchone()
    if row is None:
        raise ValueError(f"article {article_id} not found")
    return split_paragraphs(row["text"])


def add_bookmark(conn: sqlite3.Connection, article_id: int,
                 para_index: int, offset_ratio: float, label: str) -> int:
    """Insert a bookmark for a reading position.

    Args:
        conn: Database connection.
        article_id: Article id.
        para_index: Zero-based paragraph index.
        offset_ratio: Position within the paragraph, clamped to [0.0, 1.0].
        label: Short user note, truncated to MAX_LABEL_LENGTH characters.

    Returns:
        The new bookmark id.

    Raises:
        ValueError: When the paragraph index is out of range.
    """
    paras = _load_paragraphs(conn, article_id)
    if not 0 <= para_index < len(paras):
        raise ValueError(f"para_index {para_index} out of range")
    offset_ratio = min(1.0, max(0.0, offset_ratio))
    label = label[:MAX_LABEL_LENGTH]
    cur = conn.execute(
        "INSERT INTO bookmarks(article_id, para_index, offset_ratio, label) "
        "VALUES(?, ?, ?, ?)",
        (article_id, para_index, offset_ratio, label),
    )
    conn.commit()
    return cur.lastrowid


def list_bookmarks(conn: sqlite3.Connection, article_id: int) -> list[dict]:
    """List bookmarks for an article in creation order.

    Args:
        conn: Database connection.
        article_id: Article id.

    Returns:
        List of dicts with keys id, para_index, offset_ratio, label,
        and created_at, ordered by created_at then id ascending.
    """
    rows = conn.execute(
        "SELECT id, para_index, offset_ratio, label, created_at "
        "FROM bookmarks WHERE article_id = ? "
        "ORDER BY created_at, id",
        (article_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_bookmark(conn: sqlite3.Connection, bookmark_id: int) -> bool:
    """Delete a bookmark by id.

    Args:
        conn: Database connection.
        bookmark_id: Bookmark id.

    Returns:
        True when a row was deleted, False when no row matched.
    """
    cur = conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
    conn.commit()
    return cur.rowcount > 0
