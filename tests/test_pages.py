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


def test_reading_page_has_three_columns(tmp_path):
    html = _html("/", tmp_path)
    for needle in ('class="actions"', 'class="reader"', 'class="sidebar"',
                   'id="add-bookmark"', 'id="bookmark-list"',
                   'data-color="red"', 'data-color="green"', 'data-color="yellow"',
                   'id="shelf-toggle"', 'id="mark-read"'):
        assert needle in html


def test_sidebar_scrolls_independently(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    css = TestClient(create_app(db)).get("/static/style.css").text
    assert "overflow-y: auto" in css


def test_reading_script_renders_annotations_and_loads_marks(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    for needle in ("function paragraphs", "function renderBody",
                   "hl-", "data-annotation-id", "/marks"):
        assert needle in js


def test_color_mode_and_selection_mapping(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    for needle in ("colorMode", "selectionToRange", "applyAnnotation",
                   "/annotations", "hl-popup"):
        assert needle in js
    html = TestClient(create_app(db)).get("/").text
    assert 'id="hl-popup"' in html


def test_bookmark_functions_present(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    for needle in ("function renderBookmarks", "function addBookmark",
                   "function jumpToBookmark", "function currentBookmarkAnchor",
                   "/bookmarks"):
        assert needle in js


def test_bookmark_list_styles(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    css = TestClient(create_app(db)).get("/static/style.css").text
    for needle in ("#bookmark-list li", ".bm-jump", ".bm-del",
                   "var(--line)", "var(--accent)", "var(--muted)",
                   "text-overflow: ellipsis", "flex: 1"):
        assert needle in css


def test_bookmark_anchor_measures_dom(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    for needle in ("getBoundingClientRect", "scrollIntoView", "scrollBy",
                   "offsetHeight"):
        assert needle in js


def test_bookmark_anchor_spans_top_of_viewport(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    for needle in ("rect.bottom > top", "paras[paras.length - 1]",
                   "if (!paras.length) return null"):
        assert needle in js


def test_bookmark_mutations_gated_on_ok(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    add_idx = js.index("function addBookmark")
    assert js.index("if (!resp.ok) return;", add_idx) \
        < js.index("bookmarks.push", add_idx)
    render_idx = js.index("function renderBookmarks")
    assert js.index("if (!resp.ok) return;", render_idx) \
        < js.index("bookmarks = bookmarks.filter", render_idx)


def test_shelf_and_open_hooks_in_reading_script(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    assert "function toggleShelf" in js
    assert "/open" in js
    assert "/api/shelf/" in js
