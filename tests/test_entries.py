from app.db import entry_frequency, init_db, insert_occurrence, upsert_entry


def _article(conn, article_id):
    conn.execute(
        "INSERT INTO articles(id, url, title, text) VALUES(?, ?, ?, ?)",
        (article_id, f"u{article_id}", "t", "body"),
    )
    conn.commit()


def test_same_lemma_is_one_entry(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    a = upsert_entry(conn, "word", "run")
    b = upsert_entry(conn, "word", "run")
    assert a == b


def test_duplicate_lookup_in_same_article_counts_once(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _article(conn, 1)
    e = upsert_entry(conn, "word", "run")
    assert insert_occurrence(conn, e, 1, "He ran.", "ran", "跑", "谓语", "过去式") is True
    assert insert_occurrence(conn, e, 1, "He ran again.", "ran", "跑", "谓语", "过去式") is False
    assert entry_frequency(conn)[0]["count"] == 1


def test_frequency_orders_desc(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _article(conn, 1)
    _article(conn, 2)
    a = upsert_entry(conn, "word", "albeit")
    b = upsert_entry(conn, "word", "scrutiny")
    insert_occurrence(conn, a, 1, "s", "albeit", "尽管", "", "")
    insert_occurrence(conn, b, 1, "s", "scrutiny", "审查", "", "")
    insert_occurrence(conn, b, 2, "s", "scrutiny", "审查", "", "")
    assert [r["lemma"] for r in entry_frequency(conn)] == ["scrutiny", "albeit"]
