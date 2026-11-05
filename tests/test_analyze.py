import pytest

from app.db import init_db
from app.analyze import (
    chunk_text, parse_items, AnalysisError, map_grammar_term, analyze_article,
)


def test_chunk_text_splits_on_word_count():
    words = " ".join(f"w{i}" for i in range(4500))
    chunks = chunk_text(words, 2000)
    assert len(chunks) == 3
    assert all(len(c.split()) <= 2000 for c in chunks)


def test_parse_strips_markdown_fences():
    raw = '```json\n[{"term":"run","type":"word","gloss_zh":"跑"}]\n```'
    assert parse_items(raw)[0]["term"] == "run"


def test_parse_tolerates_prose_around_array():
    raw = 'Here you go:\n[{"term":"run"}]\nHope this helps.'
    assert parse_items(raw)[0]["term"] == "run"


def test_parse_raises_on_garbage():
    with pytest.raises(AnalysisError):
        parse_items("not json at all")


def test_grammar_label_maps_to_same_id(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    a = map_grammar_term(conn, "插入语")
    b = map_grammar_term(conn, "插入语")
    assert a == b


def test_analyze_article_marks_failure_without_crashing(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','short text','pending')")
    conn.commit()
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]
    analyze_article(conn, aid, runner=lambda p: "garbage")
    row = conn.execute("SELECT status, error FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert row["status"] == "failed"
    assert row["error"]


def test_parse_drops_items_without_term():
    raw = '[{"term":"run"},{"gloss_zh":"没有 term 的脏条目"}]'
    assert len(parse_items(raw)) == 1


def test_chunk_handles_code_blocks_without_crashing():
    text = "Intro.\n```python\nprint('x')\n```\n" + "word " * 2100
    assert len(chunk_text(text, 2000)) == 2
