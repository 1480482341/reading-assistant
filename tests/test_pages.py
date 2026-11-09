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
    for path in ("/", "/library", "/review", "/shelf"):
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
    for needle in ("getBoundingClientRect", "scrollTo", "scrollHeight",
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


def test_library_has_annotation_filter_and_shelf_button(tmp_path):
    html = _html("/library", tmp_path)
    assert 'id="only-marked"' in html
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/library.js").text
    for needle in ("annotation_count", "bookmark_count", "only-marked", "shelf"):
        assert needle in js


def test_shelf_page_serves_with_two_tabs(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/shelf")
    assert r.status_code == 200
    assert 'data-tab="shelf"' in r.text
    assert 'data-tab="history"' in r.text
    assert 'id="shelf-list"' in r.text
    assert 'id="history-list"' in r.text


def test_all_pages_share_navigation(tmp_path):
    for path in ("/", "/library", "/review", "/shelf"):
        html = _html(path, tmp_path)
        for href in ('href="/"', 'href="/library"', 'href="/shelf"', 'href="/review"'):
            assert href in html


def test_drag_selection_suppresses_highlight_click_outside_color_mode(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    # Both mouseup branches (color mode and lookup mode) must arm the
    # suppress flag for a non-collapsed selection, so the trailing click on
    # a .hl span cannot hijack the lookup popup.
    assert js.count("suppressHlClick = true") >= 2
    assert "isCollapsed" in js


def test_annotation_offsets_count_code_points_not_utf16_units(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    # Offsets are stored as Python code points; every place the script
    # slices or measures paragraph text must use the code-point helpers.
    assert "const cpLength" in js
    assert "Array.from(s).slice" in js
    assert "cpSlice(para" in js
    assert "cpLength(p.textContent)" in js
    # The DOM offset handed to offsetInPara is UTF-16; convert it at the
    # text-node boundary before mixing it with code-point accumulation.
    assert "textContent.slice(0, offset)" in js


def test_add_bookmark_has_inflight_guard(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    add_idx = js.index("function addBookmark")
    # The guard must be set before the POST and always cleared in a finally,
    # so a double click cannot create two bookmarks.
    assert js.index("bookmarkPending", add_idx) < \
        js.index("bookmarkPending = true", add_idx)
    assert js.index("bookmarkPending = true", add_idx) < \
        js.index("finally", add_idx)
    assert js.index("finally", add_idx) < \
        js.index("bookmarkPending = false", add_idx)


def test_history_tab_disables_shelf_button_for_shelved_items(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/shelf.js").text
    # The history list resolves shelf state from the library listing and
    # renders a disabled button instead of offering to re-add an article.
    assert "已在书架" in js
    assert "in_shelf" in js
    assert " disabled" in js


def test_error_message_resets_color_mode_and_shelf_button(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    msg_idx = js.index("function showMessage")
    # showMessage is defined before the helpers it now calls; the resets
    # must sit inside its body.
    assert js.index("setColorMode(null)", msg_idx) < \
        js.index("function setColorMode")
    assert js.index("renderShelfButton()", msg_idx) < \
        js.index("function renderShelfButton")


def test_erase_highlight_mode_is_a_fourth_swatch(tmp_path):
    html = _html("/", tmp_path)
    assert 'data-color="erase"' in html
    db = str(tmp_path / "t.db")
    init_db(db).close()
    client = TestClient(create_app(db))
    js = client.get("/static/app.js").text
    assert "function eraseAnnotations" in js
    assert 'colorMode === "erase"' in js
    css = client.get("/static/style.css").text
    assert 'button.swatch[data-color="erase"]' in css


def test_pages_and_static_assets_are_not_cached(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    client = TestClient(create_app(db))
    for path in ("/", "/library", "/review", "/shelf", "/static/app.js",
                 "/static/style.css", "/static/theme.js"):
        assert client.get(path).headers.get("cache-control") == "no-store", path


def test_reading_sidebar_shows_and_groups_grammar_categories(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    for needle in ("cat-chip", "group-head", "item.category",
                   "item.grammar_category"):
        assert needle in js


def test_save_refetches_marks_instead_of_appending(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    assert "function loadMarks" in js
    save_idx = js.index("async function save")
    assert js.index("loadMarks()", save_idx) < js.index("hidePopup()", save_idx)
    assert "addToSidebar" not in js
