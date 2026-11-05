import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT UNIQUE,
    title        TEXT NOT NULL,
    source       TEXT,
    topic        TEXT,
    published_at TEXT,
    fetched_at   TEXT DEFAULT (datetime('now')),
    raw_html     TEXT,
    text         TEXT NOT NULL,
    word_count   INTEGER,
    status       TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS analysis (
    article_id   INTEGER PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    status       TEXT DEFAULT 'pending',
    payload_json TEXT,
    model        TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    error        TEXT
);

CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    lemma      TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(kind, lemma)
);

CREATE TABLE IF NOT EXISTS occurrences (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id     INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    article_id   INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    sentence     TEXT DEFAULT '',
    surface      TEXT DEFAULT '',
    gloss        TEXT DEFAULT '',
    grammar_role TEXT DEFAULT '',
    why          TEXT DEFAULT '',
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS grammar_terms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL UNIQUE,
    aliases     TEXT DEFAULT '',
    description TEXT DEFAULT '',
    status      TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS review (
    entry_id          INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    bucket            INTEGER DEFAULT 0,
    due_at            TEXT,
    last_seen_at      TEXT,
    consecutive_known INTEGER DEFAULT 0,
    graduated         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sources (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    feed_url TEXT NOT NULL UNIQUE,
    topic    TEXT NOT NULL,
    enabled  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str) -> sqlite3.Connection:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise sqlite3.DatabaseError(f"数据库无法打开: {path}") from exc
    return conn
