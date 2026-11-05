import json
import re
import sqlite3

_EDGE_PUNCTUATION = re.compile(r"^[^\w]+|[^\w]+$")


def normalize_term(text: str) -> str:
    return _EDGE_PUNCTUATION.sub("", (text or "").strip()).lower()


def find_analysis_item(payload_json: str | None, needle: str) -> dict | None:
    if not payload_json or not needle:
        return None
    for item in json.loads(payload_json):
        if normalize_term(str(item.get("term", ""))) == needle:
            return item
    return None


def cached_item(conn: sqlite3.Connection, article_id: int, needle: str) -> dict | None:
    row = conn.execute(
        "SELECT payload_json FROM lookups WHERE article_id = ? AND text = ?",
        (article_id, needle),
    ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def store_item(conn: sqlite3.Connection, article_id: int, needle: str,
               item: dict) -> None:
    conn.execute(
        "INSERT INTO lookups(article_id, text, payload_json) VALUES(?, ?, ?) "
        "ON CONFLICT(article_id, text) DO UPDATE SET payload_json = excluded.payload_json",
        (article_id, needle, json.dumps(item, ensure_ascii=False)),
    )
    conn.commit()
