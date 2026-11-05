import json
import os
import re
import shutil
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

Runner = Callable[[str], str]

PROMPT_TEMPLATE = """You are a vocabulary and grammar analyst for a Chinese reader of English.

Analyse the passage below. Return ONLY a JSON array. No prose, no markdown fences.

Each element must have these keys:
  term          the word or phrase exactly as it appears (lowercase the first letter only if it is a common noun)
  type          one of "word", "phrase", "grammar"
  gloss_zh      a short Chinese gloss, at most 12 characters
  grammar_role  the grammatical role in its sentence, in Chinese
  sentence      the sentence it appears in, copied verbatim
  why           one or two sentences in Chinese explaining why this construction is used

Cover difficult vocabulary, collocations, and grammar points a CET-4 level reader would stumble on.
Aim for 150-200 items when the passage is long enough; fewer is fine for short passages.

PASSAGE:
"""


class AnalysisError(Exception):
    pass


def chunk_text(text: str, words_per_chunk: int = 2000) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    return [" ".join(words[i:i + words_per_chunk])
            for i in range(0, len(words), words_per_chunk)]


def _loads_array(raw: str) -> list:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
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
    return PROMPT_TEMPLATE + chunk


def run_claude(prompt: str, timeout: int = 120) -> str:
    binary = shutil.which("claude")
    if not binary:
        raise AnalysisError("找不到 claude 可执行文件")
    cmd = ["cmd", "/c", binary] if os.name == "nt" else [binary]
    cmd += ["-p", "--output-format", "json"]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError(f"模型调用超时（{timeout}s）") from exc
    if proc.returncode != 0:
        raise AnalysisError(f"claude 退出码 {proc.returncode}: {proc.stderr[:200]}")
    try:
        outer = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout
    return outer.get("result", proc.stdout)


def map_grammar_term(conn: sqlite3.Connection, label: str) -> int:
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
    prompt = build_preanalysis_prompt(chunk)
    try:
        return parse_items(runner(prompt))
    except AnalysisError:
        return parse_items(runner(prompt + "\n\nReturn ONLY the JSON array."))


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
        with ThreadPoolExecutor(max_workers=3) as pool:
            chunk_items = list(pool.map(lambda c: _analyse_chunk(runner, c), chunks))
        merged: dict[tuple[str, str], dict] = {}
        for items in chunk_items:
            for item in items:
                key = (str(item.get("type", "word")), str(item["term"]).lower())
                merged[key] = item
        payload = json.dumps(list(merged.values()), ensure_ascii=False)
    except AnalysisError as exc:
        status, error = "failed", str(exc)

    conn.execute(
        "UPDATE analysis SET status=?, payload_json=?, error=? WHERE article_id=?",
        (status, payload, error, article_id),
    )
    conn.commit()
