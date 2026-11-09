import json
import os

import pytest

from app.analyze import (
    AnalysisError,
    ModelCallError,
    analyze_article,
    build_preanalysis_prompt,
    chunk_text,
    map_grammar_category,
    parse_items,
    run_claude,
)
from app.db import init_db


def _items(count, first=None):
    rows = [{"term": first or f"w{i}", "type": "word"} for i in range(count)]
    return json.dumps(rows, ensure_ascii=False)


def _article(conn, text):
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t',?,'pending')", (text,))
    conn.commit()
    return conn.execute("SELECT id FROM articles").fetchone()["id"]


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


def test_same_grammar_category_maps_to_same_id(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    a = map_grammar_category(conn, "定语从句")
    b = map_grammar_category(conn, "定语从句")
    assert a == b


def test_unknown_grammar_category_falls_back_to_other(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    mapped = map_grammar_category(conn, "模型编出来的类别")
    other = conn.execute(
        "SELECT id FROM grammar_terms WHERE label='其他'").fetchone()["id"]
    assert mapped == other
    assert conn.execute(
        "SELECT 1 FROM grammar_terms WHERE label='模型编出来的类别'"
    ).fetchone() is None


def test_preanalysis_prompt_offers_controlled_grammar_categories():
    prompt = build_preanalysis_prompt(" ".join(["word"] * 50))
    assert "grammar_category" in prompt
    assert "定语从句" in prompt
    assert "其他" in prompt


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


def test_default_chunk_size_is_500_words():
    text = " ".join(f"w{i}" for i in range(1700))
    chunks = chunk_text(text)
    assert len(chunks) == 4
    assert all(len(c.split()) <= 500 for c in chunks)


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
    analyze_article(conn, aid, runner=lambda p: prompts.append(p) or _items(60))
    assert len(prompts) == 4


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
        return _items(60, first="good")

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


def test_grammar_items_register_their_category_not_their_phrase(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','short text','pending')")
    conn.commit()
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]
    analyze_article(conn, aid, runner=lambda p: (
        '[{"term":"having started down","type":"grammar",'
        '"grammar_category":"过去分词"}]'))
    row = conn.execute(
        "SELECT status FROM grammar_terms WHERE label='过去分词'").fetchone()
    assert row["status"] == "active"
    assert conn.execute(
        "SELECT 1 FROM grammar_terms WHERE label='having started down'"
    ).fetchone() is None


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
    from app.analyze import ModelCallError, analyze_snippet
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


def test_snippet_prompt_offers_controlled_grammar_categories(tmp_path):
    from app.analyze import analyze_snippet
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text) VALUES('u','t','albeit short')")
    conn.commit()
    captured = {}

    def runner(prompt):
        captured["prompt"] = prompt
        return '[{"term":"albeit"}]'

    analyze_snippet(conn, 1, "albeit", runner=runner)
    assert "grammar_category" in captured["prompt"]
    assert "过去分词" in captured["prompt"]


def test_default_db_path_is_absolute():
    from app import main
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
    analyze_article(conn, 1, runner=lambda p: _items(60))
    assert captured["max_workers"] == 6


def test_low_output_chunk_is_retried_once(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 500))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(10) if len(calls) == 1 else _items(60)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 2
    assert row["status"] == "ready"
    assert len(json.loads(row["payload_json"])) == 60


def test_all_low_output_chunks_keep_items_and_stay_ready(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 500))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(10)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 2
    assert row["status"] == "ready"
    assert len(json.loads(row["payload_json"])) == 10


def test_all_empty_chunks_still_fail(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 500))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(0)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 2
    assert row["status"] == "failed"


def test_short_chunk_skips_density_check(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 100))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(1)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 1
    assert row["status"] == "ready"


def test_density_check_starts_at_199_words(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 199))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(1)

    analyze_article(conn, aid, runner=runner)
    assert len(calls) == 1


def test_density_check_applies_at_200_words(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 200))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(1)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 2
    assert row["status"] == "ready"
    assert len(json.loads(row["payload_json"])) == 1


def test_low_output_chunk_does_not_discard_other_chunks(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    text = " ".join(["a"] * 500 + ["marker"] + ["b"] * 499)
    aid = _article(conn, text)
    calls = []

    def runner(prompt):
        calls.append("marker" if "marker" in prompt else "plain")
        return _items(10) if "marker" in prompt else _items(60)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert calls.count("plain") == 1
    assert calls.count("marker") == 2
    assert row["status"] == "ready"
    assert len(json.loads(row["payload_json"])) == 60


def test_chunk_model_call_error_is_not_retried_and_others_kept(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    text = " ".join(["a"] * 500 + ["marker"] + ["b"] * 499)
    aid = _article(conn, text)
    calls = []

    def runner(prompt):
        if "marker" in prompt:
            calls.append("marker")
            raise ModelCallError("boom")
        calls.append("plain")
        return _items(60)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert calls.count("marker") == 1
    assert row["status"] == "ready"
    assert len(json.loads(row["payload_json"])) == 60
