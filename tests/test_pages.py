from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app


def test_reading_page_serves(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/")
    assert r.status_code == 200
    assert "article-body" in r.text


def test_today_endpoint_on_empty_library(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/api/articles/today")
    assert r.status_code == 200 and r.json() == []


def test_static_assets_served(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/static/style.css")
    assert r.status_code == 200
    assert "--accent" in r.text


def test_entries_endpoint_returns_json_list(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO entries(kind,lemma) VALUES('word','run')")
    conn.commit()
    conn.close()
    r = TestClient(create_app(db)).get("/api/entries")
    assert r.status_code == 200
    assert r.json()[0]["lemma"] == "run"


def test_library_page_serves(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/library")
    assert r.status_code == 200
    assert "article-list" in r.text


def test_reading_page_links_library_and_shows_title_zh_slot(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    html = TestClient(create_app(db)).get("/").text
    assert 'href="/library"' in html
    assert 'id="article-title-zh"' in html


def test_review_page_links_library(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    html = TestClient(create_app(db)).get("/review").text
    assert 'href="/library"' in html
