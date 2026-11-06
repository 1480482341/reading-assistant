"""Paragraph-based text annotations (highlights with colors)."""
import logging
import re
import sqlite3

COLORS = ("red", "green", "yellow")

logger = logging.getLogger(__name__)


def split_paragraphs(text: str) -> list[str]:
    """Split text on blank-line runs and drop empty paragraphs.

    Args:
        text: Article body text.

    Returns:
        List of stripped, non-empty paragraphs.
    """
    return [piece.strip() for piece in re.split(r"\n+", text) if piece.strip()]


def _load_paragraphs(conn: sqlite3.Connection, article_id: int) -> list[str]:
    """Return the article's paragraphs, or raise if the article is missing."""
    row = conn.execute("SELECT text FROM articles WHERE id = ?",
                       (article_id,)).fetchone()
    if row is None:
        raise ValueError(f"article {article_id} not found")
    return split_paragraphs(row["text"])


def add_annotation(conn: sqlite3.Connection, article_id: int,
                   para_index: int, start_offset: int, end_offset: int,
                   quote: str, color: str) -> int:
    """Insert an annotation, replacing overlapping ones in the same paragraph.

    Args:
        conn: Database connection.
        article_id: Article id.
        para_index: Zero-based paragraph index.
        start_offset: Start offset within the paragraph.
        end_offset: End offset within the paragraph (exclusive).
        quote: Highlighted text.
        color: One of COLORS.

    Returns:
        The new annotation id.

    Raises:
        ValueError: When the paragraph index is out of range, the color is
            not allowed, or the offset range is invalid.
    """
    paras = _load_paragraphs(conn, article_id)
    if not 0 <= para_index < len(paras):
        raise ValueError(f"para_index {para_index} out of range")
    if color not in COLORS:
        raise ValueError(f"invalid color {color!r}")
    if not 0 <= start_offset < end_offset:
        raise ValueError(f"invalid range [{start_offset}, {end_offset})")
    # Delete overlapping rows in the same paragraph within the same
    # transaction, so the insert below atomically replaces them.
    conn.execute(
        "DELETE FROM annotations WHERE article_id = ? AND para_index = ? "
        "AND end_offset > ? AND start_offset < ?",
        (article_id, para_index, start_offset, end_offset),
    )
    cur = conn.execute(
        "INSERT INTO annotations(article_id, para_index, start_offset, "
        "end_offset, quote, color) VALUES(?, ?, ?, ?, ?, ?)",
        (article_id, para_index, start_offset, end_offset, quote, color),
    )
    conn.commit()
    return cur.lastrowid


def list_annotations(conn: sqlite3.Connection,
                     article_id: int) -> list[dict]:
    """List valid annotations for an article, dropping stale rows on read.

    A row is stale when its paragraph index or offsets no longer match the
    article text, or its stored quote no longer matches the text slice.

    Args:
        conn: Database connection.
        article_id: Article id.

    Returns:
        List of dicts with keys id, para_index, start_offset, end_offset,
        quote, and color.
    """
    paras = _load_paragraphs(conn, article_id)
    rows = conn.execute(
        "SELECT id, para_index, start_offset, end_offset, quote, color "
        "FROM annotations WHERE article_id = ? "
        "ORDER BY para_index, start_offset",
        (article_id,),
    ).fetchall()
    result = []
    for row in rows:
        para_index = row["para_index"]
        start_offset = row["start_offset"]
        end_offset = row["end_offset"]
        if not 0 <= para_index < len(paras):
            logger.warning("dropping stale annotation %s", row["id"])
            continue
        para = paras[para_index]
        if not 0 <= start_offset < end_offset <= len(para):
            logger.warning("dropping stale annotation %s", row["id"])
            continue
        if para[start_offset:end_offset].strip() != row["quote"].strip():
            logger.warning("dropping stale annotation %s", row["id"])
            continue
        result.append(dict(row))
    conn.commit()
    return result


def update_annotation_color(conn: sqlite3.Connection, annotation_id: int,
                            color: str) -> bool:
    """Update an annotation's color.

    Args:
        conn: Database connection.
        annotation_id: Annotation id.
        color: One of COLORS.

    Returns:
        True when a row was updated, False when no row matched.

    Raises:
        ValueError: When the color is not allowed.
    """
    if color not in COLORS:
        raise ValueError(f"invalid color {color!r}")
    cur = conn.execute("UPDATE annotations SET color = ? WHERE id = ?",
                       (color, annotation_id))
    conn.commit()
    return cur.rowcount > 0


def delete_annotation(conn: sqlite3.Connection, annotation_id: int) -> bool:
    """Delete an annotation by id.

    Args:
        conn: Database connection.
        annotation_id: Annotation id.

    Returns:
        True when a row was deleted, False when no row matched.
    """
    cur = conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
    conn.commit()
    return cur.rowcount > 0
