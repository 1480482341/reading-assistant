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
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert conn.execute(
        "SELECT 1 FROM grammar_terms WHERE label='定语从句' AND status='active'"
    ).fetchone()


def test_legacy_phrase_vocabulary_is_archived_and_replaced(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("DELETE FROM grammar_terms")
    conn.execute(
        "INSERT INTO grammar_terms(label, status) VALUES"
        "('have yet to observe', 'pending'),"
        "('while working at Google', 'pending')")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    migrated = init_db(db)
    legacy = {row["label"] for row in migrated.execute(
        "SELECT label FROM grammar_terms_legacy")}
    assert legacy == {"have yet to observe", "while working at Google"}
    labels = {row["label"] for row in migrated.execute(
        "SELECT label FROM grammar_terms")}
    assert "have yet to observe" not in labels
    assert "定语从句" in labels
    statuses = {row["status"] for row in migrated.execute(
        "SELECT status FROM grammar_terms")}
    assert statuses == {"active"}
    assert migrated.execute("PRAGMA user_version").fetchone()[0] == 3


def test_date_migration_only_runs_for_old_databases(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','body','ready')")
    conn.execute("UPDATE articles SET published_at='Wed, 04 Nov 2026 15:32:52 +0000'")
    conn.execute("PRAGMA user_version = 2")
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


def test_reading_annotation_tables_exist(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"annotations", "bookmarks", "shelf", "reading_history"} <= names


def test_schema_version_is_three(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_v1_database_upgrades_and_keeps_rows(tmp_path):
    p = tmp_path / "old.db"
    raw = sqlite3.connect(str(p))
    raw.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, text TEXT)")
    raw.execute("INSERT INTO articles(title, text) VALUES('Old', 'body')")
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()

    conn = init_db(str(p))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert conn.execute("SELECT title FROM articles").fetchone()["title"] == "Old"
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"annotations", "bookmarks", "shelf", "reading_history"} <= names


def test_deleting_article_cascades_marks(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(id,url,title,text) VALUES(1,'u','t','body')")
    conn.execute("INSERT INTO annotations(article_id,para_index,start_offset,"
                 "end_offset,quote,color) VALUES(1,0,0,4,'body','red')")
    conn.execute("INSERT INTO bookmarks(article_id,para_index,offset_ratio,label) "
                 "VALUES(1,0,0.5,'body')")
    conn.execute("INSERT INTO shelf(article_id) VALUES(1)")
    conn.execute("INSERT INTO reading_history(article_id,open_count) VALUES(1,1)")
    conn.commit()
    conn.execute("DELETE FROM articles WHERE id = 1")
    conn.commit()
    for table in ("annotations", "bookmarks", "shelf", "reading_history"):
        assert conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] == 0
