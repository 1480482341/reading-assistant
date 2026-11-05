import sqlite3

import pytest

from app.db import init_db


def test_creates_all_tables(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"articles", "analysis", "entries", "occurrences",
            "grammar_terms", "review", "sources", "settings"} <= names


def test_corrupt_db_raises_clear_error(tmp_path):
    p = tmp_path / "bad.db"
    p.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError) as e:
        init_db(str(p))
    assert "bad.db" in str(e.value) or "file is not a database" in str(e.value)
