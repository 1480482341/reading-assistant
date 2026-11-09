import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.grammar import (
    FALLBACK_CATEGORY,
    GRAMMAR_CATEGORIES,
    normalize_grammar_category,
)

Runner = Callable[[str], str]

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_WORDS = 800
DEFAULT_TIMEOUT = 300
WORDS_PER_ITEM = 5
SNIPPET_MODEL = "haiku"
PREANALYSIS_WORKERS = 6

PROMPT_TEMPLATE = """You are a vocabulary and grammar analyst for a Chinese reader of English.

Analyse the passage below. Return ONLY a JSON array. No prose, no markdown fences.

Each element must have these keys:
  term          the word or phrase exactly as it appears (lowercase the first letter only if it is a common noun)
  type          one of "word", "phrase", "grammar"
  gloss_zh      a short Chinese gloss, at most 12 characters
  grammar_role  the grammatical role in its sentence, in Chinese
  grammar_category  only when type is "grammar": one label copied exactly from the list below, or 其他 when none fits
  sentence      the sentence it appears in, copied verbatim
  why           one or two sentences in Chinese explaining why this construction is used

Cover difficult vocabulary, collocations, and grammar points a CET-4 level reader would stumble on.
Treat ordinary-looking words as difficult when the context changes their meaning.
For grammar items keep term as the phrase from the passage and put the category in grammar_category.
GRAMMAR CATEGORIES: {categories}
List each distinct term once; do not repeat near-duplicates.
Aim for about {target} items for this passage (roughly one per {words_per_item} words);
fewer is fine when the passage has few difficult constructions.

PASSAGE:
"""


class AnalysisError(Exception):
    pass


class ModelCallError(AnalysisError):
    """The model call itself failed (missing binary, timeout, non-zero exit)."""


def chunk_text(text: str, words_per_chunk: int = DEFAULT_CHUNK_WORDS) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    return [" ".join(words[i:i + words_per_chunk])
            for i in range(0, len(words), words_per_chunk)]


def _loads_array(raw: str) -> list:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
        decoder = json.JSONDecoder()
        for pos, char in enumerate(raw):
            if char != "[":
                continue
            try:
                candidate, _ = decoder.raw_decode(raw, pos)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, list):
                data = candidate
                break
        if data is None:
            raise
    if not isinstance(data, list):
        raise AnalysisError("模型输出不是数组")
    return data


def parse_items(raw: str) -> list[dict]:
    try:
        data = _loads_array(raw)
    except AnalysisError:
        raise
    except Exception as exc:
        raise AnalysisError(f"无法解析模型输出: {exc}") from exc
    return [item for item in data
            if isinstance(item, dict) and item.get("term")]


def build_preanalysis_prompt(chunk: str) -> str:
    target = max(1, round(len(chunk.split()) / WORDS_PER_ITEM))
    return PROMPT_TEMPLATE.format(target=target,
                                  words_per_item=WORDS_PER_ITEM,
                                  categories="、".join(GRAMMAR_CATEGORIES)) + chunk


_MODEL_CWD: str | None = None


def model_cwd() -> str:
    """Empty working directory so the model never picks up this project's context."""
    global _MODEL_CWD
    if _MODEL_CWD is None:
        _MODEL_CWD = tempfile.mkdtemp(prefix="reading-assistant-model-")
    return _MODEL_CWD


def run_claude(prompt: str, timeout: int = DEFAULT_TIMEOUT,
               model: str | None = None) -> str:
    binary = shutil.which("claude")
    if not binary:
        raise ModelCallError("找不到 claude 可执行文件")
    cmd = ["cmd", "/c", binary] if os.name == "nt" else [binary]
    # --bare skips user hooks/plugins/memory: ~1.5s faster per call, no effect on JSON output
    cmd += ["-p", "--output-format", "json", "--strict-mcp-config", "--bare"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              cwd=model_cwd(), check=False)
    except subprocess.TimeoutExpired as exc:
        raise ModelCallError(f"模型调用超时（{timeout}s）") from exc
    if proc.returncode != 0:
        raise ModelCallError(f"claude 退出码 {proc.returncode}: {proc.stderr[:200]}")
    try:
        outer = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout
    return outer.get("result", proc.stdout)


def _run_with_retry(runner: Runner, prompt: str) -> list[dict]:
    try:
        return parse_items(runner(prompt))
    except ModelCallError:
        raise
    except AnalysisError:
        return parse_items(runner(prompt + "\n\nReturn ONLY the JSON array."))


SNIPPET_TEMPLATE = """A reader selected "{term}" in the sentence below.
Return ONLY a JSON array with one object with keys: term, type, gloss_zh, grammar_role, grammar_category, sentence, why.
grammar_category is only for type "grammar": copy one label exactly from the list below, or use 其他.
Write gloss_zh, grammar_role and why in Chinese.
GRAMMAR CATEGORIES: {categories}

SENTENCE: {sentence}
"""


def find_sentence(body: str, needle: str) -> str:
    needle = needle.strip()
    idx = body.find(needle)
    if idx < 0 and len(needle) > 40:
        idx = body.find(needle[:40])
    if idx < 0:
        return needle[:400]
    start = body.rfind(".", 0, idx) + 1
    end = body.find(".", idx)
    end = len(body) if end < 0 else end + 1
    return body[start:end].strip()[:400]


def analyze_snippet(conn: sqlite3.Connection, article_id: int, needle: str,
                    runner: Runner | None = None) -> dict:
    runner = runner or (lambda p: run_claude(p, model=SNIPPET_MODEL))
    row = conn.execute("SELECT text FROM articles WHERE id = ?", (article_id,)).fetchone()
    body = row["text"] if row else ""
    sentence = find_sentence(body, needle)
    prompt = SNIPPET_TEMPLATE.format(
        term=needle, sentence=sentence,
        categories="、".join(GRAMMAR_CATEGORIES))
    items = _run_with_retry(runner, prompt)
    if not items:
        raise AnalysisError("模型未返回条目")
    item = items[0]
    item.setdefault("sentence", sentence)
    return item


def map_grammar_category(conn: sqlite3.Connection, category: str) -> int:
    """Map a model-supplied category to its vocabulary row.

    Anything outside the controlled list collapses to 其他, so the table never
    accumulates one-off phrase labels again.
    """
    raw = str(category or "").strip()
    label = normalize_grammar_category(raw)
    if raw and raw not in GRAMMAR_CATEGORIES:
        logger.warning("unknown grammar category %r mapped to %s",
                       raw, FALLBACK_CATEGORY)
    row = conn.execute("SELECT id FROM grammar_terms WHERE label = ?", (label,)).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "INSERT INTO grammar_terms(label, status) VALUES(?, 'pending') RETURNING id",
        (label,),
    ).fetchone()
    conn.commit()
    return row["id"]


def _analyse_chunk(runner: Runner, chunk: str) -> list[dict]:
    return _run_with_retry(runner, build_preanalysis_prompt(chunk))


def analyze_article(conn: sqlite3.Connection, article_id: int,
                    runner: Runner | None = None) -> None:
    runner = runner or run_claude
    row = conn.execute("SELECT text FROM articles WHERE id = ?", (article_id,)).fetchone()
    if row is None:
        raise AnalysisError(f"文章不存在: {article_id}")

    conn.execute(
        "INSERT INTO analysis(article_id, status) VALUES(?, 'running') "
        "ON CONFLICT(article_id) DO UPDATE SET status='running', error=NULL",
        (article_id,),
    )
    conn.commit()

    status, payload, error = "ready", None, None
    try:
        chunks = chunk_text(row["text"])
        chunk_items: list[list[dict]] = []
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=PREANALYSIS_WORKERS) as pool:
            futures = [pool.submit(_analyse_chunk, runner, chunk) for chunk in chunks]
            for future in as_completed(futures):
                try:
                    chunk_items.append(future.result())
                except AnalysisError as exc:
                    failures.append(str(exc))
        if not chunk_items:
            raise AnalysisError("; ".join(failures) or "预分析失败")
        merged: dict[tuple[str, str], dict] = {}
        for items in chunk_items:
            for item in items:
                key = (str(item.get("type", "word")), str(item["term"]).lower())
                merged[key] = item
        for item in merged.values():
            if item.get("type") == "grammar":
                map_grammar_category(conn, str(item.get("grammar_category") or ""))
        payload = json.dumps(list(merged.values()), ensure_ascii=False)
    except AnalysisError as exc:
        status, error = "failed", str(exc)

    conn.execute(
        "UPDATE analysis SET status=?, payload_json=?, error=? WHERE article_id=?",
        (status, payload, error, article_id),
    )
    if status == "ready":
        conn.execute("UPDATE articles SET status='ready' WHERE id=?", (article_id,))
        conn.execute("DELETE FROM lookups WHERE article_id=?", (article_id,))
    conn.commit()
