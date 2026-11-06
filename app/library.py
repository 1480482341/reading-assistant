import sqlite3


def library_rows(conn: sqlite3.Connection) -> list[dict]:
    tags: dict[int, list[str]] = {}
    for row in conn.execute("SELECT article_id, tag FROM article_tags ORDER BY tag"):
        tags.setdefault(row["article_id"], []).append(row["tag"])

    articles = conn.execute(
        "SELECT a.id, a.title, a.title_zh, a.topic, a.source, a.published_at, "
        "a.word_count, a.status, "
        "EXISTS(SELECT 1 FROM shelf s WHERE s.article_id = a.id) AS in_shelf, "
        "(SELECT COUNT(*) FROM annotations x WHERE x.article_id = a.id) "
        "AS annotation_count, "
        "(SELECT COUNT(*) FROM bookmarks b WHERE b.article_id = a.id) "
        "AS bookmark_count, "
        "(SELECT COUNT(*) FROM occurrences o WHERE o.article_id = a.id) "
        "AS occurrence_count "
        "FROM articles a ORDER BY a.published_at DESC, a.id DESC"
    ).fetchall()
    return [{**dict(row), "in_shelf": bool(row["in_shelf"]),
             "tags": tags.get(row["id"], [])} for row in articles]
