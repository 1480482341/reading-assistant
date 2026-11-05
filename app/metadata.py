import logging
import sqlite3

from app.analyze import ModelCallError, Runner, _loads_array, run_claude

logger = logging.getLogger(__name__)

INTEREST_TAGS = (
    "AI", "Computing", "Physics", "Math", "Biology", "Medicine", "Psychology",
    "Philosophy", "History", "Politics", "Economics", "Environment", "Art",
    "Literature", "Culture", "Society",
)

TITLE_ZH_MAX = 30
MAX_TAGS = 3
EXCERPT_WORDS = 100
BATCH_SIZE = 10

PROMPT_TEMPLATE = """You are tagging English articles for a Chinese reader.
For each numbered item below, return a JSON object with:
  title_zh  a natural Chinese translation of the title, at most {max_title} characters
  tags      1-3 labels chosen ONLY from this list: {tags}
Return ONLY a JSON array, one object per item, in the same order.

{items}
"""


def build_metadata_prompt(batch: list[tuple[str, str]]) -> str:
    items = "\n".join(
        f"{i}. TITLE: {title}\n   EXCERPT: {excerpt}"
        for i, (title, excerpt) in enumerate(batch, start=1)
    )
    return PROMPT_TEMPLATE.format(
        max_title=TITLE_ZH_MAX,
        tags=", ".join(INTEREST_TAGS),
        items=items,
    )


def _clean_title(raw: object) -> str:
    return str(raw or "").strip()[:TITLE_ZH_MAX]


def _clean_tags(raw: object) -> list[str]:
    tags: list[str] = []
    for tag in raw if isinstance(raw, list) else []:
        if tag in INTEREST_TAGS and tag not in tags:
            tags.append(tag)
    return tags[:MAX_TAGS]


def parse_metadata(raw: str, expected: int) -> list[dict]:
    data = _loads_array(raw)
    items: list[dict] = []
    for entry in data[:expected]:
        if not isinstance(entry, dict):
            items.append({"title_zh": "", "tags": []})
            continue
        items.append({
            "title_zh": _clean_title(entry.get("title_zh")),
            "tags": _clean_tags(entry.get("tags")),
        })
    return items


def _parse_with_retry(runner: Runner, prompt: str, expected: int) -> list[dict]:
    try:
        return parse_metadata(runner(prompt), expected)
    except ModelCallError:
        raise
    except Exception:
        return parse_metadata(runner(prompt + "\n\nReturn ONLY the JSON array."), expected)


def _excerpt(text: str) -> str:
    return " ".join(text.split()[:EXCERPT_WORDS])


def enrich_metadata(conn: sqlite3.Connection, runner: Runner | None = None,
                    batch_size: int = BATCH_SIZE) -> int:
    runner = runner or run_claude
    rows = conn.execute(
        "SELECT id, title, text FROM articles WHERE title_zh IS NULL ORDER BY id"
    ).fetchall()
    enriched = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        prompt = build_metadata_prompt(
            [(row["title"], _excerpt(row["text"])) for row in batch]
        )
        try:
            items = _parse_with_retry(runner, prompt, len(batch))
        except Exception:
            logger.warning("元数据生成失败: 第 %s 批", start // batch_size + 1,
                           exc_info=True)
            continue
        for row, item in zip(batch, items):
            if not item["title_zh"]:
                continue
            conn.execute("UPDATE articles SET title_zh=? WHERE id=?",
                         (item["title_zh"], row["id"]))
            for tag in item["tags"]:
                conn.execute(
                    "INSERT OR IGNORE INTO article_tags(article_id, tag) VALUES(?, ?)",
                    (row["id"], tag),
                )
            enriched += 1
        conn.commit()
    return enriched
