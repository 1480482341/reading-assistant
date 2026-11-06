# 阅读体验增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让长文可以"读到一半放下、下次接着读"——新增书签、彩色标色、书架与阅读历史，并把阅读页改成左操作 / 中正文 / 右信息三栏，配上四套可切换主题。

**Architecture:** 后端在现有 FastAPI + SQLite 上新增四张表（`annotations` / `bookmarks` / `shelf` / `reading_history`）与三个小模块，标记用"段落索引 + 段内字符偏移 + 原文片段"锚定。前端保持原生 JS 无构建，同一套 CSS 变量驱动四套主题，阅读页重排为三栏 grid。

**Tech Stack:** Python 3 / FastAPI / SQLite / pytest / 原生 HTML+CSS+JS

**Spec:** `docs/superpowers/specs/2026-11-06-reading-experience-design.md`

## Global Constraints

- 前端原生 JS，无 npm、无构建步骤；界面文案中文，代码与注释英文。
- 数据库单文件 SQLite，位置 `data/library.db`；结构变更用 `PRAGMA user_version` 门控，只跑一次。
- 标色与书签全程本地，不调用模型。
- 严格 RED→GREEN：先写失败测试，再实现。
- 每步提交前跑 `uv run pytest`，全量必须绿。
- 段落切分规则前后端一致：按 `\n+` 切分，逐段 `strip()`，丢弃空段。
- 颜色白名单固定为 `red` / `green` / `yellow`。
- 默认主题 `eye-green`；主题值只能是 `eye-green` / `dark` / `light` / `eye-warm`。
- Conventional Commits，提交信息用英文。

## Review Focus

1. **跨段选区**：用户从一段拖到下一段时，只标起点所在段落到段尾；不能抛异常，也不能整段消失。
2. **连续空行与首尾空白**：正文含 `\n\n\n` 或首尾空行时，段落索引必须稳定，否则所有标记整体错位。
3. **重叠标色**：同一段内新建标色与旧标色重叠时，后建者覆盖前建者；相邻但不相交的两个标色必须都保留。
4. **删除文章**：删掉文章后，其标注 / 书签 / 书架 / 历史必须一并消失，不能留下孤儿行。
5. **浏览器里被改坏的主题值**：`localStorage['ra-theme']` 为非法值时回落到 `eye-green`，页面不能因此不渲染。

---

### Task 1: 数据库 v2 结构与迁移

**Files:**
- Modify: `app/db.py`（`SCHEMA_VERSION`、`SCHEMA`）
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: 四张表 `annotations(id, article_id, para_index, start_offset, end_offset, quote, color, created_at)`、`bookmarks(id, article_id, para_index, offset_ratio, label, created_at)`、`shelf(article_id, added_at)`、`reading_history(article_id, open_count, first_opened, last_opened)`；`SCHEMA_VERSION == 2`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_db.py` 追加：

```python
def test_reading_annotation_tables_exist(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"annotations", "bookmarks", "shelf", "reading_history"} <= names


def test_schema_version_is_two(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_v1_database_upgrades_and_keeps_rows(tmp_path):
    p = tmp_path / "old.db"
    raw = sqlite3.connect(str(p))
    raw.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, text TEXT)")
    raw.execute("INSERT INTO articles(title, text) VALUES('Old', 'body')")
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()

    conn = init_db(str(p))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert conn.execute("SELECT title FROM articles").fetchone()["title"] == "Old"
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"annotations", "bookmarks", "shelf", "reading_history"} <= names


def test_deleting_article_cascades_marks(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(id,url,title,text) VALUES(1,'u','t','body')")
    conn.execute("INSERT INTO annotations(article_id,para_index,start_offset,"
                 "end_offset,quote,color) VALUES(1,0,0,4,'body','red')")
    conn.execute("INSERT INTO bookmarks(article_id,para_index,offset_ratio,label) "
                 "VALUES(1,0,0.5,'body')")
    conn.execute("INSERT INTO shelf(article_id) VALUES(1)")
    conn.execute("INSERT INTO reading_history(article_id,open_count) VALUES(1,1)")
    conn.commit()
    conn.execute("DELETE FROM articles WHERE id = 1")
    conn.commit()
    for table in ("annotations", "bookmarks", "shelf", "reading_history"):
        assert conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL —— `test_reading_annotation_tables_exist` 等报缺少表。

- [ ] **Step 3: 实现**

`app/db.py` 里把 `SCHEMA_VERSION = 1` 改为 `2`，在 `SCHEMA` 末尾（`settings` 表之后）追加：

```sql
CREATE TABLE IF NOT EXISTS annotations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id   INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    para_index   INTEGER NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset   INTEGER NOT NULL,
    quote        TEXT NOT NULL,
    color        TEXT NOT NULL,
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_annotations_article ON annotations(article_id);

CREATE TABLE IF NOT EXISTS bookmarks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id   INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    para_index   INTEGER NOT NULL,
    offset_ratio REAL DEFAULT 0,
    label        TEXT DEFAULT '',
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_article ON bookmarks(article_id);

CREATE TABLE IF NOT EXISTS shelf (
    article_id INTEGER PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    added_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reading_history (
    article_id   INTEGER PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    open_count   INTEGER DEFAULT 1,
    first_opened TEXT,
    last_opened  TEXT
);
```

`init_db` 的版本门控无需改动：`executescript(SCHEMA)` 已建表，`user_version` 自动升到 2。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_db.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add annotation, bookmark, shelf and history tables"
```

---

### Task 2: 段落切分与标色核心

**Files:**
- Create: `app/annotations.py`
- Test: `tests/test_annotations.py`

**Interfaces:**
- Produces:
  - `COLORS: tuple[str, ...] = ("red", "green", "yellow")`
  - `split_paragraphs(text: str) -> list[str]`
  - `add_annotation(conn, article_id: int, para_index: int, start_offset: int, end_offset: int, quote: str, color: str) -> int`
  - `list_annotations(conn, article_id: int) -> list[dict]`（每项含 `id, para_index, start_offset, end_offset, quote, color`）
  - `update_annotation_color(conn, annotation_id: int, color: str) -> bool`
  - `delete_annotation(conn, annotation_id: int) -> bool`
- 规则：`add_annotation` 在区间非法、颜色不在白名单、段落索引越界时抛 `ValueError`；新建前删除同段内区间重叠的旧标色（`end > other_start and start < other_end`）。

- [ ] **Step 1: 写失败测试**

`tests/test_annotations.py`：

```python
import pytest

from app.annotations import (add_annotation, delete_annotation, list_annotations,
                             split_paragraphs, update_annotation_color)
from app.db import init_db

TEXT = "First paragraph here.\n\nSecond paragraph.\n\n\nThird one."


def _conn(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(id,url,title,text) VALUES(1,'u','t',?)", (TEXT,))
    conn.commit()
    return conn


def test_split_paragraphs_drops_blank_lines():
    assert split_paragraphs(TEXT) == [
        "First paragraph here.", "Second paragraph.", "Third one."]


def test_split_paragraphs_ignores_surrounding_whitespace():
    assert split_paragraphs("\n\n  a  \n\n  b \n\n") == ["a", "b"]


def test_add_and_list_roundtrip(tmp_path):
    conn = _conn(tmp_path)
    aid = add_annotation(conn, 1, 1, 0, 6, "Second", "green")
    rows = list_annotations(conn, 1)
    assert len(rows) == 1
    assert rows[0]["id"] == aid
    assert rows[0]["color"] == "green"
    assert rows[0]["quote"] == "Second"


def test_overlapping_annotation_replaces_previous(tmp_path):
    conn = _conn(tmp_path)
    add_annotation(conn, 1, 0, 0, 10, "First para", "red")
    add_annotation(conn, 1, 0, 5, 15, "para here.", "yellow")
    rows = list_annotations(conn, 1)
    assert len(rows) == 1
    assert rows[0]["color"] == "yellow"


def test_adjacent_annotations_are_both_kept(tmp_path):
    conn = _conn(tmp_path)
    add_annotation(conn, 1, 0, 0, 5, "First", "red")
    add_annotation(conn, 1, 0, 5, 10, " para", "green")
    assert len(list_annotations(conn, 1)) == 2


def test_annotations_in_different_paragraphs_do_not_collide(tmp_path):
    conn = _conn(tmp_path)
    add_annotation(conn, 1, 0, 0, 5, "First", "red")
    add_annotation(conn, 1, 1, 0, 6, "Second", "red")
    assert len(list_annotations(conn, 1)) == 2


def test_invalid_color_rejected(tmp_path):
    with pytest.raises(ValueError):
        add_annotation(_conn(tmp_path), 1, 0, 0, 5, "First", "purple")


def test_invalid_range_rejected(tmp_path):
    with pytest.raises(ValueError):
        add_annotation(_conn(tmp_path), 1, 0, 5, 5, "", "red")


def test_paragraph_index_out_of_range_rejected(tmp_path):
    with pytest.raises(ValueError):
        add_annotation(_conn(tmp_path), 1, 9, 0, 5, "x", "red")


def test_quote_mismatch_is_dropped_on_read(tmp_path):
    conn = _conn(tmp_path)
    add_annotation(conn, 1, 0, 0, 9, "NOPE", "red")
    assert list_annotations(conn, 1) == []


def test_update_color_and_delete(tmp_path):
    conn = _conn(tmp_path)
    aid = add_annotation(conn, 1, 0, 0, 5, "First", "red")
    assert update_annotation_color(conn, aid, "yellow") is True
    assert list_annotations(conn, 1)[0]["color"] == "yellow"
    assert delete_annotation(conn, aid) is True
    assert list_annotations(conn, 1) == []
    assert delete_annotation(conn, aid) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_annotations.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.annotations'`。

- [ ] **Step 3: 实现 `app/annotations.py`**

```python
COLORS = ("red", "green", "yellow")

def split_paragraphs(text: str) -> list[str]:
    """Split on blank-line runs and drop empty paragraphs."""

def add_annotation(conn, article_id, para_index, start_offset, end_offset,
                   quote, color) -> int: ...
def list_annotations(conn, article_id) -> list[dict]: ...
def update_annotation_color(conn, annotation_id, color) -> bool: ...
def delete_annotation(conn, annotation_id) -> bool: ...
```

实现要点：
- `split_paragraphs` 用 `re.split(r"\n+", text)`，每段 `strip()`，过滤空串。
- `add_annotation` 先取该文章正文并切段校验 `0 <= para_index < len(paras)`；校验 `color in COLORS`、`0 <= start_offset < end_offset`；然后在同一事务里删除同文章同段的重叠行，再插入并 `commit()`，返回新 id。
- `list_annotations` 取该文正文切段，对每行校验 `paras[para_index][start:end].strip() == quote.strip()` 且区间未越界；不匹配的行用 `logging.getLogger(__name__).warning("dropping stale annotation %s", id)` 记录后跳过。
- `update_annotation_color`：颜色非法抛 `ValueError`；返回 `rowcount > 0`。
- 全部函数执行后 `conn.commit()`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_annotations.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/annotations.py tests/test_annotations.py
git commit -m "feat: add paragraph-based annotation store"
```

---

### Task 3: 标色 API

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_annotations_api.py`

**Interfaces:**
- Consumes: Task 2 的 `add_annotation` / `list_annotations` / `update_annotation_color` / `delete_annotation`。
- Produces: `GET/POST /api/articles/{id}/annotations`、`PATCH/DELETE /api/annotations/{id}`。

- [ ] **Step 1: 写失败测试**

`tests/test_annotations_api.py`：

```python
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app

TEXT = "First paragraph here.\n\nSecond paragraph."


def _client(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','t',?,'ready')", (TEXT,))
    conn.commit()
    conn.close()
    return TestClient(create_app(db))


def test_create_and_list_annotation(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/articles/1/annotations", json={
        "para_index": 0, "start_offset": 0, "end_offset": 5,
        "quote": "First", "color": "red"})
    assert r.status_code == 200
    rows = c.get("/api/articles/1/annotations").json()
    assert len(rows) == 1 and rows[0]["color"] == "red"


def test_invalid_color_returns_422(tmp_path):
    r = _client(tmp_path).post("/api/articles/1/annotations", json={
        "para_index": 0, "start_offset": 0, "end_offset": 5,
        "quote": "First", "color": "purple"})
    assert r.status_code == 422


def test_unknown_article_returns_404(tmp_path):
    r = _client(tmp_path).post("/api/articles/99/annotations", json={
        "para_index": 0, "start_offset": 0, "end_offset": 5,
        "quote": "First", "color": "red"})
    assert r.status_code == 404


def test_patch_color_and_delete(tmp_path):
    c = _client(tmp_path)
    aid = c.post("/api/articles/1/annotations", json={
        "para_index": 0, "start_offset": 0, "end_offset": 5,
        "quote": "First", "color": "red"}).json()["id"]
    assert c.patch(f"/api/annotations/{aid}", json={"color": "green"}).status_code == 200
    assert c.get("/api/articles/1/annotations").json()[0]["color"] == "green"
    assert c.delete(f"/api/annotations/{aid}").status_code == 200
    assert c.get("/api/articles/1/annotations").json() == []


def test_delete_missing_annotation_returns_404(tmp_path):
    assert _client(tmp_path).delete("/api/annotations/999").status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_annotations_api.py -v`
Expected: 404（路由不存在）。

- [ ] **Step 3: 实现路由**

在 `app/main.py` 增加 Pydantic body：

```python
class AnnotationBody(BaseModel):
    para_index: int
    start_offset: int
    end_offset: int
    quote: str = ""
    color: str


class AnnotationColorBody(BaseModel):
    color: str
```

在 `create_app` 内、`/api/articles/library` 之后、`/api/articles/{article_id:int}` **之前**注册带子路径的 POST（FastAPI 对子路径不冲突，但保持顺序一致便于阅读）：

```python
@app.get("/api/articles/{article_id}/annotations")
@app.post("/api/articles/{article_id}/annotations")
@app.patch("/api/annotations/{annotation_id}")
@app.delete("/api/annotations/{annotation_id}")
```

具体行为：
- POST 先确认文章存在（`SELECT 1 FROM articles WHERE id=?`），不存在 → 404；调用 `add_annotation`，捕获 `ValueError` → `HTTPException(422, str(exc))`；返回 `{"id": new_id}`。
- GET 返回 `list_annotations`。
- PATCH 捕获 `ValueError` → 422；`False` → 404；返回 `{"ok": True}`。
- DELETE 返回 `False` 时 404，否则 `{"ok": True}`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_annotations_api.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/main.py tests/test_annotations_api.py
git commit -m "feat: expose annotation endpoints"
```

---

### Task 4: 书签核心与 API

**Files:**
- Create: `app/bookmarks.py`
- Modify: `app/main.py`
- Test: `tests/test_bookmarks.py`

**Interfaces:**
- Produces:
  - `add_bookmark(conn, article_id: int, para_index: int, offset_ratio: float, label: str) -> int`
  - `list_bookmarks(conn, article_id: int) -> list[dict]`（`id, para_index, offset_ratio, label, created_at`，按 `created_at, id` 升序）
  - `delete_bookmark(conn, bookmark_id: int) -> bool`
  - `GET/POST /api/articles/{id}/bookmarks`、`DELETE /api/bookmarks/{id}`
- 规则：`offset_ratio` 夹到 `[0.0, 1.0]`；`para_index` 越界抛 `ValueError`；`label` 截断到 80 字。

- [ ] **Step 1: 写失败测试**

`tests/test_bookmarks.py`：

```python
import pytest
from fastapi.testclient import TestClient

from app.bookmarks import add_bookmark, delete_bookmark, list_bookmarks
from app.db import init_db
from app.main import create_app

TEXT = "First paragraph here.\n\nSecond paragraph."


def _conn(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(id,url,title,text) VALUES(1,'u','t',?)", (TEXT,))
    conn.commit()
    return conn


def test_add_and_list_bookmarks_in_order(tmp_path):
    conn = _conn(tmp_path)
    first = add_bookmark(conn, 1, 0, 0.25, "First paragraph")
    second = add_bookmark(conn, 1, 1, 0.0, "Second paragraph")
    rows = list_bookmarks(conn, 1)
    assert [r["id"] for r in rows] == [first, second]
    assert rows[0]["offset_ratio"] == 0.25


def test_offset_ratio_is_clamped(tmp_path):
    conn = _conn(tmp_path)
    add_bookmark(conn, 1, 0, 5.0, "x")
    add_bookmark(conn, 1, 0, -1.0, "y")
    ratios = [r["offset_ratio"] for r in list_bookmarks(conn, 1)]
    assert ratios == [1.0, 0.0]


def test_label_is_truncated_to_80_chars(tmp_path):
    conn = _conn(tmp_path)
    add_bookmark(conn, 1, 0, 0.0, "z" * 200)
    assert len(list_bookmarks(conn, 1)[0]["label"]) == 80


def test_para_index_out_of_range_rejected(tmp_path):
    with pytest.raises(ValueError):
        add_bookmark(_conn(tmp_path), 1, 7, 0.0, "x")


def test_delete_bookmark_returns_false_when_missing(tmp_path):
    assert delete_bookmark(_conn(tmp_path), 999) is False


def test_bookmark_api_roundtrip(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','t',?,'ready')", (TEXT,))
    conn.commit()
    conn.close()
    c = TestClient(create_app(db))
    bid = c.post("/api/articles/1/bookmarks",
                 json={"para_index": 1, "offset_ratio": 0.5, "label": "Second"}).json()["id"]
    rows = c.get("/api/articles/1/bookmarks").json()
    assert rows[0]["label"] == "Second"
    assert c.delete(f"/api/bookmarks/{bid}").status_code == 200
    assert c.get("/api/articles/1/bookmarks").json() == []


def test_bookmark_for_unknown_article_returns_404(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    c = TestClient(create_app(db))
    assert c.post("/api/articles/9/bookmarks",
                  json={"para_index": 0, "offset_ratio": 0, "label": "x"}).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_bookmarks.py -v`
Expected: FAIL —— `No module named 'app.bookmarks'`。

- [ ] **Step 3: 实现**

`app/bookmarks.py` 复用 `app.annotations.split_paragraphs` 做段落越界校验。`app/main.py` 增加 `BookmarkBody(para_index: int, offset_ratio: float = 0, label: str = "")` 与三个路由，错误映射与 Task 3 一致（`ValueError` → 422，缺文章/缺书签 → 404）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_bookmarks.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/bookmarks.py app/main.py tests/test_bookmarks.py
git commit -m "feat: add bookmarks with API"
```

---

### Task 5: 书架与阅读历史

**Files:**
- Create: `app/shelf.py`
- Modify: `app/main.py`
- Test: `tests/test_shelf.py`

**Interfaces:**
- Produces:
  - `add_to_shelf(conn, article_id: int, now: str) -> None`（幂等）
  - `remove_from_shelf(conn, article_id: int) -> bool`
  - `shelf_rows(conn) -> list[dict]`（`id, title, title_zh, source, topic, status, added_at, annotation_count, bookmark_count`，按 `added_at` 倒序）
  - `record_open(conn, article_id: int, now: str) -> None`（首次插入 `open_count=1`；再次打开 `open_count+1` 并更新 `last_opened`）
  - `history_rows(conn) -> list[dict]`（`id, title, title_zh, source, topic, status, open_count, last_opened`，按 `last_opened` 倒序）
  - `in_shelf(conn, article_id: int) -> bool`
  - 路由：`GET /api/shelf`、`POST/DELETE /api/shelf/{id}`、`GET /api/history`、`POST /api/articles/{id}/open`

- [ ] **Step 1: 写失败测试**

`tests/test_shelf.py`：

```python
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app
from app.shelf import add_to_shelf, in_shelf, record_open, remove_from_shelf

NOW = "2026-11-06T10:00:00"


def _conn(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','One','body','ready')")
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(2,'u2','Two','body','read')")
    conn.commit()
    return conn


def test_add_to_shelf_is_idempotent(tmp_path):
    conn = _conn(tmp_path)
    add_to_shelf(conn, 1, NOW)
    add_to_shelf(conn, 1, NOW)
    assert conn.execute("SELECT COUNT(*) AS c FROM shelf").fetchone()["c"] == 1
    assert in_shelf(conn, 1) is True


def test_remove_from_shelf(tmp_path):
    conn = _conn(tmp_path)
    add_to_shelf(conn, 1, NOW)
    assert remove_from_shelf(conn, 1) is True
    assert remove_from_shelf(conn, 1) is False
    assert in_shelf(conn, 1) is False


def test_record_open_counts_and_updates_last_opened(tmp_path):
    conn = _conn(tmp_path)
    record_open(conn, 1, "2026-11-01T09:00:00")
    record_open(conn, 1, "2026-11-02T09:00:00")
    row = conn.execute("SELECT * FROM reading_history WHERE article_id=1").fetchone()
    assert row["open_count"] == 2
    assert row["first_opened"] == "2026-11-01T09:00:00"
    assert row["last_opened"] == "2026-11-02T09:00:00"


def test_shelf_and_history_api(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','One','body','ready')")
    conn.commit()
    conn.close()
    c = TestClient(create_app(db))
    assert c.post("/api/shelf/1").status_code == 200
    shelf = c.get("/api/shelf").json()
    assert shelf[0]["id"] == 1 and shelf[0]["annotation_count"] == 0
    assert c.delete("/api/shelf/1").status_code == 200
    assert c.get("/api/shelf").json() == []

    assert c.post("/api/articles/1/open").status_code == 200
    hist = c.get("/api/history").json()
    assert hist[0]["id"] == 1 and hist[0]["open_count"] == 1


def test_shelf_unknown_article_returns_404(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    c = TestClient(create_app(db))
    assert c.post("/api/shelf/9").status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_shelf.py -v`
Expected: FAIL —— `No module named 'app.shelf'`。

- [ ] **Step 3: 实现**

`shelf_rows` / `history_rows` 用相关子查询统计 `annotations` 与 `bookmarks` 数量；时间戳由调用方传入（便于测试），路由里用 `datetime.now().isoformat(timespec="seconds")`。`POST /api/shelf/{id}` 与 `POST /api/articles/{id}/open` 先校验文章存在，否则 404。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_shelf.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/shelf.py app/main.py tests/test_shelf.py
git commit -m "feat: add shelf and reading history"
```

---

### Task 6: 文章库计数、文章详情扩充、右栏数据接口

**Files:**
- Modify: `app/library.py`、`app/main.py`
- Test: `tests/test_library_api.py`、`tests/test_api.py`

**Interfaces:**
- Produces:
  - `library_rows` 每行新增 `in_shelf: bool`、`annotation_count: int`、`bookmark_count: int`、`occurrence_count: int`
  - `GET /api/articles/{id}/marks` → `{"occurrences": [{"term","gloss_zh","grammar_role","why"}...], "grammar": [...]}`
  - `GET /api/articles/{id}` 新增 `in_shelf: bool`、`annotations: list[dict]`、`bookmarks: list[dict]`
- 定义：`occurrences` 取 `entries.kind != 'grammar'` 的行；`grammar` 取 `entries.kind == 'grammar'` 的行。

- [ ] **Step 1: 写失败测试**

在 `tests/test_library_api.py` 追加：

```python
def test_library_rows_expose_mark_counts_and_shelf_flag(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','T','First.\n\nSecond.','ready')")
    conn.execute("INSERT INTO annotations(article_id,para_index,start_offset,"
                 "end_offset,quote,color) VALUES(1,0,0,5,'First','red')")
    conn.execute("INSERT INTO bookmarks(article_id,para_index,offset_ratio,label) "
                 "VALUES(1,1,0,'Second')")
    conn.execute("INSERT INTO shelf(article_id) VALUES(1)")
    conn.commit()
    conn.close()
    row = TestClient(create_app(db)).get("/api/articles/library").json()[0]
    assert row["annotation_count"] == 1
    assert row["bookmark_count"] == 1
    assert row["in_shelf"] is True
```

在 `tests/test_api.py` 追加：

```python
def test_article_detail_includes_marks_and_shelf(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','t','First.\n\nSecond.','ready')")
    conn.execute("INSERT INTO annotations(article_id,para_index,start_offset,"
                 "end_offset,quote,color) VALUES(1,0,0,5,'First','red')")
    conn.execute("INSERT INTO bookmarks(article_id,para_index,offset_ratio,label) "
                 "VALUES(1,1,0.5,'Second')")
    conn.execute("INSERT INTO shelf(article_id) VALUES(1)")
    conn.commit()
    conn.close()
    body = TestClient(create_app(db)).get("/api/articles/1").json()
    assert body["in_shelf"] is True
    assert body["annotations"][0]["color"] == "red"
    assert body["bookmarks"][0]["offset_ratio"] == 0.5


def test_marks_endpoint_splits_words_and_grammar(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','t','body','ready')")
    conn.execute("INSERT INTO entries(id,kind,lemma) VALUES(1,'word','albeit')")
    conn.execute("INSERT INTO entries(id,kind,lemma) VALUES(2,'grammar','inversion')")
    conn.execute("INSERT INTO occurrences(entry_id,article_id,sentence,surface,gloss)"
                 " VALUES(1,1,'s','albeit','尽管')")
    conn.execute("INSERT INTO occurrences(entry_id,article_id,sentence,surface,gloss)"
                 " VALUES(2,1,'s','never have I','倒装')")
    conn.commit()
    conn.close()
    body = TestClient(create_app(db)).get("/api/articles/1/marks").json()
    assert [o["term"] for o in body["occurrences"]] == ["albeit"]
    assert [o["term"] for o in body["grammar"]] == ["inversion"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_library_api.py tests/test_api.py -v`
Expected: FAIL —— 缺 key 或 404。

- [ ] **Step 3: 实现**

`app/library.py` 的 SQL 改为带相关子查询：

```sql
SELECT a.id, a.title, a.title_zh, a.topic, a.source, a.published_at,
       a.word_count, a.status,
       EXISTS(SELECT 1 FROM shelf s WHERE s.article_id = a.id) AS in_shelf,
       (SELECT COUNT(*) FROM annotations x WHERE x.article_id = a.id) AS annotation_count,
       (SELECT COUNT(*) FROM bookmarks b WHERE b.article_id = a.id) AS bookmark_count,
       (SELECT COUNT(*) FROM occurrences o WHERE o.article_id = a.id) AS occurrence_count
FROM articles a ORDER BY a.published_at DESC, a.id DESC
```

`in_shelf` 在返回时转成 `bool(row["in_shelf"])`。

`app/main.py`：`article_detail` 追加三次查询（`in_shelf`、`list_annotations`、`list_bookmarks`）；新增 `/api/articles/{article_id}/marks`，用一条 JOIN 查询取 `entries.kind, entries.lemma, occurrences.gloss, grammar_role, why`，按 `kind` 分到两个列表，每项字段名为 `term / gloss_zh / grammar_role / why`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_library_api.py tests/test_api.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/library.py app/main.py tests/test_library_api.py tests/test_api.py
git commit -m "feat: expose mark counts and article marks"
```

---

### Task 7: 四套主题与顶栏切换

**Files:**
- Modify: `web/style.css`、`web/library.css`、`web/review.css`
- Create: `web/theme.js`
- Modify: `web/index.html`、`web/library.html`、`web/review.html`
- Test: `tests/test_pages.py`

**Interfaces:**
- Produces: `<html data-theme="eye-green|dark|light|eye-warm">`；共享脚本 `/static/theme.js`；顶栏按钮 `#theme-toggle`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_pages.py` 追加：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL —— 找不到主题选择器与按钮。

- [ ] **Step 3: 实现**

`web/style.css` 顶部：

```css
:root, [data-theme="light"] { --ink:#1b1b1b; --muted:#6b6b6b; --line:#e3e0da;
  --accent:#2f6fd0; --bg:#faf9f6; --panel:#ffffff; --on-accent:#ffffff;
  --banner-bg:#fdf3d8; --banner-ink:#6b4e00; }
[data-theme="eye-green"] { --ink:#22301f; --muted:#5c6b57; --line:#bfd3b7;
  --accent:#3f7a3a; --bg:#d6e8d0; --panel:#e6f1e1; --on-accent:#ffffff;
  --banner-bg:#f3e9c4; --banner-ink:#5c4a12; }
[data-theme="dark"] { --ink:#dfe3e8; --muted:#8b939e; --line:#2b3038;
  --accent:#6ea8fe; --bg:#14161a; --panel:#1c1f24; --on-accent:#0b0d10;
  --banner-bg:#3a3016; --banner-ink:#e8d9a8; }
[data-theme="eye-warm"] { --ink:#33291b; --muted:#7a6a52; --line:#e0d2b8;
  --accent:#a4632a; --bg:#f5e9c8; --panel:#fcf4e0; --on-accent:#ffffff;
  --banner-bg:#f0dfae; --banner-ink:#5c4a1a; }
```

把 `.banner` 的 `#fdf3d8/#e8d8a8/#6b4e00` 与按钮的 `#fff` 替换为变量；`web/library.css:41`、`web/review.css:60` 的 `#fff` 改为 `var(--on-accent)`。

`web/theme.js`：

```js
const THEMES = ["eye-green", "dark", "light", "eye-warm"];
const THEME_LABELS = { "eye-green": "护眼绿", "dark": "暗黑", "light": "浅色", "eye-warm": "暖黄" };
// 读取 currentTheme()，点击 #theme-toggle 时循环到下一个并写 localStorage['ra-theme']
```

每个页面 `<head>` 末尾加内联脚本（防闪烁，反目标 4）：

```html
<script>
(function () {
  var t = localStorage.getItem("ra-theme");
  if (["eye-green","dark","light","eye-warm"].indexOf(t) < 0) t = "eye-green";
  document.documentElement.dataset.theme = t;
})();
</script>
```

每个页面顶栏加 `<button id="theme-toggle" class="theme-toggle">护眼绿</button>`，并在页面脚本之前引入 `<script src="/static/theme.js"></script>`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add web/style.css web/library.css web/review.css web/theme.js web/index.html web/library.html web/review.html tests/test_pages.py
git commit -m "feat: add four switchable themes"
```

---

### Task 8: 阅读页三栏布局与滚动修复

**Files:**
- Modify: `web/index.html`、`web/style.css`
- Test: `tests/test_pages.py`

**Interfaces:**
- Produces: `aside.actions`（左）、`section.reader`（中）、`aside.sidebar`（右）；`#add-bookmark`、`#bookmark-list`、三个 `.swatch[data-color]`、`#mark-read`、`#shelf-toggle`。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

`web/index.html` 的 `<main class="layout">` 改为：

```html
<main class="layout">
  <aside class="actions">
    <div class="actions-ops">
      <div class="side-head">书签</div>
      <button id="add-bookmark">＋ 书签</button>
      <ul id="bookmark-list"></ul>
      <div class="side-head">标色</div>
      <div class="swatches">
        <button class="swatch" data-color="red" title="标红"></button>
        <button class="swatch" data-color="green" title="标绿"></button>
        <button class="swatch" data-color="yellow" title="标黄"></button>
      </div>
      <div class="side-head">操作</div>
      <button id="shelf-toggle">加入书架</button>
      <button id="mark-read">读完了</button>
    </div>
  </aside>
  <section class="reader">…原内容不变…</section>
  <aside class="sidebar" id="sidebar">…原内容不变…</aside>
</main>
```

删除顶栏里原来的 `<a href="#" id="mark-read">读完了</a>`。

`web/style.css`：

```css
.layout { grid-template-columns: 176px minmax(0, 1fr) 280px; gap: 32px; align-items: start; }
.actions, .sidebar { position: sticky; top: 24px; max-height: calc(100vh - 48px); overflow-y: auto; }
.actions { border-right: 1px solid var(--line); padding-right: 16px; }
.sidebar { border-left: 1px solid var(--line); padding-left: 20px; }
```

窄屏媒体查询（`max-width: 900px`）下改为单列堆叠，`position: static; max-height: none;`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add web/index.html web/style.css tests/test_pages.py
git commit -m "feat: three-column reading layout with scrolling sidebar"
```

---

### Task 9: 正文高亮渲染与右栏复原

**Files:**
- Modify: `web/app.js`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `GET /api/articles/{id}`（含 `annotations` / `bookmarks` / `in_shelf`）、`GET /api/articles/{id}/marks`。
- Produces（供后续任务使用）：
  - `let annotations = []`、`let bookmarks = []`
  - `function paragraphs() -> string[]`
  - `function renderBody() -> void`（重建 `<p>` 并写入 `.hl.hl-<color>` 元素，每个高亮带 `data-annotation-id`）
  - `function renderRightPanel(marks) -> void`

- [ ] **Step 1: 写失败测试**

```python
def test_reading_script_renders_annotations_and_loads_marks(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    for needle in ("function paragraphs", "function renderBody",
                   "hl-", "data-annotation-id", "/marks"):
        assert needle in js
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

在 `web/app.js` 中：

- `paragraphs()`：`full.text.split(/\n+/).map(s => s.trim()).filter(Boolean)`。
- `renderBody()`：清空 `bodyEl`，逐段建 `<p data-para="i">`；对每段取该段标色（按 `start_offset` 升序，重叠已在后端消除），切分成片段数组，逐片段 `escapeHtml`，高亮片段包成 `<span class="hl hl-${color}" data-annotation-id="${id}">`。
- `showArticle()` 改为保存 `full`、设置 `annotations = full.annotations || []`、`bookmarks = full.bookmarks || []`，调用 `renderBody()`，再 `fetch('/api/articles/' + full.id + '/marks')` 填充右栏两个列表（复用 `addToSidebar` 的样式，抽成 `appendMark(listEl, item)`）。
- 标色 CSS（`web/style.css`）：`.hl { border-radius: 2px; padding: 0 1px; } .hl-red{background:rgba(220,70,70,.30)} .hl-green{background:rgba(60,170,90,.30)} .hl-yellow{background:rgba(230,180,40,.35)}`；暗色主题下各色透明度降到 `.22`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS。

- [ ] **Step 5: 手动验证**

启动 `uv run uvicorn app.main:app --port 8000`，用库里已有文章确认：正文正常分段、无控制台报错、右栏打开即有词条（此前需要点"记下来"才出现）。

- [ ] **Step 6: 提交**

```bash
git add web/app.js web/style.css tests/test_pages.py
git commit -m "feat: render stored annotations and restore right panel"
```

---

### Task 10: 标色模式与选区换算

**Files:**
- Modify: `web/app.js`、`web/style.css`
- Test: `tests/test_pages.py`

**Interfaces:**
- Produces:
  - `let colorMode = null`
  - `function selectionToRange(sel) -> {paraIndex, start, end} | null`（跨段时 `end` 截到起点段末尾）
  - `function applyAnnotation(range, color) -> void`
  - 点击高亮元素弹出 `#hl-popup`，提供改色与取消。

- [ ] **Step 1: 写失败测试**

```python
def test_color_mode_and_selection_mapping(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    for needle in ("colorMode", "selectionToRange", "applyAnnotation",
                   "/annotations", "hl-popup"):
        assert needle in js
    html = TestClient(create_app(db)).get("/").text
    assert 'id="hl-popup"' in html
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

- 点击 `.swatch`: 若 `colorMode === 该色` 则退出（清 `.active`），否则设为该色并给该色块加 `.active`。
- `document.addEventListener("keydown")` 里 Esc 退出标色模式并关闭 `#hl-popup`。
- `mouseup` 处理改为：若 `colorMode` 非空且选区在 `bodyEl` 内 → 调 `selectionToRange`，`POST /api/articles/{id}/annotations`，成功后把返回行 push 进 `annotations`，`renderBody()`，保持标色模式；期间**不调用** `onSelect()`。
- `selectionToRange`：取 `range.startContainer` 最近的 `<p>` 作为起点段；用 `TreeWalker` 累加其前序文本节点长度得到 `start`；若 `range.endContainer` 不在同一 `<p>`，`end = p.textContent.length`，否则同样累加得到 `end`。返回 `null` 当 `start === end`。
- `#hl-popup` 元素放进 `index.html`，结构与现有 `.popup` 类似：三个色块按钮 + 「取消标色」；定位到被点击的高亮处。
- 点击高亮：`PATCH /api/annotations/{id}` 改色或 `DELETE` 取消，成功后更新本地数组并 `renderBody()`。
- 点击空白关闭 `#hl-popup`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS。

- [ ] **Step 5: 手动验证**

点红 → 划选一句 → 立即变红且不弹释义框；再划一句仍是红色；Esc 后划词恢复弹释义框；点已高亮的句子可改色/取消；刷新后标色仍在。

跨段选区：从一段末尾拖到下一段中间，松手后只有起点段到段尾被标色，下一段不受影响、页面不报错。

- [ ] **Step 6: 提交**

```bash
git add web/app.js web/style.css web/index.html tests/test_pages.py
git commit -m "feat: add color mode for highlighting selections"
```

---

### Task 11: 书签增删与跳转

**Files:**
- Modify: `web/app.js`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `GET/POST /api/articles/{id}/bookmarks`、`DELETE /api/bookmarks/{id}`。
- Produces: `function renderBookmarks()`、`function currentBookmarkAnchor()`、`function addBookmark()`、`function jumpToBookmark(bm)`。

- [ ] **Step 1: 写失败测试**

```python
def test_bookmark_functions_present(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    for needle in ("function renderBookmarks", "function addBookmark",
                   "function jumpToBookmark", "/bookmarks"):
        assert needle in js
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

- `currentBookmarkAnchor()`：遍历 `bodyEl` 的 `<p>`，取第一个 `getBoundingClientRect().top >= topbar 高度` 的段落下标；`offset_ratio = clamp((视口顶 - rect.top) / rect.height, 0, 1)`；`label = p.textContent.slice(0, 40)`。
- `addBookmark()`：`POST` 后 push 到 `bookmarks` 并 `renderBookmarks()`。
- `renderBookmarks()`：清空 `#bookmark-list`，每项 `<li><button class="bm-jump">label</button><button class="bm-del">×</button></li>`。
- `jumpToBookmark(bm)`：`p.scrollIntoView({block: "start"})`，再 `window.scrollBy(0, -topbarHeight + bm.offset_ratio * p.offsetHeight)`。
- 删除调用 `DELETE` 并从本地数组移除。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS。

- [ ] **Step 5: 手动验证**

滚动到中段加书签 → 列表出现 → 滚回顶部点书签 → 回到原位置（误差小于半屏）→ 刷新后书签仍在 → 删除后消失。

- [ ] **Step 6: 提交**

```bash
git add web/app.js tests/test_pages.py
git commit -m "feat: add bookmarks with jump and delete"
```

---

### Task 12: 阅读页的书架按钮与打开记录

**Files:**
- Modify: `web/app.js`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `POST/DELETE /api/shelf/{id}`、`POST /api/articles/{id}/open`、文章详情里的 `in_shelf`。
- Produces: `function toggleShelf()`；页面加载完成后调用一次 `recordOpen()`。

- [ ] **Step 1: 写失败测试**

```python
def test_shelf_and_open_hooks_in_reading_script(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/app.js").text
    assert "function toggleShelf" in js
    assert "/open" in js
    assert "/api/shelf/" in js
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

- `showArticle()` 里按 `full.in_shelf` 把 `#shelf-toggle` 文本设为「已在书架」或「加入书架」。
- `toggleShelf()`：在书架则 `DELETE`，否则 `POST`；成功后翻转状态与按钮文本，失败时保留原状态。
- `loadArticle()` 成功拿到文章后 `POST /api/articles/{id}/open`（失败忽略，不影响阅读）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add web/app.js tests/test_pages.py
git commit -m "feat: add shelf toggle and open tracking"
```

---

### Task 13: 文章库角标、书架按钮与「有标注」筛选

**Files:**
- Modify: `web/library.html`、`web/library.js`、`web/library.css`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `library_rows` 的 `in_shelf / annotation_count / bookmark_count / occurrence_count`、`POST/DELETE /api/shelf/{id}`。

- [ ] **Step 1: 写失败测试**

```python
def test_library_has_annotation_filter_and_shelf_button(tmp_path):
    html = _html("/library", tmp_path)
    assert 'id="only-marked"' in html
    db = str(tmp_path / "t.db")
    init_db(db).close()
    js = TestClient(create_app(db)).get("/static/library.js").text
    for needle in ("annotation_count", "bookmark_count", "only-marked", "shelf"):
        assert needle in js
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

- `library.html` 的状态筛选后加一行 `<label class="filter-marked"><input type="checkbox" id="only-marked"> 只看有标注的</label>`。
- `library.js`：`state.onlyMarked`；`matches()` 里追加 `!state.onlyMarked || (a.annotation_count + a.bookmark_count > 0)`；卡片 meta 行后追加 `<div class="marks">书签 ${n} · 标色 ${m} · 词条 ${k}</div>`；卡片内加 `<button class="shelf-btn">加入书架 / 已在书架</button>`，点击时 `stopPropagation()` 并调接口、翻转文本。
- `library.css` 补 `.marks`、`.shelf-btn`、`.filter-marked` 样式，颜色全部用变量。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS。

- [ ] **Step 5: 手动验证**

勾选「只看有标注的」后列表正确收窄；点「加入书架」不触发行跳转。

- [ ] **Step 6: 提交**

```bash
git add web/library.html web/library.js web/library.css tests/test_pages.py
git commit -m "feat: show mark counts and shelf toggle in library"
```

---

### Task 14: 书架页

**Files:**
- Create: `web/shelf.html`、`web/shelf.js`、`web/shelf.css`
- Modify: `app/main.py`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `GET /api/shelf`、`GET /api/history`、`POST/DELETE /api/shelf/{id}`。
- Produces: 路由 `GET /shelf` 返回 `web/shelf.html`。

- [ ] **Step 1: 写失败测试**

```python
def test_shelf_page_serves_with_two_tabs(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/shelf")
    assert r.status_code == 200
    assert 'data-tab="shelf"' in r.text
    assert 'data-tab="history"' in r.text
    assert 'id="shelf-list"' in r.text
    assert 'id="history-list"' in r.text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL —— 404。

- [ ] **Step 3: 实现**

- `app/main.py` 在 `/library` 后加：

```python
@app.get("/shelf")
def shelf_page():
    return FileResponse(WEB_DIR / "shelf.html")
```

- `web/shelf.html`：与其它页相同的顶栏（含主题按钮与主题脚本），主体两个标签按钮与两个 `<ul>`。
- `web/shelf.js`：加载两个接口；每个 li 显示标题（`title_zh || title`）、`source · status`、`书签 N · 标色 M`；书架项带「移出书架」，历史项显示 `打开 N 次 · 最后 YYYY-MM-DD` 并带「加入书架」。点击 li 跳 `/?id=N`。
- `web/shelf.css`：列表与标签样式，颜色全部用变量。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/main.py web/shelf.html web/shelf.js web/shelf.css tests/test_pages.py
git commit -m "feat: add shelf page with history tab"
```

---

### Task 15: 全站导航统一与收尾

**Files:**
- Modify: `web/index.html`、`web/library.html`、`web/review.html`、`web/shelf.html`
- Modify: `README.md`、`HANDOFF.md`
- Test: `tests/test_pages.py`

**Interfaces:**
- Produces: 四个页面顶栏一致：阅读 / 文章库 / 书架 / 复习 / 主题按钮 / 导出。

- [ ] **Step 1: 写失败测试**

```python
def test_all_pages_share_navigation(tmp_path):
    for path in ("/", "/library", "/review", "/shelf"):
        html = _html(path, tmp_path)
        for href in ('href="/"', 'href="/library"', 'href="/shelf"', 'href="/review"'):
            assert href in html
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL（部分页面缺 `/shelf`）。

- [ ] **Step 3: 实现**

四个页面顶栏统一为：

```html
<nav>
  <a href="/">阅读</a>
  <a href="/library">文章库</a>
  <a href="/shelf">书架</a>
  <a href="/review">复习</a>
  <button id="theme-toggle" class="theme-toggle">护眼绿</button>
  <a href="/api/export?format=md">导出</a>
</nav>
```

当前页保留 `class="active"`。

`README.md` 补一节「书签、标色与书架」，说明：标色要先点左侧色块再划选；书签在左侧；书架页两个标签；主题按钮在顶栏。`HANDOFF.md` 更新当前状态（新表、user_version=2、新增页面与接口、测试数）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest -v`
Expected: 全量 PASS。

- [ ] **Step 5: 手动验收**

按设计文档第 8 节走一遍：标三处色 + 两个书签 → 刷新复原；四套主题跨页切换且不闪白；文章库角标与「只看有标注的」；书架两个标签；右栏长内容可独立滚动；窄窗口（<900px）堆叠正常。

- [ ] **Step 6: 提交**

```bash
git add web/index.html web/library.html web/review.html web/shelf.html README.md HANDOFF.md tests/test_pages.py
git commit -m "docs: unify navigation and document reading marks"
```
