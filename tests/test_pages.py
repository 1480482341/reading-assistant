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


def _html(path, tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    return TestClient(create_app(db)).get(path).text


def test_style_defines_four_themes(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    css = TestClient(create_app(db)).get("/static/style.css").text
    for theme in ("eye-green", "dark", "light", "eye-warm"):
        assert f'[data-theme="{theme}"]' in css


def test_every_page_sets_theme_before_render_and_has_toggle(tmp_path):
    for path in ("/", "/library", "/review"):
        html = _html(path, tmp_path)
        assert "ra-theme" in html
        assert 'id="theme-toggle"' in html
        assert "/static/theme.js" in html


def test_inline_theme_script_falls_back_to_eye_green(tmp_path):
    html = _html("/", tmp_path)
    assert 'localStorage.getItem("ra-theme")' in html
    assert 't = "eye-green"' in html
