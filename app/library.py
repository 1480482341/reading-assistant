import sqlite3


def library_rows(conn: sqlite3.Connection) -> list[dict]:
    tags: dict[int, list[str]] = {}
    for row in conn.execute("SELECT article_id, tag FROM article_tags ORDER BY tag"):
        tags.setdefault(row["article_id"], []).append(row["tag"])

    articles = conn.execute(
        "SELECT id, title, title_zh, topic, source, published_at, word_count, status "
        "FROM articles ORDER BY published_at DESC, id DESC"
    ).fetchall()
    return [{**dict(row), "tags": tags.get(row["id"], [])} for row in articles]
