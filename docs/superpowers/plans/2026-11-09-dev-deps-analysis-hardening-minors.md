# 工程清理 · 预分析加固 · 两条 Minor 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 固化 ruff/mypy 检查环境，把预分析分块降到 500 词并增加低产出失败判定，修复习列表分组顺序与表外类别覆盖两条 Minor。

**Architecture:** 三项独立改动：dev 依赖与 mypy 配置进 `pyproject.toml`；`app/analyze.py` 调整分块常量与块级校验（重试语义不变，最多 2 次调用）；`app/main.py` 收紧类别写路径；`web/review.js` 调整排序。无 schema 变更、不迁移数据。

**Tech Stack:** Python 3.11、FastAPI、SQLite、uv、pytest、ruff、mypy、原生 JS。

**Spec:** `docs/superpowers/specs/2026-11-09-dev-deps-analysis-hardening-minors-design.md`

## Global Constraints

- 不改 schema、不迁移数据、不触碰 `data/library.db`。
- 预分析密度保持每 5 词 1 条；`PREANALYSIS_WORKERS = 6`；预分析用默认模型，划词用 haiku；超时 300 秒；空临时目录 + `--strict-mcp-config --bare`。
- 模型调用失败（`ModelCallError`）不重试；解析失败或低产出最多重试一次。
- 界面文案中文，代码与注释英文；页面文本一律 `textContent`；不引入 npm/JS 测试框架。
- 严格 RED→GREEN；每个任务结束跑全量 `uv run pytest`。
- 提交用 Conventional Commits；推送走 SSH（`git@github.com:1480482341/reading-assistant.git`）。
- ruff / mypy 只进 dev 依赖，不增加运行时依赖。

## Review Focus

1. **单个块的模型调用失败**（找不到 claude、超时、非零退出）：不应重试，其他块的结果仍应入库，文章仍为 ready。
2. **恰好 200 词的块**：密度判定必须从 ≥200 词开始；199 词的块即使只返回 1 条也不能重试或判失败。
3. **类别边界**：首次保存遇到表外类别必须留空；再次保存遇表外类别必须保留已有类别；字面「其他」必须仍能入库。
4. **短尾块**（<200 词）合法地产出很少条目：不能触发重试，也不能让整篇失败。
5. **只有词汇条目的复习列表**：没有语法组时只渲染一个「词汇与短语」分组，不崩、不空。

---

### Task 1: 固化 ruff / mypy

**Files:**
- Modify: `pyproject.toml:15-19`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: 无
- Produces: 之后所有任务使用 `uv run ruff check .` 与 `uv run mypy`，无需 `--with`。

- [ ] **Step 1: 修改 pyproject.toml**

`[dependency-groups] dev` 增加两项，并新增 mypy 配置：

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
    "ruff>=0.17.4",
    "mypy>=2.4.1",
]

[tool.mypy]
ignore_missing_imports = true
files = ["app"]
```

- [ ] **Step 2: 更新锁文件并同步**

Run: `cd reading-assistant && uv lock && uv sync`
Expected: `uv.lock` 出现 ruff / mypy 条目，命令退出码 0。

- [ ] **Step 3: 验证静态检查**

Run: `uv run ruff check . && uv run mypy`
Expected: ruff 输出 `All checks passed!`；mypy 输出 `Success: no issues found`。

- [ ] **Step 4: 验证测试基线**

Run: `uv run pytest -q`
Expected: `190 passed`（允许 1 条第三方 httpx 弃用警告）。

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add ruff and mypy to dev dependencies"
```

---

### Task 2: 预分析分块 800 → 500 词

**Files:**
- Modify: `app/analyze.py:22`
- Test: `tests/test_analyze.py:92-113`

**Interfaces:**
- Consumes: 无
- Produces: `DEFAULT_CHUNK_WORDS = 500`；`chunk_text(text, n)` 行为不变。

- [ ] **Step 1: 更新失败测试**

把 `test_default_chunk_size_is_800_words` 改名为 `test_default_chunk_size_is_500_words`，断言 1700 词切成 4 块且每块 ≤500 词：

```python
def test_default_chunk_size_is_500_words():
    text = " ".join(f"w{i}" for i in range(1700))
    chunks = chunk_text(text)
    assert len(chunks) == 4
    assert all(len(c.split()) <= 500 for c in chunks)
```

把 `test_analyze_article_uses_default_chunking` 的断言从 3 改为 4：

```python
    analyze_article(conn, aid, runner=lambda p: prompts.append(p) or "[]")
    assert len(prompts) == 4
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_analyze.py::test_default_chunk_size_is_500_words tests/test_analyze.py::test_analyze_article_uses_default_chunking -v`
Expected: FAIL（实际 3 块 / 3 次调用）。

- [ ] **Step 3: 修改常量**

`app/analyze.py` 第 22 行：

```python
DEFAULT_CHUNK_WORDS = 500
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_analyze.py -q`
Expected: PASS。

- [ ] **Step 5: 全量测试**

Run: `uv run pytest -q`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
git add app/analyze.py tests/test_analyze.py
git commit -m "fix(analyze): shrink preanalysis chunks to 500 words

800-word chunks produced 25% corrupt results in local sampling: outputs
above ~34k tokens came back as ~6k-character fragments. 500-word chunks
stay under 26k tokens with unchanged density (1 item per 5 words)."
```

---

### Task 3: 低产出即失败

**Files:**
- Modify: `app/analyze.py:22-26`（常量）、`app/analyze.py:150-157`（`_run_with_retry`）、`app/analyze.py:221-222`（`_analyse_chunk`）
- Test: `tests/test_analyze.py`（新增与调整）

**Interfaces:**
- Consumes: `DEFAULT_CHUNK_WORDS = 500`、`chunk_text`、`build_preanalysis_prompt`（Task 2）。
- Produces:
  - `MIN_DENSITY_WORDS = 200`
  - `LOW_OUTPUT_RATIO = 0.5`
  - `_run_with_retry(runner: Runner, prompt: str, min_items: int = 0) -> list[dict]`
  - `_analyse_chunk(runner: Runner, chunk: str) -> list[dict]`（签名不变）

- [ ] **Step 1: 写失败测试**

在 `tests/test_analyze.py` 顶部增加 `import json`，把 `ModelCallError` 加入 `from app.analyze import ...` 的导入列表，并添加辅助函数：

```python
def _items(count, first=None):
    rows = [{"term": first or f"w{i}", "type": "word"} for i in range(count)]
    return json.dumps(rows, ensure_ascii=False)


def _article(conn, text):
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t',?,'pending')", (text,))
    conn.commit()
    return conn.execute("SELECT id FROM articles").fetchone()["id"]
```

新增 6 个测试：

```python
def test_low_output_chunk_is_retried_once(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 500))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(10) if len(calls) == 1 else _items(60)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 2
    assert row["status"] == "ready"
    assert len(json.loads(row["payload_json"])) == 60


def test_persistently_low_output_marks_analysis_failed(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 500))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(10)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, error FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 2
    assert row["status"] == "failed"
    assert "低产出" in row["error"]


def test_short_chunk_skips_density_check(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 100))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(1)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 1
    assert row["status"] == "ready"


def test_density_check_starts_at_199_words(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 199))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(1)

    analyze_article(conn, aid, runner=runner)
    assert len(calls) == 1


def test_density_check_applies_at_200_words(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 200))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _items(1)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 2
    assert row["status"] == "failed"


def test_low_output_chunk_does_not_discard_other_chunks(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    text = " ".join(["a"] * 500 + ["marker"] + ["b"] * 499)
    aid = _article(conn, text)
    calls = []

    def runner(prompt):
        calls.append("marker" if "marker" in prompt else "plain")
        return _items(10) if "marker" in prompt else _items(60)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert calls.count("plain") == 1
    assert calls.count("marker") == 2
    assert row["status"] == "ready"
    assert len(json.loads(row["payload_json"])) == 60


def test_chunk_model_call_error_is_not_retried_and_others_kept(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    text = " ".join(["a"] * 500 + ["marker"] + ["b"] * 499)
    aid = _article(conn, text)
    calls = []

    def runner(prompt):
        if "marker" in prompt:
            calls.append("marker")
            raise ModelCallError("boom")
        calls.append("plain")
        return _items(60)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert calls.count("marker") == 1
    assert row["status"] == "ready"
    assert len(json.loads(row["payload_json"])) == 60
```

同时把受影响的旧测试 runner 改为足量输出：

- `test_analyze_article_uses_default_chunking`：`runner=lambda p: prompts.append(p) or _items(60)`。
- `test_analyze_article_uses_six_parallel_chunks`：`runner=lambda p: _items(60)`。
- `test_partial_chunk_failure_keeps_successful_items`：非 boom 块返回 `_items(60, first="good")`。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_analyze.py -q`
Expected: 新测试 FAIL（低产出未被识别，调用次数与状态不符）。

- [ ] **Step 3: 实现常量与校验**

`app/analyze.py` 常量区增加：

```python
MIN_DENSITY_WORDS = 200
LOW_OUTPUT_RATIO = 0.5
```

`_run_with_retry` 改为：

```python
def _run_with_retry(runner: Runner, prompt: str, min_items: int = 0) -> list[dict]:
    retry = False
    try:
        items = parse_items(runner(prompt))
    except ModelCallError:
        raise
    except AnalysisError:
        items, retry = [], True
    if retry or len(items) < min_items:
        items = parse_items(runner(prompt + "\n\nReturn ONLY the JSON array."))
    if len(items) < min_items:
        logger.warning("low-output chunk: %d items, minimum %d", len(items), min_items)
        raise AnalysisError(f"低产出：{len(items)} 条（下限 {min_items}）")
    return items
```

`_analyse_chunk` 改为：

```python
def _analyse_chunk(runner: Runner, chunk: str) -> list[dict]:
    words = len(chunk.split())
    expected = max(1, round(words / WORDS_PER_ITEM))
    min_items = (expected + 1) // 2 if words >= MIN_DENSITY_WORDS else 0
    return _run_with_retry(runner, build_preanalysis_prompt(chunk), min_items=min_items)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_analyze.py -q`
Expected: PASS。

- [ ] **Step 5: 全量测试与静态检查**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
git add app/analyze.py tests/test_analyze.py
git commit -m "fix(analyze): fail preanalysis chunks below half the target density

A chunk could return ten items for a 160-item target and still be stored
as success. Chunks of at least 200 words now retry once below 50% of the
target and are dropped if still low; short tail chunks stay exempt."
```

---

### Task 4: 表外类别不覆盖已有类别

**Files:**
- Modify: `app/main.py:23`（import）、`app/main.py:207-211`
- Test: `tests/test_api.py:276-296`

**Interfaces:**
- Consumes: `GRAMMAR_CATEGORIES`（`app/grammar.py`）；`upsert_entry(conn, kind, lemma, category)` 的空值不覆盖语义（`app/db.py:207-216`）。
- Produces: 写路径只接受受控类别；无新函数。

- [ ] **Step 1: 更新与新增失败测试**

把 `test_unknown_grammar_category_folds_to_other` 改名为 `test_unknown_grammar_category_is_left_empty`，断言改为空串：

```python
def test_unknown_grammar_category_is_left_empty(tmp_path):
    client = _client(tmp_path)
    item = {"term": "Having started", "type": "grammar", "gloss_zh": "开始之后",
            "grammar_role": "状语", "why": "非谓语",
            "grammar_category": "分词状语从句"}
    client.post("/api/occurrences", json={
        "article_id": 1, "text": "Having started",
        "sentence": "Having started early, she left.", "item": item})
    conn = connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT category FROM entries").fetchone()["category"] == ""
```

新增两个测试：

```python
def test_unknown_category_does_not_overwrite_existing(tmp_path):
    client = _client(tmp_path)
    base = {"term": "Having started", "type": "grammar", "gloss_zh": "开始之后",
            "grammar_role": "状语", "why": "非谓语"}
    for category in ("过去分词", "分词状语从句"):
        client.post("/api/occurrences", json={
            "article_id": 1, "text": "Having started",
            "sentence": "Having started early, she left.",
            "item": {**base, "grammar_category": category}})
    conn = connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT category FROM entries").fetchone()["category"] == "过去分词"


def test_literal_other_category_is_stored(tmp_path):
    client = _client(tmp_path)
    item = {"term": "Having started", "type": "grammar", "gloss_zh": "开始之后",
            "grammar_role": "状语", "why": "非谓语", "grammar_category": "其他"}
    client.post("/api/occurrences", json={
        "article_id": 1, "text": "Having started",
        "sentence": "Having started early, she left.", "item": item})
    conn = connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT category FROM entries").fetchone()["category"] == "其他"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_api.py::test_unknown_grammar_category_is_left_empty tests/test_api.py::test_unknown_category_does_not_overwrite_existing -v`
Expected: FAIL（当前折叠为「其他」并覆盖）。

- [ ] **Step 3: 修改写路径**

`app/main.py` 第 23 行改为：

```python
from app.grammar import GRAMMAR_CATEGORIES
```

第 207–211 行改为：

```python
            kind = str(item.get("type", "word"))
            raw_category = str(item.get("grammar_category") or "").strip()
            category = (raw_category if kind == "grammar"
                        and raw_category in GRAMMAR_CATEGORIES else "")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_api.py tests/test_db.py -q`
Expected: PASS。

- [ ] **Step 5: 全量测试与静态检查**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
git add app/main.py tests/test_api.py
git commit -m "fix(entries): never overwrite a category with an unrecognised label

The write path normalised unknown labels to 其他 before upsert, which then
replaced a valid stored category. Only labels from the controlled list are
written now; unknown labels leave the existing category untouched."
```

---

### Task 5: 复习列表词汇组固定第一

**Files:**
- Modify: `web/review.js:45-52`
- Test: `tests/test_pages.py:321-332`

**Interfaces:**
- Consumes: `/api/entries` 返回的 `kind` 与 `category`（Task 4 之后类别语义不变）。
- Produces: 页面内 `groupRank(row)`；无后端接口变化。

- [ ] **Step 1: 更新失败测试**

在 `test_review_page_shows_category_badge_and_groups_list` 的 needle 列表中加入 `"groupRank"`：

```python
    for needle in ("card-category", "group-head", "item.category", "groupRank"):
        assert needle in js
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_pages.py::test_review_page_shows_category_badge_and_groups_list -v`
Expected: FAIL（`groupRank` 不存在）。

- [ ] **Step 3: 改排序**

`web/review.js` 中 `groupOf` 之后：

```js
  const VOCABULARY_GROUP = "词汇与短语";
  const groupOf = row =>
    row.kind === "grammar" && row.category ? row.category : VOCABULARY_GROUP;
  const groupRank = row => (groupOf(row) === VOCABULARY_GROUP ? 0 : 1);
  const sorted = rows.slice().sort((a, b) => {
    const ra = groupRank(a);
    const rb = groupRank(b);
    if (ra !== rb) return ra - rb;
    const ga = groupOf(a);
    const gb = groupOf(b);
    if (ga !== gb) return ga.localeCompare(gb, "zh");
    return String(a.lemma).localeCompare(String(b.lemma), "zh");
  });
```

- [ ] **Step 4: 运行页面测试**

Run: `uv run pytest tests/test_pages.py -q`
Expected: PASS。

- [ ] **Step 5: 浏览器实测**

1. 建临时库并塞入 3 条词条（word 1 条、grammar 「倒装」「定语从句」各 1 条）与对应 review 行：

```bash
cd reading-assistant && uv run python -c "
import sqlite3
from app.db import init_db
from app.review import ensure_review
p = r'temp/review-check.db'
import os
if os.path.exists(p): os.remove(p)
c = init_db(p)
c.execute(\"INSERT INTO entries(kind,lemma,category) VALUES('word','open','')\")
c.execute(\"INSERT INTO entries(kind,lemma,category) VALUES('grammar','inversion','倒装')\")
c.execute(\"INSERT INTO entries(kind,lemma,category) VALUES('grammar','relative clause','定语从句')\")
c.commit()
for r in c.execute('SELECT id FROM entries'):
    ensure_review(c, r['id'], '2026-11-09')
print('seeded')
"
```

2. 启动临时服务并打开 `/review`：

```bash
uv run python -c "import uvicorn; from app.main import create_app; uvicorn.run(create_app(r'temp/review-check.db'), host='127.0.0.1', port=8000)"
```

3. 浏览器（本机 Edge）打开 `http://127.0.0.1:8000/review`，点「看列表」。
   Expected DOM 顺序：`词汇与短语` → `倒装` → `定语从句`（组内 lemma 按拼音）。
4. 删除语法词条后刷新，只剩一个 `词汇与短语` 分组，页面不报错：

```bash
uv run python -c "import sqlite3; c=sqlite3.connect(r'temp/review-check.db'); c.execute(\"DELETE FROM entries WHERE kind='grammar'\"); c.commit()"
```

5. 关掉临时服务。

- [ ] **Step 6: 全量测试**

Run: `uv run pytest -q`
Expected: 全绿。

- [ ] **Step 7: 提交**

```bash
git add web/review.js tests/test_pages.py
git commit -m "fix(review): always list vocabulary before grammar groups

Groups were sorted by pinyin as a single list, so 词汇与短语 landed between
grammar categories. It is pinned to rank 0; grammar groups keep pinyin order."
```

---

### Task 6: 文档同步

**Files:**
- Modify: `README.md:85`
- Modify: `HANDOFF.md`（§2.1、§2.2、§2.5、§3.1、§3.4、§6、§7）

**Interfaces:**
- Consumes: 前五个任务的最终行为与命令。
- Produces: 交接文档与新对话起点。

- [ ] **Step 1: 更新 README**

第 85 行「按 800 词一块分块分析」改为「按 500 词一块分块分析」。

- [ ] **Step 2: 更新 HANDOFF**

- §2.1：ruff / mypy 已进 dev 依赖，命令改为 `uv run ruff check .` 与 `uv run mypy`。
- §2.2：删除「低产出缺判断」；写明解析失败根因（单次输出过大）与 500 词修法；保留「旧文章不回溯类别」。
- §2.5：两条 Minor 标记为已修复，并写明新语义（词汇组固定第一；表外类别不覆盖、新词条为未分类）。
- §3.1：分块 800 → 500；其余不变。
- §3.4：静态检查命令更新。
- §6：测试数量按实际结果更新。
- §7：移除已完成项，保留推送提醒。

- [ ] **Step 3: 全量验证**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: 全绿。

- [ ] **Step 4: 提交**

```bash
git add README.md HANDOFF.md
git commit -m "docs: record dev tooling and preanalysis hardening changes"
```

---

## Self-Review 结论

- 规格覆盖：dev 依赖（Task 1）、500 词分块（Task 2）、低产出判定（Task 3）、c2（Task 4）、c1（Task 5）、文档（Task 6）。规格中「不做局部抢救」「无 schema 变更」体现在非目标与约束。
- 类型一致性：`_run_with_retry(runner, prompt, min_items=0)` 在 Task 3 定义并被 `_analyse_chunk` 使用；`groupRank` 在 Task 5 测试与实现同名。
- Review Focus 五项均已落到 Task 3/4/5 的测试或浏览器步骤。
- 计划长度与规格相当，代码块仅包含测试与不可推导的实现片段。
