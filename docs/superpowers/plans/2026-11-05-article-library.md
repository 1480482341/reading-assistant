# 文章库与兴趣标签 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增按细粒度兴趣标签筛选的文章库页面，每篇文章显示中文标题，点开即可阅读。

**Architecture:** 后台批量调用本机 `claude` 为文章生成 `title_zh` 与受控词表标签并落库；新增只读接口 `/api/articles/library` 与 `/library` 静态页；阅读页支持 `?id=` 打开任意文章。

**Tech Stack:** Python 3 / FastAPI / SQLite / 原生 JS（无构建步骤）/ pytest / uv

**Spec:** `docs/superpowers/specs/2026-11-05-article-library-design.md`

## Global Constraints

- 模型通道只用本机 `claude` 命令行，不引入 API key；调用工作目录为空临时目录（复用 `app.analyze.run_claude`）。
- 模型输出必须按 JSON 解析；解析失败重试一次；整批失败只记日志，不阻塞启动任务。
- 标签只能取自受控词表，非法标签丢弃，结果去重，每篇最多 3 个。
- 界面文案中文，代码与注释英文。
- 严格 RED→GREEN：先写失败测试，再实现，最后跑全量 `uv run pytest`。
- 不改变 `pick_today` 的队列逻辑；「读完了」只标当前文章已读。

## Review Focus

- 旧数据库没有 `title_zh` 列时，启动必须先迁移再查询，否则所有文章相关接口报错。
- `title_zh` 为 NULL（模型失败或未处理）时，文章库与阅读页必须正常显示、只省略中文标题，不能渲染 `null`。
- 模型返回的数组长度/顺序与输入不一致时，按序号对齐、缺项跳过，不能错位写库或崩溃。
- `/api/articles/library` 必须注册在 `/api/articles/{article_id}` 之前，否则被解析成 int 而 422。
- 标签重复、非法或超过 3 个时，入库结果必须是去重、合法、最多 3 个。

---

### Task 1: 数据库结构与迁移

**Files:**
- Modify: `app/db.py`（SCHEMA 与 `init_db`）
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: 无
- Produces: `articles.title_zh TEXT`；表 `article_tags(article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE, tag TEXT, PRIMARY KEY(article_id, tag))`

- [ ] **Step 1: 写失败测试**

在 `tests/test_db.py` 追加：

```python
def test_article_tags_table_and_title_zh_column(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(articles)")}
    assert "title_zh" in cols
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "article_tags" in tables


def test_old_db_gets_title_zh_column_migrated(tmp_path):
    p = tmp_path / "old.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, text TEXT)")
    conn.execute("INSERT INTO articles(title, text) VALUES('Old', 'body')")
    conn.commit()
    conn.close()

    migrated = init_db(str(p))
    cols = {r["name"] for r in migrated.execute("PRAGMA table_info(articles)")}
    assert "title_zh" in cols
    assert migrated.execute("SELECT title FROM articles").fetchone()["title"] == "Old"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL（`title_zh` 不在列集合 / `article_tags` 不存在）

- [ ] **Step 3: 实现**

`app/db.py` 的 `articles` 建表语句加入 `title_zh TEXT,`；`SCHEMA` 追加：

```sql
CREATE TABLE IF NOT EXISTS article_tags (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    tag        TEXT NOT NULL,
    PRIMARY KEY (article_id, tag)
);
```

`init_db` 在 `executescript` 之后、`commit` 之前加迁移：

```python
cols = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
if "title_zh" not in cols:
    conn.execute("ALTER TABLE articles ADD COLUMN title_zh TEXT")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add title_zh column and article_tags table"
```

---

### Task 2: 元数据生成模块

**Files:**
- Create: `app/metadata.py`
- Test: `tests/test_metadata.py`

**Interfaces:**
- Consumes: `app.analyze.run_claude`、`app.analyze.ModelCallError`、`app.analyze.AnalysisError`、`app.analyze._loads_array`
- Produces:
  - `INTEREST_TAGS: tuple[str, ...]`（16 个）
  - `build_metadata_prompt(batch: list[tuple[str, str]]) -> str`（元素为 `(title, excerpt)`）
  - `parse_metadata(raw: str, expected: int) -> list[dict]`，元素为 `{"title_zh": str, "tags": list[str]}`
  - `enrich_metadata(conn: sqlite3.Connection, runner: Runner | None = None, batch_size: int = 10) -> int`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from app.db import init_db
from app.metadata import INTEREST_TAGS, enrich_metadata, parse_metadata
from app.analyze import ModelCallError


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: FAIL（`ModuleNotFoundError: app.metadata`）

- [ ] **Step 3: 实现 `app/metadata.py`**

要点：
- `INTEREST_TAGS` 按 spec 顺序：`("AI", "Computing", "Physics", "Math", "Biology", "Medicine", "Psychology", "Philosophy", "History", "Politics", "Economics", "Environment", "Art", "Literature", "Culture", "Society")`。
- `parse_metadata` 用 `_loads_array` 解析，容忍 ```json 围栏；只取前 `expected` 项；`title_zh` 去空白并截断 30 字；`tags` 过滤 `INTEREST_TAGS`、按首次出现去重、最多 3 个；非 dict 项跳过。
- `enrich_metadata` 每批取 `SELECT id, title, text FROM articles WHERE title_zh IS NULL ORDER BY id` 的 `batch_size` 条，excerpt 取正文前 100 词；解析失败追加 `"\n\nReturn ONLY the JSON array."` 重试一次；`ModelCallError` 与其他异常按批 `logger.warning` 后继续；`title_zh` 为空的条目跳过、保持 NULL，下次启动重试；每批写库后 `commit`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add app/metadata.py tests/test_metadata.py
git commit -m "feat: add metadata enrichment for titles and tags"
```

---

### Task 3: 启动任务接入元数据生成

**Files:**
- Modify: `app/collect.py:97-106`（`startup_job`）
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `app.metadata.enrich_metadata(conn, runner=None) -> int`
- Produces: `startup_job` 依次调用 `collect_new` → `enrich_metadata` → `analyze_pending`

- [ ] **Step 1: 写失败测试**

```python
def test_startup_job_enriches_before_analysis(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    order = []
    monkeypatch.setattr("app.collect.collect_new", lambda conn: order.append("collect") or 0)
    monkeypatch.setattr("app.collect.enrich_metadata",
                        lambda conn, runner=None: order.append("enrich") or 0)
    monkeypatch.setattr("app.collect.analyze_pending",
                        lambda conn, runner=None: order.append("analyze") or 0)
    from app.collect import startup_job
    startup_job(db)
    assert order == ["collect", "enrich", "analyze"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_collect.py::test_startup_job_enriches_before_analysis -v`
Expected: FAIL（`AttributeError: ... enrich_metadata` 或顺序断言失败）

- [ ] **Step 3: 实现**

`app/collect.py` 顶部加 `from app.metadata import enrich_metadata`；`startup_job` 内：

```python
added = collect_new(conn)
titled = enrich_metadata(conn, runner)
analysed = analyze_pending(conn, runner)
logger.info("启动任务完成: 新增 %s 篇, 元数据 %s 篇, 预分析 %s 篇", added, titled, analysed)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_collect.py -v`
Expected: PASS（全部通过）

- [ ] **Step 5: 提交**

```bash
git add app/collect.py tests/test_collect.py
git commit -m "feat: enrich article metadata during startup"
```

---

### Task 4: 文章库接口与文章详情补字段

**Files:**
- Create: `app/library.py`
- Modify: `app/main.py`（新增路由，`article_detail` 的 SELECT 增加 `title_zh`）
- Test: `tests/test_library_api.py`

**Interfaces:**
- Consumes: `articles`、`article_tags` 表
- Produces: `library_rows(conn) -> list[dict]`，元素键为 `id, title, title_zh, topic, source, published_at, word_count, status, tags`；`GET /api/articles/library`

- [ ] **Step 1: 写失败测试**

```python
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
                 "word_count,text,status) VALUES(2,'u2','Newer',NULL,'humanities','A',"
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


def test_article_detail_includes_title_zh(tmp_path):
    body = _client(tmp_path).get("/api/articles/1").json()
    assert body["title_zh"] == "旧文"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_library_api.py -v`
Expected: FAIL（404/422，接口不存在）

- [ ] **Step 3: 实现**

`app/library.py`：查询所有文章（`ORDER BY published_at DESC, id DESC`），一次性读出 `article_tags` 按 `article_id` 聚合，返回 `[{**dict(row), "tags": [...]}]`。

`app/main.py`：`import` 后新增路由，**放在 `/api/articles/{article_id}` 之前**：

```python
@app.get("/api/articles/library")
def article_library():
    conn = open_db()
    try:
        return library_rows(conn)
    finally:
        conn.close()
```

`article_detail` 的 SELECT 加入 `title_zh`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_library_api.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/library.py app/main.py tests/test_library_api.py
git commit -m "feat: add article library endpoint"
```

---

### Task 5: 文章库页面路由

**Files:**
- Modify: `app/main.py`（WEB_DIR 存在时新增 `/library`）
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `web/library.html`（Task 6 创建；本任务先放占位文件即可通过测试）
- Produces: `GET /library`

- [ ] **Step 1: 写失败测试**

```python
def test_library_page_serves(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/library")
    assert r.status_code == 200
    assert "article-list" in r.text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_pages.py::test_library_page_serves -v`
Expected: FAIL（404）

- [ ] **Step 3: 实现**

- 新建最小 `web/library.html`（含 `<ul class="article-list" id="article-list">`），Task 6 补全。
- `app/main.py` 的 `if WEB_DIR.exists():` 块内加：

```python
@app.get("/library")
def library_page():
    return FileResponse(WEB_DIR / "library.html")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/main.py web/library.html tests/test_pages.py
git commit -m "feat: serve library page"
```

---

### Task 6: 文章库页面实现

**Files:**
- Create: `web/library.js`、`web/library.css`
- Modify: `web/library.html`
- Test: 浏览器人工验证（前端无单测）

**Interfaces:**
- Consumes: `GET /api/articles/library`，字段见 Task 4
- Produces: 页面行为——标签多选（同时满足）、状态筛选、点击卡片跳 `/?id=<id>`

- [ ] **Step 1: 写页面骨架**

`web/library.html`：`style.css` + `library.css`；顶栏导航 `阅读 / 文章库(active) / 复习 / 导出`；主体含 `#status-filter`、`#tag-filter`、`#article-list`；引用 `/static/library.js`。

- [ ] **Step 2: 实现 `library.js`**

- 常量 `TAGS` 与后端 `INTEREST_TAGS` 一致（16 个）。
- `state = { tags: new Set(), status: "all" }`；状态按钮：全部 / 待分析(pending) / 可读(ready) / 已读(read)。
- 标签按钮点击切换选中；多选按「同时包含」过滤。
- 「全部」按钮清空标签并复位状态。
- 渲染卡片：英文标题、`title_zh`（为空则不渲染中文行）、`source · published_at · word_count words · status`、标签 chip；卡片 `dataset.id`，点击跳 `/?id=<id>`。
- 空列表显示「文章库还是空的」。

- [ ] **Step 3: 写 `library.css`**

沿用 `style.css` 变量（`--ink/--muted/--line/--accent/--panel`）；卡片为上下留白的列表项，选中标签按钮用 `--accent` 反色。

- [ ] **Step 4: 浏览器验证**

Run: `uv run uvicorn app.main:app --port 8000`，打开 `/library`：
- 26 篇文章全部列出，已读与 pending 都在。
- 点标签后只剩含该标签的文章；多选叠加；「全部」复位。
- `title_zh` 为空的条目只显示英文标题。
- 点卡片进入 `/?id=N` 且载入对应文章。

- [ ] **Step 5: 提交**

```bash
git add web/library.html web/library.js web/library.css
git commit -m "feat: add article library page"
```

---

### Task 7: 阅读页支持按 id 打开与中文标题

**Files:**
- Modify: `web/app.js`、`web/index.html`、`web/review.html`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `GET /api/articles/{id}`（含 `title_zh`）
- Produces: 阅读页 `?id=` 行为；顶栏「文章库」链接

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL（缺少链接 / 元素）

- [ ] **Step 3: 实现**

- `index.html`：导航加 `<a href="/library">文章库</a>`；`h1` 后加 `<div class="title-zh" id="article-title-zh"></div>`。
- `review.html`：导航加 `<a href="/library">文章库</a>`。
- `app.js`：读 `new URLSearchParams(location.search).get("id")`；有值时 `fetch(/api/articles/${id})`，非 200 时标题显示「文章不存在」并清空正文；否则维持当天队列逻辑。渲染时清空并填充 `#article-title-zh`（空字符串则隐藏）。
- `style.css` 加 `.title-zh { color: var(--muted); font-size: 16px; margin-bottom: 8px; }`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS

- [ ] **Step 5: 浏览器验证**

`/?id=1` 显示对应文章与中文标题；`/?id=99999` 显示「文章不存在」不报错；无参数时仍是当天第一篇。

- [ ] **Step 6: 提交**

```bash
git add web/app.js web/index.html web/review.html web/style.css tests/test_pages.py
git commit -m "feat: open articles by id and show Chinese titles"
```

---

### Task 8: 全量验证与文档

**Files:**
- Modify: `README.md`
- Test: 全量测试

**Interfaces:**
- Consumes: 前七个任务的成果
- Produces: 可用的完整功能与使用说明

- [ ] **Step 1: 全量测试**

Run: `uv run pytest`
Expected: 全部通过（原 62 个 + 新增用例）

- [ ] **Step 2: 真实数据冒烟**

在现有 `data/library.db` 上启动应用，确认启动日志出现「元数据 N 篇」，`/library` 能看到中文标题与标签；若模型不可用，页面仍可浏览且不报错。

- [ ] **Step 3: 更新 README**

在「启动」一节后补充：文章库地址 `/library`；标签与中文标题由启动时后台任务生成，未生成的文章仅显示英文标题，重新启动会重试。

- [ ] **Step 4: 提交**

```bash
git add README.md
git commit -m "docs: describe article library"
```
