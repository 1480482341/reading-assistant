# 语法类别展示与复习分组 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让受控语法类别在阅读右栏、划词浮层和复习页可见，并把复习列表按类别分组，且不改变复习算法。

**Architecture:** schema v4 只给 `entries` 增加 `category` 列；写路径在确认词条时把预分析/即时分析的 `grammar_category` 规范化后落到 entry；三个读接口与前端复用 `entries`。复习卡片仍是单短语，只有列表视图按类别插入分组行。

**Tech Stack:** Python 3.11 / FastAPI / SQLite / vanilla JS（无构建步骤）/ pytest。

**Spec:** `docs/superpowers/specs/2026-11-09-grammar-category-display-design.md`

## Global Constraints

- Python >= 3.11；依赖只用 `pyproject.toml` 中已列的，不新增。
- 数据库单文件 `data/library.db`；结构变更用 `PRAGMA user_version` 门控，只跑一次；本次目标版本 4。
- 受控类别唯一来源是 `app/grammar.py` 的 `GRAMMAR_CATEGORIES`（45 项）与 `normalize_grammar_category()`；列表外一律折叠为 `其他`。
- 前端原生 JS，无 npm、无构建；界面文案中文，代码与注释英文；写入页面的文本必须转义或走 `textContent`。
- 主题只用 CSS 变量；新增样式不得引入四套主题之外的新色值。
- 严格 RED→GREEN：每个任务先写失败测试，实现后跑全量 `uv run pytest`。
- 不回溯旧数据、不合并复习卡片、不改导出格式、不改预分析并发与分块。
- 真实库已在实施前备份为 `data/library.db.bak7-pre-entry-category`；不要在实施中删除它。

## Review Focus

- **v3 真实库升级**：已有 20 个 entries 与复习进度必须原样保留，只多一列。→ Task 1 的 `test_v3_database_gains_entry_category`。
- **未知类别串**：模型返回列表外类别时不得报错、不得入库未知标签，必须折叠为「其他」。→ Task 2 的 `test_unknown_grammar_category_folds_to_other`。
- **空类别覆盖**：再次确认同一词条且这次没有类别时，不能把已有类别清空。→ Task 2 的 `test_upsert_entry_keeps_category_when_blank`。
- **保存后的右栏**：保存成功必须与服务端一致（有标签、在正确分组、不重复）。→ Task 5 的 `test_save_refetches_marks_instead_of_appending`。
- **导出不变**：Markdown / CSV 列不变，即使 `entry_rows` 的查询多数了一列。→ Task 3 的现有 `tests/test_export.py` 全量通过。

---

### Task 1: schema v4 — `entries.category`

**Files:**
- Modify: `app/db.py:7`（`SCHEMA_VERSION`）、`app/db.py:48-54`（`entries` 建表）、`app/db.py:176-195`（`init_db` 迁移门控）
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `entries` 表含 `category TEXT NOT NULL DEFAULT ''`；新库与迁移后库的 `PRAGMA user_version == 4`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_db.py`：
- 把 `test_init_db_stamps_schema_version`、`test_schema_version_is_three`、`test_v1_database_upgrades_and_keeps_rows`、`test_legacy_phrase_vocabulary_is_archived_and_replaced` 中所有 `== 3` 改为 `== 4`，并把 `test_schema_version_is_three` 改名为 `test_schema_version_is_four`。
- 新增：

```python
def test_entries_table_has_category_column(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(entries)")}
    assert "category" in cols


def test_v3_database_gains_entry_category(tmp_path):
    p = tmp_path / "old.db"
    raw = sqlite3.connect(str(p))
    raw.execute(
        "CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "kind TEXT NOT NULL, lemma TEXT NOT NULL, "
        "created_at TEXT DEFAULT (datetime('now')), UNIQUE(kind, lemma))")
    raw.execute("INSERT INTO entries(kind, lemma) VALUES('grammar', 'having started')")
    raw.execute("PRAGMA user_version = 3")
    raw.commit()
    raw.close()

    conn = init_db(str(p))
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(entries)")}
    assert "category" in cols
    row = conn.execute("SELECT kind, lemma, category FROM entries").fetchone()
    assert tuple(row) == ("grammar", "having started", "")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_db.py -q`
Expected: FAIL —— 版本断言为 3、`category` 列不存在。

- [ ] **Step 3: 实现**

`app/db.py`：
1. `SCHEMA_VERSION = 4`。
2. `SCHEMA` 的 `entries` 建表在 `lemma` 后加 `category     TEXT NOT NULL DEFAULT ''`。
3. `init_db` 的 `if version < SCHEMA_VERSION:` 分支加：

```python
if version < 4:
    entry_cols = {r["name"] for r in conn.execute("PRAGMA table_info(entries)")}
    if "category" not in entry_cols:
        conn.execute(
            "ALTER TABLE entries ADD COLUMN category TEXT NOT NULL DEFAULT ''")
```

（用列存在性守卫，覆盖「新库已由 SCHEMA 建好列、version 仍为 0」的情况。）

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_db.py -q`
Expected: PASS。

- [ ] **Step 5: 全量回归并提交**

Run: `uv run pytest -q`；Expected: PASS。
```bash
git add app/db.py tests/test_db.py
git commit -m "feat(db): add entries.category in schema v4"
```

---

### Task 2: 写入路径 — `upsert_entry` 与 `/api/occurrences`

**Files:**
- Modify: `app/db.py:198-205`（`upsert_entry`）、`app/main.py:196-218`（`record_occurrence`）
- Test: `tests/test_db.py`、`tests/test_api.py`

**Interfaces:**
- Consumes: `entries.category`（Task 1）。
- Produces: `upsert_entry(conn, kind: str, lemma: str, category: str = "") -> int`；`POST /api/occurrences` 仍返回 `{"recorded": bool, "entry_id": int}`。

- [ ] **Step 1: 写失败测试**

`tests/test_db.py`：

```python
def test_upsert_entry_stores_category(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    entry_id = upsert_entry(conn, "grammar", "having started", "过去分词")
    assert conn.execute("SELECT category FROM entries WHERE id = ?",
                        (entry_id,)).fetchone()["category"] == "过去分词"


def test_upsert_entry_keeps_category_when_blank(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    entry_id = upsert_entry(conn, "grammar", "having started", "过去分词")
    upsert_entry(conn, "grammar", "having started", "")
    assert conn.execute("SELECT category FROM entries WHERE id = ?",
                        (entry_id,)).fetchone()["category"] == "过去分词"
```

（`test_db.py` 顶部相应补 `from app.db import init_db, upsert_entry`。）

`tests/test_api.py`（顶部已有 `_client(tmp_path, runner=None)` 辅助：建库、插一篇文章并返回
`TestClient`；本次需同时 `from app.db import connect, init_db`）：

```python
def test_occurrences_store_normalized_grammar_category(tmp_path):
    ...  # 建库、插一篇文章，client = TestClient(create_app(db))
    item = {"term": "Having started", "type": "grammar", "gloss_zh": "开始之后",
            "grammar_role": "状语", "why": "非谓语", "grammar_category": "过去分词"}
    r = client.post("/api/occurrences", json={
        "article_id": 1, "text": "Having started", "sentence": "Having started early",
        "item": item})
    assert r.status_code == 200
    conn = connect(db)
    assert conn.execute("SELECT category FROM entries").fetchone()["category"] == "过去分词"


def test_unknown_grammar_category_folds_to_other(tmp_path):
    ...  # 同上，grammar_category 换成 "分词状语从句"
    conn = connect(db)
    assert conn.execute("SELECT category FROM entries").fetchone()["category"] == "其他"


def test_word_occurrence_has_no_category(tmp_path):
    ...  # item type = "word"
    conn = connect(db)
    assert conn.execute("SELECT category FROM entries").fetchone()["category"] == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_db.py tests/test_api.py -q`
Expected: FAIL —— `upsert_entry` 不接受第 4 个参数 / category 为空。

- [ ] **Step 3: 实现**

`app/db.py` 的 `upsert_entry` 改为：

```python
def upsert_entry(conn: sqlite3.Connection, kind: str, lemma: str,
                 category: str = "") -> int:
    row = conn.execute(
        "INSERT INTO entries(kind, lemma, category) VALUES(?, ?, ?) "
        "ON CONFLICT(kind, lemma) DO UPDATE SET "
        "category = CASE WHEN excluded.category <> '' "
        "THEN excluded.category ELSE entries.category END "
        "RETURNING id",
        (kind, lemma, category),
    ).fetchone()
    conn.commit()
    return row["id"]
```

`app/main.py` 的 `record_occurrence` 在 `upsert_entry` 前计算类别（`normalize_grammar_category` 需从 `app.grammar` 导入）：

```python
kind = str(item.get("type", "word"))
raw_category = str(item.get("grammar_category") or "").strip()
category = (normalize_grammar_category(raw_category)
            if kind == "grammar" and raw_category else "")
entry_id = upsert_entry(conn, kind, lemma, category)
```

（不要对空字段调用 `normalize_grammar_category`，否则会把「没给类别」误记成「其他」。）

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_db.py tests/test_api.py -q`；Expected: PASS。

- [ ] **Step 5: 全量回归并提交**

Run: `uv run pytest -q`；Expected: PASS。
```bash
git add app/db.py app/main.py tests/test_db.py tests/test_api.py
git commit -m "feat(grammar): persist normalized category on entries"
```

---

### Task 3: 读接口返回类别

**Files:**
- Modify: `app/main.py:393-418`（`/marks`）、`app/review.py:48-59`（`due_queue`）、`app/export.py:5-17`（`QUERY`）
- Test: `tests/test_api.py`（新增）；回归 `tests/test_export.py`

**Interfaces:**
- Consumes: `entries.category`（Task 1）。
- Produces: `/api/articles/{id}/marks` 的每个条目含 `category: str`；`/api/review/queue` 每行含 `category`；`/api/entries` 每行含 `category`。导出输出不变。

- [ ] **Step 1: 写失败测试**

`tests/test_api.py`（复用 `_client(tmp_path)` 与 Task 2 加入的 `connect` 导入）：

```python
def test_marks_include_entry_category(tmp_path):
    ...  # 建库；插入 article、entry('grammar','having started','过去分词')、occurrence
    body = TestClient(create_app(db)).get("/api/articles/1/marks").json()
    assert body["grammar"][0]["category"] == "过去分词"


def test_review_queue_includes_category(tmp_path):
    ...  # 插 entry + 当天到期的 review 行
    row = TestClient(create_app(db)).get("/api/review/queue").json()[0]
    assert row["category"] == "过去分词"


def test_entries_endpoint_includes_category(tmp_path):
    ...  # 插 entry
    row = TestClient(create_app(db)).get("/api/entries").json()[0]
    assert row["category"] == "过去分词"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_api.py -q`
Expected: FAIL —— 响应里没有 `category` 键。

- [ ] **Step 3: 实现**

1. `article_marks` 的 SELECT 增加 `e.category`，条目 dict 增加 `"category": row["category"]`。
2. `due_queue` 的 SELECT 增加 `e.category`。
3. `export.QUERY` 的 SELECT 增加 `e.category`（`HEADER` 不动，CSV/MD 输出保持原样）。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_api.py tests/test_export.py tests/test_pages.py -q`；Expected: PASS。

- [ ] **Step 5: 全量回归并提交**

Run: `uv run pytest -q`；Expected: PASS。
```bash
git add app/main.py app/review.py app/export.py tests/test_api.py
git commit -m "feat(api): return grammar category from read endpoints"
```

---

### Task 4: 即时分析提示词补 `grammar_category`

**Files:**
- Modify: `app/analyze.py:159-164`（`SNIPPET_TEMPLATE`）、`app/analyze.py:186`（`format` 调用）
- Test: `tests/test_analyze.py`

**Interfaces:**
- Consumes: `GRAMMAR_CATEGORIES`（已导入）。
- Produces: `analyze_snippet` 的提示词包含 `grammar_category` 与 45 类列表；返回的 item 可能带该键。

- [ ] **Step 1: 写失败测试**

`tests/test_analyze.py`（沿用文件内假 runner 写法）：

```python
def test_snippet_prompt_offers_controlled_grammar_categories(tmp_path):
    ...  # 建库并插一篇文章，fake runner 记录 prompt
    captured = {}

    def runner(prompt):
        captured["prompt"] = prompt
        return FAKE

    analyze_snippet(conn, 1, "albeit", runner=runner)
    assert "grammar_category" in captured["prompt"]
    assert "过去分词" in captured["prompt"]
```

（`FAKE` 用文件内已有的单对象 JSON 字符串。）

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_analyze.py -q`
Expected: FAIL —— 提示词没有 `grammar_category`。

- [ ] **Step 3: 实现**

`SNIPPET_TEMPLATE` 的键列表增加 `grammar_category`，并附类别列表：

```python
SNIPPET_TEMPLATE = """A reader selected "{term}" in the sentence below.
Return ONLY a JSON array with one object with keys: term, type, gloss_zh, grammar_role, grammar_category, sentence, why.
grammar_category is only for type "grammar": copy one label exactly from the list below, or use 其他.
Write gloss_zh, grammar_role and why in Chinese.
GRAMMAR CATEGORIES: {categories}

SENTENCE: {sentence}
"""
```

`analyze_snippet` 的 `format` 增加 `categories="、".join(GRAMMAR_CATEGORIES)`。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_analyze.py -q`；Expected: PASS。

- [ ] **Step 5: 全量回归并提交**

Run: `uv run pytest -q`；Expected: PASS。
```bash
git add app/analyze.py tests/test_analyze.py
git commit -m "feat(analyze): ask snippet analysis for a grammar category"
```

---

### Task 5: 阅读页右栏、浮层与保存后的刷新

**Files:**
- Modify: `web/app.js`（`appendMark`、`renderRightPanel`、`showPopup`、`save`、`showArticle`、删除 `addToSidebar`）、`web/style.css`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `/marks` 的 `category`（Task 3）；payload item 的 `grammar_category`。
- Produces: 页面脚本含 `loadMarks()`；`save()` POST 成功后调用 `loadMarks()`。

- [ ] **Step 1: 写失败测试**

`tests/test_pages.py`：

```python
def test_reading_sidebar_shows_and_groups_grammar_categories(tmp_path):
    js = ...  # GET /static/app.js
    assert "cat-chip" in js
    assert "group-head" in js
    assert "item.category" in js
    assert "item.grammar_category" in js  # popup


def test_save_refetches_marks_instead_of_appending(tmp_path):
    js = ...
    save_idx = js.index("async function save")
    assert "loadMarks" in js
    assert js.index("loadMarks()", save_idx) < js.index("hidePopup()", save_idx)
    assert "addToSidebar" not in js
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_pages.py -q`
Expected: FAIL —— 尚无 `cat-chip` / `loadMarks`。

- [ ] **Step 3: 实现**

1. `appendMark`：类别非空时追加
   `const chip = document.createElement("span"); chip.className = "cat-chip"; chip.textContent = item.category;`
2. `renderRightPanel`：`marked-list` 原样；`grammar-list` 先按 `category` 分组（空归「未分类」），每组前插入
   `li.className = "group-head"`，组内再 `appendMark`。
3. `showPopup`：`popup-why` 的文本改为
   `[item.grammar_category, item.grammar_role, item.why].filter(Boolean).join(" · ")`。
4. 抽出 `function loadMarks() { fetch(.../marks).then(r => r.json()).then(renderRightPanel)... }`；
   `showArticle` 改调 `loadMarks()`；`save()` 在 POST 后调用 `loadMarks()`，删除 `addToSidebar` 及其调用。
5. `web/style.css` 增加 `.cat-chip`、`.group-head`（只用既有变量，例如
   `color: var(--muted); border: 1px solid var(--line);`）。右栏窄，`cat-chip` 用
   `white-space: nowrap; font-size: 11px;`。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_pages.py -q`；Expected: PASS。

- [ ] **Step 5: 全量回归并提交**

Run: `uv run pytest -q`；Expected: PASS。
```bash
git add web/app.js web/style.css tests/test_pages.py
git commit -m "feat(reading): show and group grammar categories in the sidebar"
```

---

### Task 6: 复习页类别徽标与列表分组

**Files:**
- Modify: `web/review.html`（卡片新增 `#card-category`）、`web/review.js`（`render`、`load`）、`web/style.css`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `/api/review/queue`、`/api/entries` 的 `category`（Task 3）。
- Produces: 卡片元素 `#card-category`；列表分组行 `class="group-head"`。

- [ ] **Step 1: 写失败测试**

```python
def test_review_page_shows_category_badge_and_groups_list(tmp_path):
    html = _html("/review", tmp_path)
    assert 'id="card-category"' in html
    js = ...  # GET /static/review.js
    assert "card-category" in js
    assert "group-head" in js
    assert "item.category" in js
    css = ...  # GET /static/style.css
    for needle in (".cat-chip", ".group-head", ".card-category"):
        assert needle in css
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_pages.py -q`；Expected: FAIL。

- [ ] **Step 3: 实现**

1. `review.html` 卡片内加 `<div class="card-category" id="card-category"></div>`。
2. `review.js` 的 `render`：`card-category` 文本设为 `item.category || ""`，空时 `hidden = true`。
3. `review.js` 的 `load`：把 `/api/entries` 行排序后渲染，
   排序键 `(row.kind === "grammar" && row.category ? 0 : 1, row.category || "词汇与短语", row.lemma)`；
   组键变化时插入 `<tr class="group-head"><td colspan="3">组名</td></tr>`。
   单词/短语行归入「词汇与短语」。
4. `web/style.css` 增加 `.card-category`（小号、`var(--muted)`）与 `.group-head`
   （`font-weight: 600; color: var(--muted); background: transparent;`）。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_pages.py -q`；Expected: PASS。

- [ ] **Step 5: 全量回归并提交**

Run: `uv run pytest -q`；Expected: PASS。
```bash
git add web/review.html web/review.js web/style.css tests/test_pages.py
git commit -m "feat(review): show category badge and grouped list"
```

---

### Task 7: 浏览器复验、真实库迁移与交接更新

**Files:**
- Modify: `HANDOFF.md`
- 临时文件放 `/temp`，不提交。

**Interfaces:**
- Consumes: 前六个任务。

- [ ] **Step 1: 用临时库做浏览器复验**

1. 在 `temp/` 写一个启动脚本：调用 `create_app(temp_db)` 并用 uvicorn 跑在 8010；
   `temp_db` 预置：1 篇文章（含多段正文）、2 个语法 entry（不同类别）、
   各一条 occurrence 与当天到期的 review 行、1 个 word entry。
2. 用系统 Edge + Playwright 打开 `http://127.0.0.1:8010/` 与 `/review`，
   确认：右栏语法按类别分组且有标签；浮层显示类别；复习卡片有徽标；
   列表视图有分组行；窄侧栏不溢出。截图留档，文件用完删除。
3. 检查 `curl -s http://127.0.0.1:8010/api/articles/1/marks` 与
   `/api/review/queue` 含 `category`。

- [ ] **Step 2: 迁移真实库并核对**

先在无服务运行时确认备份仍在，再启动一次真实服务（导入即迁移）：
```bash
ls -l data/library.db.bak7-pre-entry-category
uv run python -c "from app.main import app; print('ok')"
uv run python -c "import sqlite3; c=sqlite3.connect('data/library.db'); print(c.execute('PRAGMA user_version').fetchone()[0], c.execute('SELECT COUNT(*) FROM entries').fetchone()[0])"
```
Expected: 备份存在；输出 `ok`；版本 `4`，词条数仍为迁移前的数量（实施时为 20）。

- [ ] **Step 3: 更新 `HANDOFF.md`**

- 第 3 行日期与「第七次整理」。
- 新增「第七轮：语法类别展示与复习分组」小节：schema v4、`entries.category`、
  右栏分组、浮层、复习徽标与列表分组、保存后重拉 `/marks`。
- 更新 §2.2：删除「尚未展示」条目，保留「旧数据不回溯」。
- 更新 §6 数据状态：schema 4；新增备份 `library.db.bak7-pre-entry-category`。
- 更新提交列表与测试数量。

- [ ] **Step 4: 最终验证并提交**

Run: `uv run pytest -q`；Expected: 全绿。
```bash
git add HANDOFF.md
git commit -m "docs: record grammar category display round"
```
