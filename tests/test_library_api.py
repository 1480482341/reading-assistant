from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app


def _client(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,title_zh,topic,source,published_at,"
                 "word_count,text,status) VALUES(1,'u1','Older','旧文','tech','Q',"
                 "'2026-01-01',900,'body','read')")
    conn.execute("INSERT INTO articles(id,url,title,topic,source,published_at,"
                 "word_count,text,status) VALUES(2,'u2','Newer','humanities','A',"
                 "'2026-02-01',800,'body','pending')")
    conn.execute("INSERT INTO article_tags(article_id,tag) VALUES(1,'AI')")
    conn.execute("INSERT INTO article_tags(article_id,tag) VALUES(1,'Society')")
    conn.commit()
    conn.close()
    return TestClient(create_app(db))


def test_library_lists_all_statuses_newest_first(tmp_path):
    rows = _client(tmp_path).get("/api/articles/library").json()
    assert [r["id"] for r in rows] == [2, 1]
    assert {r["status"] for r in rows} == {"pending", "read"}


def test_library_returns_tags_and_null_title_zh(tmp_path):
    rows = _client(tmp_path).get("/api/articles/library").json()
    first, second = rows
    assert first["title_zh"] is None
    assert second["tags"] == ["AI", "Society"]


def test_library_route_not_shadowed_by_article_id(tmp_path):
    assert _client(tmp_path).get("/api/articles/library").status_code == 200


def test_non_numeric_article_id_is_not_found(tmp_path):
    assert _client(tmp_path).get("/api/articles/not-a-number").status_code == 404


def test_articles_without_published_at_sort_last(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,published_at,text,status) "
                 "VALUES(1,'u1','Dated','2026-01-01','body','ready')")
    conn.execute("INSERT INTO articles(id,url,title,published_at,text,status) "
                 "VALUES(2,'u2','Undated',NULL,'body','ready')")
    conn.commit()
    conn.close()
    rows = TestClient(create_app(db)).get("/api/articles/library").json()
    assert [r["id"] for r in rows] == [1, 2]


def test_library_sorts_by_parsed_date_not_raw_string(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,published_at,text,status) "
                 "VALUES(1,'u1','Older','Tue, 27 Oct 2026 13:52:12 +0000','body','ready')")
    conn.execute("INSERT INTO articles(id,url,title,published_at,text,status) "
                 "VALUES(2,'u2','Newer','Wed, 04 Nov 2026 15:32:52 +0000','body','ready')")
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    rows = TestClient(create_app(db)).get("/api/articles/library").json()
    assert [r["id"] for r in rows] == [2, 1]
    assert rows[0]["published_at"] == "2026-11-04"


from app.metadata import INTEREST_TAGS


def test_tags_endpoint_serves_controlled_vocabulary(tmp_path):
    body = _client(tmp_path).get("/api/tags").json()
    assert body["tags"] == list(INTEREST_TAGS)


def test_article_detail_includes_title_zh(tmp_path):
    body = _client(tmp_path).get("/api/articles/1").json()
    assert body["title_zh"] == "旧文"
