import os

import pytest

from app.db import init_db
from app.analyze import (
    chunk_text, parse_items, AnalysisError, map_grammar_term, analyze_article,
    build_preanalysis_prompt, run_claude,
)


def test_chunk_text_splits_on_word_count():
    words = " ".join(f"w{i}" for i in range(4500))
    chunks = chunk_text(words, 2000)
    assert len(chunks) == 3
    assert all(len(c.split()) <= 2000 for c in chunks)


def test_preanalysis_asks_for_one_item_per_five_words():
    prompt = build_preanalysis_prompt(" ".join(["word"] * 160))
    assert "about 32 items" in prompt
    assert "one per 5 words" in prompt
    assert "context changes their meaning" in prompt


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


def test_default_chunk_size_is_800_words():
    text = " ".join(f"w{i}" for i in range(1700))
    chunks = chunk_text(text)
    assert len(chunks) == 3
    assert all(len(c.split()) <= 800 for c in chunks)


def test_prompt_targets_items_in_proportion_to_word_count():
    prompt = build_preanalysis_prompt("word " * 400)
    assert "80" in prompt
    assert "150-200" not in prompt


def test_analyze_article_uses_default_chunking(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t',?,'pending')",
                 (" ".join(f"w{i}" for i in range(1700)),))
    conn.commit()
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]
    prompts = []
    analyze_article(conn, aid, runner=lambda p: prompts.append(p) or "[]")
    assert len(prompts) == 3


def test_run_claude_defaults_to_long_timeout_in_empty_temp_cwd(monkeypatch):
    captured = {}

    class Proc:
        returncode = 0
        stdout = '{"result": "[]"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return Proc()

    monkeypatch.setattr("app.analyze.shutil.which", lambda name: "claude")
    monkeypatch.setattr("app.analyze.subprocess.run", fake_run)
    run_claude("hello")
    assert captured["timeout"] == 300
    assert os.path.isdir(captured["cwd"])
    assert os.listdir(captured["cwd"]) == []


def test_run_claude_skips_mcp_servers(monkeypatch):
    captured = {}

    class Proc:
        returncode = 0
        stdout = '{"result": "[]"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Proc()

    monkeypatch.setattr("app.analyze.shutil.which", lambda name: "claude")
    monkeypatch.setattr("app.analyze.subprocess.run", fake_run)
    run_claude("hello")
    assert "--strict-mcp-config" in captured["cmd"]


def test_run_claude_skips_user_hooks_and_plugins(monkeypatch):
    captured = {}

    class Proc:
        returncode = 0
        stdout = '{"result": "[]"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Proc()

    monkeypatch.setattr("app.analyze.shutil.which", lambda name: "claude")
    monkeypatch.setattr("app.analyze.subprocess.run", fake_run)
    run_claude("hello")
    assert "--bare" in captured["cmd"]


def test_snippet_lookup_uses_fast_model(monkeypatch, tmp_path):
    from app.analyze import analyze_snippet

    captured = {}

    class Proc:
        returncode = 0
        stdout = '{"result": "[{\\"term\\": \\"x\\", \\"gloss_zh\\": \\"y\\"}]"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Proc()

    monkeypatch.setattr("app.analyze.shutil.which", lambda name: "claude")
    monkeypatch.setattr("app.analyze.subprocess.run", fake_run)

    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','body text','ready')")
    conn.commit()
    analyze_snippet(conn, 1, "body")
    assert "--model" in captured["cmd"]
    assert "haiku" in captured["cmd"]


def test_preanalysis_keeps_default_model(monkeypatch, tmp_path):
    captured = {}

    class Proc:
        returncode = 0
        stdout = '{"result": "[{\\"term\\": \\"x\\"}]"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Proc()

    monkeypatch.setattr("app.analyze.shutil.which", lambda name: "claude")
    monkeypatch.setattr("app.analyze.subprocess.run", fake_run)

    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','body text','pending')")
    conn.commit()
    analyze_article(conn, 1)
    assert "--model" not in captured["cmd"]


def test_successful_analysis_marks_article_ready(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','short text','pending')")
    conn.commit()
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]
    analyze_article(conn, aid, runner=lambda p: '[{"term":"run","type":"word"}]')
    assert conn.execute("SELECT status FROM articles WHERE id=?", (aid,)).fetchone()["status"] == "ready"


def test_find_sentence_uses_selection_when_not_found(tmp_path):
    from app.analyze import find_sentence
    assert find_sentence("Alpha. Beta.", "gamma " * 100).startswith("gamma")


def test_partial_chunk_failure_keeps_successful_items(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    text = " ".join(["good"] * 800 + ["boom"] + ["good"] * 799)
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t',?,'pending')", (text,))
    conn.commit()
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]

    def runner(prompt):
        if "boom" in prompt:
            raise AnalysisError("boom chunk failed")
        return '[{"term":"good","type":"word"}]'

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert row["status"] == "ready"
    assert "good" in row["payload_json"]


def test_reanalysis_clears_lookup_cache(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','short text','pending')")
    conn.commit()
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]
    conn.execute("INSERT INTO lookups(article_id,text,payload_json) VALUES(?,?,?)",
                 (aid, "run", '{"term":"run","gloss_zh":"旧"}'))
    conn.commit()

    analyze_article(conn, aid, runner=lambda p: '[{"term":"run","type":"word","gloss_zh":"跑"}]')
    left = conn.execute("SELECT COUNT(*) AS n FROM lookups WHERE article_id=?",
                        (aid,)).fetchone()["n"]
    assert left == 0


def test_grammar_items_register_in_grammar_terms(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','short text','pending')")
    conn.commit()
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]
    analyze_article(conn, aid, runner=lambda p: '[{"term":"插入语","type":"grammar"}]')
    assert conn.execute("SELECT 1 FROM grammar_terms WHERE label='插入语'").fetchone()


def test_parse_tolerates_brackets_in_surrounding_prose():
    raw = '[{"term":"run","type":"word"}] Hope this helps. [done]'
    assert parse_items(raw)[0]["term"] == "run"


def test_parse_failure_is_retried_once(tmp_path):
    from app.analyze import analyze_snippet
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text) VALUES('u','t','albeit short')")
    conn.commit()
    calls = []

    def runner(prompt):
        calls.append(1)
        return "garbage" if len(calls) == 1 else '[{"term":"albeit"}]'

    assert analyze_snippet(conn, 1, "albeit", runner=runner)["term"] == "albeit"
    assert len(calls) == 2


def test_model_call_failure_is_not_retried(tmp_path):
    from app.analyze import analyze_snippet, ModelCallError
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text) VALUES('u','t','albeit short')")
    conn.commit()
    calls = []

    def runner(prompt):
        calls.append(1)
        raise ModelCallError("timeout")

    with pytest.raises(ModelCallError):
        analyze_snippet(conn, 1, "albeit", runner=runner)
    assert len(calls) == 1


def test_default_db_path_is_absolute():
    import app.main as main
    assert main.DB_PATH.is_absolute()
    assert main.DB_PATH.as_posix().endswith("data/library.db")


def test_analyze_article_uses_six_parallel_chunks(monkeypatch, tmp_path):
    import app.analyze as mod

    captured = {}
    real_pool = mod.ThreadPoolExecutor

    def recording_pool(*args, **kwargs):
        captured.update(kwargs)
        return real_pool(*args, **kwargs)

    monkeypatch.setattr(mod, "ThreadPoolExecutor", recording_pool)
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t',?,'pending')",
                 (" ".join(f"w{i}" for i in range(1700)),))
    conn.commit()
    analyze_article(conn, 1, runner=lambda p: "[]")
    assert captured["max_workers"] == 6
