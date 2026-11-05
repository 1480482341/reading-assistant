import sqlite3

import pytest

from app.db import init_db


def test_creates_all_tables(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"articles", "analysis", "entries", "occurrences",
            "grammar_terms", "review", "sources", "settings"} <= names


def test_article_tags_table_and_title_zh_column(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(articles)")}
    assert "title_zh" in cols
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "article_tags" in tables


def test_old_db_gets_title_zh_column_migrated(tmp_path):
    p = tmp_path / "old.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, text TEXT)")
    conn.execute("INSERT INTO articles(title, text) VALUES('Old', 'body')")
    conn.commit()
    conn.close()

    migrated = init_db(str(p))
    cols = {r["name"] for r in migrated.execute("PRAGMA table_info(articles)")}
    assert "title_zh" in cols
    assert migrated.execute("SELECT title FROM articles").fetchone()["title"] == "Old"


def test_init_db_stamps_schema_version(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_date_migration_only_runs_for_old_databases(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','body','ready')")
    conn.execute("UPDATE articles SET published_at='Wed, 04 Nov 2026 15:32:52 +0000'")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    migrated = init_db(db)
    assert migrated.execute("SELECT published_at FROM articles").fetchone()[0].startswith("Wed,")

    migrated.execute("PRAGMA user_version = 0")
    migrated.commit()
    migrated.close()
    migrated = init_db(db)
    assert migrated.execute("SELECT published_at FROM articles").fetchone()[0] == "2026-11-04"


def test_corrupt_db_raises_clear_error(tmp_path):
    p = tmp_path / "bad.db"
    p.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError) as e:
        init_db(str(p))
    assert "bad.db" in str(e.value) or "file is not a database" in str(e.value)
