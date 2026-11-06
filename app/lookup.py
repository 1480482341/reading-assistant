import json
import re
import sqlite3

_EDGE_PUNCTUATION = re.compile(r"^[^\w]+|[^\w]+$")
MAX_PHRASE_WORDS = 6
MIN_FUZZY_LEN = 5


def normalize_term(text: str) -> str:
    return _EDGE_PUNCTUATION.sub("", (text or "").strip()).lower()


def _stem_variants(word: str) -> set[str]:
    variants = {word}
    if word.endswith("ies") and len(word) > 4:
        variants.add(word[:-3] + "y")
    if word.endswith("es") and len(word) > 4:
        variants.add(word[:-2])
    if word.endswith("s") and len(word) > 4 and not word.endswith("ss"):
        variants.add(word[:-1])
    if word.endswith("ed") and len(word) > 5:
        variants.update({word[:-2], word[:-1]})
    if word.endswith("ing") and len(word) > 6:
        variants.update({word[:-3], word[:-3] + "e"})
    if word.endswith("ly") and len(word) > 5:
        variants.add(word[:-2])
    return variants


def find_analysis_item(payload_json: str | None, needle: str) -> dict | None:
    if not payload_json or not needle:
        return None
    pairs = [(item, normalize_term(str(item.get("term", ""))))
             for item in json.loads(payload_json)]
    for item, term in pairs:
        if term == needle:
            return item

    needle_stems = _stem_variants(needle)
    if len(needle) >= MIN_FUZZY_LEN:
        for item, term in pairs:
            if term and len(term) >= MIN_FUZZY_LEN and _stem_variants(term) & needle_stems:
                return item

    if " " in needle or len(needle) < MIN_FUZZY_LEN or not needle.isalpha():
        return None
    pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
    matches = [(len(term.split()), len(term), item)
               for item, term in pairs
               if 1 < len(term.split()) <= MAX_PHRASE_WORDS and pattern.search(term)]
    return min(matches, key=lambda match: (match[0], match[1]))[2] if matches else None


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
