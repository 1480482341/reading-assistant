from app.analyze import ModelCallError
from app.db import init_db
from app.metadata import INTEREST_TAGS, enrich_metadata, parse_metadata


def test_vocabulary_has_sixteen_tags():
    assert len(INTEREST_TAGS) == 16
    assert {"AI", "Physics", "Philosophy", "Society"} <= set(INTEREST_TAGS)


def test_parse_drops_unknown_and_duplicate_tags():
    raw = '[{"title_zh":"人工智能的未来","tags":["AI","Bogus","AI","Physics","History"]}]'
    items = parse_metadata(raw, 1)
    assert items == [{"title_zh": "人工智能的未来", "tags": ["AI", "Physics", "History"]}]


def test_parse_truncates_long_title_to_30_chars():
    raw = '[{"title_zh":"' + "很" * 50 + '","tags":[]}]'
    assert len(parse_metadata(raw, 1)[0]["title_zh"]) == 30


def test_parse_aligns_by_index_and_skips_missing():
    raw = '[{"title_zh":"甲","tags":["AI"]}]'
    items = parse_metadata(raw, 3)
    assert len(items) == 1


def _add_article(conn, title, text="body " * 100):
    return conn.execute(
        "INSERT INTO articles(url,title,text,status) VALUES(NULL,?,?,'pending') RETURNING id",
        (title, text),
    ).fetchone()["id"]


def test_enrich_writes_title_and_tags(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _add_article(conn, "The Future of AI")
    conn.commit()
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return '[{"title_zh":"人工智能的未来","tags":["AI","Computing"]}]'

    assert enrich_metadata(conn, runner=runner) == 1
    row = conn.execute("SELECT title_zh FROM articles WHERE id=?", (aid,)).fetchone()
    assert row["title_zh"] == "人工智能的未来"
    tags = {r["tag"] for r in conn.execute(
        "SELECT tag FROM article_tags WHERE article_id=?", (aid,))}
    assert tags == {"AI", "Computing"}
    assert "The Future of AI" in calls[0]


def test_enrich_skips_already_translated(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _add_article(conn, "Done")
    _add_article(conn, "New")
    conn.execute("UPDATE articles SET title_zh='已完成' WHERE title='Done'")
    conn.commit()
    seen = []

    def runner(prompt):
        seen.append(prompt)
        return '[{"title_zh":"新的","tags":[]}]'

    assert enrich_metadata(conn, runner=runner) == 1
    assert len(seen) == 1
    assert "New" in seen[0] and "Done" not in seen[0]


def test_enrich_retries_once_on_bad_json(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _add_article(conn, "Retry Me")
    conn.commit()
    outputs = ["not json", '[{"title_zh":"重试","tags":[]}]']

    assert enrich_metadata(conn, runner=lambda p: outputs.pop(0)) == 1
    assert outputs == []


def test_enrich_leaves_null_on_model_error(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _add_article(conn, "Broken")
    conn.commit()

    def runner(prompt):
        raise ModelCallError("boom")

    assert enrich_metadata(conn, runner=runner) == 0
    assert conn.execute(
        "SELECT title_zh FROM articles WHERE id=?", (aid,)).fetchone()["title_zh"] is None


def test_enrich_skips_batch_when_model_returns_fewer_items(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _add_article(conn, "First")
    _add_article(conn, "Second")
    conn.commit()

    def runner(prompt):
        return '[{"title_zh":"只有一个","tags":["AI"]}]'

    assert enrich_metadata(conn, runner=runner) == 0
    rows = conn.execute("SELECT title_zh FROM articles ORDER BY id").fetchall()
    assert [r["title_zh"] for r in rows] == [None, None]
    assert conn.execute("SELECT COUNT(*) FROM article_tags").fetchone()[0] == 0
