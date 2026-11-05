# 英语阅读工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一个本地阅读器：每天自动备好英文文章，划词即得释义与语法拆解，所有命中存入本地数据库并按频次与间隔重复复习。

**Architecture:** FastAPI + SQLite 单机应用。文章经 RSS 采集、trafilatura 提取正文后入库；后台按 2000 词分块调用本机 `claude -p` 生成结构化词条与语法点；前端划词先查本地预分析结果，未命中再走即时调用。

**Tech Stack:** Python 3.11、uv、FastAPI、SQLite (标准库 sqlite3)、trafilatura、feedparser、原生 JS（无构建步骤）

**Spec:** `E:\AI_Project\plan\2026-11-05-reading-assistant-design.md`

## Global Constraints

- Python 3.11.9，依赖用 uv 管理（`uv add` / `uv run`）
- 模型只用本机 `claude -p`，**不引入 API key**；调用时工作目录设为空的临时目录
- 单次 `claude -p` 超时 120 秒；实测单次约 12 秒
- 所有模型输出必须经 JSON 解析，失败重试一次，再失败标记该块 `failed`
- 预分析结果**不写 occurrences**；只有用户确认的查询才计频次
- 前端为原生 JS，无 npm / 无构建步骤
- 数据库单文件 `data/library.db`；无守护进程，随应用启动
- 界面文案中文，代码与注释英文

## Review Focus

1. **划中的文本超长或含换行**（整段、整句带标点、跨段落选择）——期望：截断到 500 字符或按句切分后分析，页面不卡死、不报错
2. **模型输出被 markdown 围栏包裹或前后带解释文字** —— 期望：仍能解析出数组；解析失败自动重试一次
3. **正文含代码块、公式、非英文段落** —— 期望：提取与分块不崩溃，词条不产出乱码条目
4. **复习队列为空时打开复习页** —— 期望：显示空状态文案，不报错、不白屏
5. **数据库文件损坏或被占用** —— 期望：启动时报出明确错误路径，而不是静默建一张空表

---

### Task 1: 项目骨架与数据库 schema

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing
- Produces: `init_db(path: str) -> sqlite3.Connection`（创建全部表并返回连接，`row_factory = sqlite3.Row`）；`connect(path: str) -> sqlite3.Connection`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
import sqlite3, pytest
from app.db import init_db

def test_creates_all_tables(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"articles", "analysis", "entries", "occurrences",
            "grammar_terms", "review", "sources", "settings"} <= names

def test_corrupt_db_raises_clear_error(tmp_path):
    p = tmp_path / "bad.db"
    p.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError) as e:
        init_db(str(p))
    assert "bad.db" in str(e.value) or "file is not a database" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implement schema in `app/db.py`**

用 `CREATE TABLE IF NOT EXISTS` 建设计文档第 10 节的八张表。`review` 表列固定为 `entry_id INTEGER PRIMARY KEY, bucket INTEGER DEFAULT 0, due_at TEXT, last_seen_at TEXT, consecutive_known INTEGER DEFAULT 0, graduated INTEGER DEFAULT 0`（Task 7、Task 10 都依赖这两个字段名）。`init_db` 捕获 `sqlite3.DatabaseError` 后 `raise sqlite3.DatabaseError(f"数据库无法打开: {path}") from e`（满足 Review Focus 第 5 条）。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/__init__.py app/db.py tests/test_db.py
git commit -m "feat: project skeleton and sqlite schema"
```

---

### Task 2: 词条归并、频次与幂等

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_entries.py`

**Interfaces:**
- Consumes: `init_db(path)` from Task 1
- Produces:
  - `upsert_entry(conn, kind: str, lemma: str) -> int`（返回 entry_id）
  - `insert_occurrence(conn, entry_id: int, article_id: int, sentence: str, surface: str, gloss: str, grammar_role: str, why: str) -> bool`（同文章同词条返回 False 不写入）
  - `entry_frequency(conn) -> list[sqlite3.Row]`（字段 `entry_id, kind, lemma, count`，按 count 降序）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_entries.py
from app.db import init_db, upsert_entry, insert_occurrence, entry_frequency

def test_same_lemma_is_one_entry(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    a = upsert_entry(conn, "word", "run")
    b = upsert_entry(conn, "word", "run")
    assert a == b

def test_duplicate_lookup_in_same_article_counts_once(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    e = upsert_entry(conn, "word", "run")
    assert insert_occurrence(conn, e, 1, "He ran.", "ran", "跑", "谓语", "过去式") is True
    assert insert_occurrence(conn, e, 1, "He ran again.", "ran", "跑", "谓语", "过去式") is False
    assert entry_frequency(conn)[0]["count"] == 1

def test_frequency_orders_desc(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    a = upsert_entry(conn, "word", "albeit")
    b = upsert_entry(conn, "word", "scrutiny")
    insert_occurrence(conn, a, 1, "s", "albeit", "尽管", "", "")
    insert_occurrence(conn, b, 1, "s", "scrutiny", "审查", "", "")
    insert_occurrence(conn, b, 2, "s", "scrutiny", "审查", "", "")
    assert [r["lemma"] for r in entry_frequency(conn)] == ["scrutiny", "albeit"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_entries.py -v`
Expected: FAIL — `ImportError: cannot import name 'upsert_entry'`

- [ ] **Step 3: Implement the three functions**

`upsert_entry` 用 `INSERT ... ON CONFLICT(kind, lemma) DO UPDATE SET lemma=lemma RETURNING id`。`insert_occurrence` 先查 `(entry_id, article_id)` 是否已存在。幂等性用应用层判断即可，不加唯一索引（同一文章同一词条允许不同句子各存一条的语义不同，此处按设计文档取"同文章只计一次"）。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_entries.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_entries.py
git commit -m "feat: entry upsert, idempotent occurrences, frequency ordering"
```

---

### Task 3: RSS 采集与正文提取

**Files:**
- Create: `app/sources.py`
- Create: `tests/fixtures/sample.rss`
- Create: `tests/fixtures/sample_article.html`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `init_db`, from Task 1
- Produces:
  - `fetch_items(feed_xml: bytes) -> list[dict]`（字段 `title, link, published, summary`）
  - `extract_text(html: str) -> str`
  - `ingest_article(conn, url: str, title: str, source: str, topic: str, html: str, published_at: str) -> int | None`（提取后 `< 400` 词返回 None；url 已存在返回已有 id）
  - `seed_sources(conn) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sources.py
from pathlib import Path
from app.db import init_db
from app.sources import fetch_items, extract_text, ingest_article

FIX = Path(__file__).parent / "fixtures"

def test_parses_rss_items():
    items = fetch_items((FIX / "sample.rss").read_bytes())
    assert len(items) == 2
    assert items[0]["title"]

def test_extracts_body_without_navigation():
    text = extract_text((FIX / "sample_article.html").read_text(encoding="utf-8"))
    assert "algorithmic trading" in text
    assert "Subscribe" not in text

def test_short_extraction_is_rejected(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert ingest_article(conn, "u1", "t", "s", "tech", "<html><body>hi</body></html>", "") is None

def test_same_url_is_not_duplicated(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    html = (FIX / "sample_article.html").read_text(encoding="utf-8")
    a = ingest_article(conn, "u2", "t", "s", "tech", html, "")
    b = ingest_article(conn, "u2", "t", "s", "tech", html, "")
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sources.py -v`
Expected: FAIL — `No module named 'app.sources'`

- [ ] **Step 3: Implement; add fixtures**

`fetch_items` 用 feedparser 解析字节串。`extract_text` 用 `trafilatura.extract(html, include_comments=False, include_tables=False)`，返回 `""` 当 None。`seed_sources` 写入三个主源：Quanta、JSTOR Daily、Longreads（设计文档第 14 节标注为带全文的主源）。

fixture 用真实结构的精简版：`sample.rss` 含 2 个 `<item>`；`sample_article.html` 含 `<nav>`、`<article>` 正文（其中一句含 "algorithmic trading"）、页尾 "Subscribe" 区块。

- [ ] **Step 4: Verify extraction quality on real articles (R3)**

Run: `uv run python -c "from app.sources import extract_text; import urllib.request as u; print(len(extract_text(u.urlopen('https://www.quantamagazine.org/feed/').read().decode('utf-8','ignore'))))"`
再对 JSTOR Daily、Longreads 各抽 1 篇真实文章，人工检查提取结果无导航残留、无正文截断。
Expected: 三篇正文完整、无广告/导航文本。
**若不合格**：停止，回来向用户报告并讨论换提取库（候选：readability-lxml），不要硬往下做。

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add app/sources.py tests/fixtures tests/test_sources.py
git commit -m "feat: rss fetching and article text extraction"
```

---

### Task 4: 预分析（分块、调用、JSON 容错、术语映射）

**Files:**
- Create: `app/analyze.py`
- Test: `tests/test_analyze.py`

**Interfaces:**
- Consumes: `init_db` (Task 1), `upsert_entry` (Task 2)
- Produces:
  - `chunk_text(text: str, words_per_chunk: int = 2000) -> list[str]`
  - `parse_items(raw: str) -> list[dict]`（抛出 `AnalysisError`）
  - `map_grammar_term(conn, label: str) -> int`（映射不到时新建 `status='pending'`）
  - `build_preanalysis_prompt(chunk: str) -> str`
  - `analyze_article(conn, article_id: int, runner: Callable[[str], str] | None = None) -> None`（`runner` 可注入，测试用假实现）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analyze.py
import pytest
from app.db import init_db
from app.analyze import chunk_text, parse_items, AnalysisError, map_grammar_term, analyze_article

def test_chunk_text_splits_on_word_count():
    words = " ".join(f"w{i}" for i in range(4500))
    chunks = chunk_text(words, 2000)
    assert len(chunks) == 3
    assert all(len(c.split()) <= 2000 for c in chunks)

def test_parse_strips_markdown_fences():
    raw = '```json\n[{"term":"run","type":"word","gloss_zh":"跑"}]\n```'
    assert parse_items(raw)[0]["term"] == "run"

def test_parse_tolerates_prose_around_array():
    raw = 'Here you go:\n[{"term":"run"}]\nHope this helps.'
    assert parse_items(raw)[0]["term"] == "run"

def test_parse_raises_after_retry():
    calls = []
    def bad_runner(prompt):
        calls.append(prompt)
        return "not json at all"
    with pytest.raises(AnalysisError):
        parse_items("not json at all")
    assert True

def test_grammar_label_maps_to_same_id(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    a = map_grammar_term(conn, "插入语")
    b = map_grammar_term(conn, "插入语")
    assert a == b

def test_analyze_article_marks_failure_without_crashing(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','short text','pending')")
    conn.commit()
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]
    analyze_article(conn, aid, runner=lambda p: "garbage")
    row = conn.execute("SELECT status, error FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert row["status"] == "failed"
    assert row["error"]

def test_parse_drops_items_without_term():
    raw = '[{"term":"run"},{"gloss_zh":"没有 term 的脏条目"}]'
    assert len(parse_items(raw)) == 1

def test_chunk_handles_code_blocks_without_crashing():
    text = "Intro.\n```python\nprint('x')\n```\n" + "word " * 2100
    assert len(chunk_text(text, 2000)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analyze.py -v`
Expected: FAIL — `No module named 'app.analyze'`

- [ ] **Step 3: Implement `app/analyze.py`**

- `chunk_text`：按词切分，贪心拼到 `words_per_chunk`
- `parse_items`：先 `json.loads`；失败则用正则取第一个 `[...]` 再解析；仍失败抛 `AnalysisError`
- `run_claude(prompt, timeout=120)`：`subprocess.run(["claude","-p","--output-format","json",...])`，`cwd` 设为 `tempfile.mkdtemp()`，解析外层 JSON 的 `result` 字段；非零退出抛 `AnalysisError`
- `analyze_article`：分块 → 3 路并发调用 → 每块 `parse_items`（失败重试一次）→ 合并去重 `(kind, term)` → 写 `analysis.payload_json`，状态 `ready`／`failed` + `error`
- 语法点条目通过 `map_grammar_term` 落 `grammar_terms`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analyze.py -v`
Expected: 8 passed

- [ ] **Step 5: Real call smoke test**

Run: `uv run python -c "from app.analyze import run_claude; print(run_claude('Return only a JSON array with one object whose term is attest to')[:200])"`
Expected: 输出含 `attest to`，耗时 10–15 秒。

- [ ] **Step 6: Commit**

```bash
git add app/analyze.py tests/test_analyze.py
git commit -m "feat: chunked pre-analysis with tolerant json parsing"
```

---

### Task 5: 划词查询与确认接口

**Files:**
- Create: `app/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `init_db`, `entry_frequency`, `insert_occurrence`, `upsert_entry`, `analyze_article`
- Produces:
  - `create_app(db_path: str) -> FastAPI`（测试注入临时库）
  - `GET /api/lookup?article_id=&text=` → `{"hit": bool, "item": {...} | null}`
  - `POST /api/occurrences` body `{article_id, text, sentence, item}` → `{"recorded": bool, "entry_id": int}`
  - `lookup_local(payload: list[dict], text: str) -> dict | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py
from fastapi.testclient import TestClient
from app.db import init_db
from app.main import create_app

def _client(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','body','ready')")
    conn.execute("""INSERT INTO analysis(article_id,status,payload_json) VALUES
        (1,'ready','[{"term":"albeit","type":"word","gloss_zh":"尽管","grammar_role":"conj","sentence":"albeit short","why":"让步"}]')""")
    conn.commit(); conn.close()
    return TestClient(create_app(db))

def test_lookup_hits_local_analysis(tmp_path):
    r = _client(tmp_path).get("/api/lookup", params={"article_id": 1, "text": "albeit"})
    assert r.status_code == 200
    assert r.json()["hit"] is True
    assert r.json()["item"]["gloss_zh"] == "尽管"

def test_lookup_overlong_selection_is_truncated(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/lookup", params={"article_id": 1, "text": "x" * 5000})
    assert r.status_code == 200
    assert r.json()["hit"] is False

def test_duplicate_confirmation_records_once(tmp_path):
    c = _client(tmp_path)
    body = {"article_id": 1, "text": "albeit", "sentence": "albeit short",
            "item": {"term": "albeit", "type": "word"}}
    assert c.post("/api/occurrences", json=body).json()["recorded"] is True
    assert c.post("/api/occurrences", json=body).json()["recorded"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL — `No module named 'app.main'`

- [ ] **Step 3: Implement `create_app` and the two routes**

`create_app` 用闭包持有 `db_path`，每个请求 `connect(db_path)`。`/api/lookup` 先把 `text` 截断到 500 字符并 `strip()`；命中判断用 `term.lower() == text.lower()`，未命中时返回 `{"hit": False, "item": None}` 并由前端触发即时分析（Task 9 接入）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: lookup and occurrence endpoints"
```

---

### Task 6: 每日队列与方向轮换

**Files:**
- Modify: `app/sources.py`
- Test: `tests/test_queue.py`

**Interfaces:**
- Consumes: `init_db`
- Produces: `pick_today(conn, limit: int = 5) -> list[dict]`（按 `tech → history → humanities` 轮换，跳过已读，返回 `id, title, topic, status`）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_queue.py
from app.db import init_db
from app.sources import pick_today

def _seed(conn):
    for i, topic in enumerate(["tech", "tech", "history", "humanities", "history"]):
        conn.execute("INSERT INTO articles(url,title,topic,text,status) VALUES(?,?,?,?,?)",
                     (f"u{i}", f"t{i}", topic, "body", "ready"))
    conn.commit()

def test_rotates_topics(tmp_path):
    conn = init_db(str(tmp_path / "t.db")); _seed(conn)
    topics = [a["topic"] for a in pick_today(conn, limit=3)]
    assert topics == ["tech", "history", "humanities"]

def test_skips_already_read(tmp_path):
    conn = init_db(str(tmp_path / "t.db")); _seed(conn)
    conn.execute("UPDATE articles SET status='read' WHERE topic='history' AND id=(SELECT MIN(id) FROM articles WHERE topic='history')")
    conn.commit()
    topics = [a["topic"] for a in pick_today(conn, limit=3)]
    assert "history" in topics and len(topics) == 3

def test_empty_library_returns_empty_list(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    assert pick_today(conn) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_queue.py -v`
Expected: FAIL — `ImportError: cannot import name 'pick_today'`

- [ ] **Step 3: Implement `pick_today`**

按固定顺序 `["tech", "history", "humanities"]` 轮转取每个主题最新一条未读，直到 `limit`；主题无可用文章则跳过该主题继续。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_queue.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/sources.py tests/test_queue.py
git commit -m "feat: daily article queue with topic rotation"
```

---

### Task 7: 复习状态机

**Files:**
- Create: `app/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `init_db`
- Produces:
  - `INTERVALS = [0, 3, 7]`（天）
  - `ensure_review(conn, entry_id: int, now: str) -> None`（新建时 bucket=0，due 当天）
  - `grade(conn, entry_id: int, known: bool, now: str) -> None`
  - `due_queue(conn, now: str, limit: int = 50) -> list[sqlite3.Row]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review.py
from app.db import init_db
from app.review import ensure_review, grade, due_queue

NOW = "2026-11-05"

def _entry(conn):
    return conn.execute("INSERT INTO entries(kind,lemma) VALUES('word','run') RETURNING id").fetchone()["id"]

def test_new_entry_due_today(tmp_path):
    conn = init_db(str(tmp_path / "t.db")); e = _entry(conn)
    ensure_review(conn, e, NOW)
    assert len(due_queue(conn, NOW)) == 1

def test_known_advances_bucket(tmp_path):
    conn = init_db(str(tmp_path / "t.db")); e = _entry(conn)
    ensure_review(conn, e, NOW); grade(conn, e, True, NOW)
    row = conn.execute("SELECT bucket FROM review WHERE entry_id=?", (e,)).fetchone()
    assert row["bucket"] == 1
    assert due_queue(conn, NOW) == []

def test_unknown_resets_to_zero(tmp_path):
    conn = init_db(str(tmp_path / "t.db")); e = _entry(conn)
    ensure_review(conn, e, NOW); grade(conn, e, True, NOW); grade(conn, e, False, NOW)
    row = conn.execute("SELECT bucket, consecutive_known FROM review WHERE entry_id=?", (e,)).fetchone()
    assert row["bucket"] == 0 and row["consecutive_known"] == 0

def test_two_known_at_last_bucket_graduates(tmp_path):
    conn = init_db(str(tmp_path / "t.db")); e = _entry(conn)
    ensure_review(conn, e, NOW)
    for _ in range(3): grade(conn, e, True, NOW)
    grade(conn, e, True, NOW)
    row = conn.execute("SELECT graduated FROM review WHERE entry_id=?", (e,)).fetchone()
    assert row["graduated"] == 1
    assert due_queue(conn, NOW) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review.py -v`
Expected: FAIL — `No module named 'app.review'`

- [ ] **Step 3: Implement `app/review.py`**

`due_at = now + INTERVALS[bucket]` 天（ISO 日期字符串比较即可）。`bucket` 上限 2；在 bucket==2 时答对累计 `consecutive_known`，达到 2 置 `graduated=1`。答错：`bucket=0, consecutive_known=0, due_at=now`。`due_queue` 过滤 `graduated=0 AND due_at<=now`，按 `entry_frequency` 的 count 降序、再按 `due_at` 升序。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/review.py tests/test_review.py
git commit -m "feat: three-bucket spaced repetition with graduation"
```

---

### Task 8: 导出

**Files:**
- Create: `app/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `init_db`, `entry_frequency`
- Produces: `export_markdown(conn) -> str`；`export_csv(conn) -> str`（表头 `kind,lemma,count,gloss,sentence,article_url`）

- [ ] **Step 1: Write the failing test**

```python
# tests/test_export.py
from app.db import init_db
from app.export import export_markdown, export_csv

def _seed(conn):
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('http://x','T','body','read')")
    conn.execute("INSERT INTO entries(kind,lemma) VALUES('word','albeit')")
    conn.execute("""INSERT INTO occurrences(entry_id,article_id,sentence,surface,gloss,grammar_role,why)
                    VALUES(1,1,'albeit short','albeit','尽管','conj','让步')""")
    conn.commit()

def test_markdown_contains_word_and_frequency(tmp_path):
    conn = init_db(str(tmp_path / "t.db")); _seed(conn)
    md = export_markdown(conn)
    assert "albeit" in md and "1" in md

def test_csv_has_header_and_row(tmp_path):
    conn = init_db(str(tmp_path / "t.db")); _seed(conn)
    lines = export_csv(conn).strip().splitlines()
    assert lines[0] == "kind,lemma,count,gloss,sentence,article_url"
    assert "albeit" in lines[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_export.py -v`
Expected: FAIL — `No module named 'app.export'`

- [ ] **Step 3: Implement using the `csv` module with `io.StringIO`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_export.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/export.py tests/test_export.py
git commit -m "feat: markdown and csv export"
```

---

### Task 9: 阅读页前端（双栏 + 划词）

**Files:**
- Create: `web/index.html`
- Create: `web/app.js`
- Create: `web/style.css`
- Modify: `app/main.py`（挂载 `StaticFiles`，新增 `GET /`、`GET /api/articles/today`、`GET /api/articles/{id}`）

**Interfaces:**
- Consumes: Task 5 的 `/api/lookup`、`/api/occurrences`；Task 6 的 `pick_today`
- Produces: 页面 `/`；右侧栏通过 `renderSidebar(items)` 渲染，条目数据结构 `{term, gloss_zh, grammar_role}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pages.py
from fastapi.testclient import TestClient
from app.db import init_db
from app.main import create_app

def test_reading_page_serves(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db).close()
    r = TestClient(create_app(db)).get("/")
    assert r.status_code == 200
    assert "article-body" in r.text

def test_today_endpoint_on_empty_library(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db).close()
    r = TestClient(create_app(db)).get("/api/articles/today")
    assert r.status_code == 200 and r.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Build the page**

双栏布局（左正文 `#article-body`，右 `#sidebar`）。`app.js` 监听 `mouseup`：`window.getSelection().toString()` → 调 `/api/lookup` → 命中直接在选区旁浮层显示；未命中显示「分析中…」并调即时接口；浮层有「记下来」按钮 → `POST /api/occurrences` → 右栏追加。

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_pages.py -v`
Expected: 2 passed

- [ ] **Step 5: Manual browser check**

Run: `uv run uvicorn app.main:app --reload` 然后浏览器打开 `http://127.0.0.1:8000/`，划选一个词。
Expected: 浮层出现，右栏追加条目，控制台无报错。

- [ ] **Step 6: Commit**

```bash
git add web app/main.py tests/test_pages.py
git commit -m "feat: reading page with selection lookup"
```

---

### Task 10: 复习页前端（卡片默认 + 列表）

**Files:**
- Create: `web/review.html`
- Create: `web/review.js`
- Modify: `app/main.py`（新增 `GET /review`、`GET /api/review/queue`、`POST /api/review/{entry_id}`）

**Interfaces:**
- Consumes: Task 7 的 `due_queue`、`grade`
- Produces: 页面 `/review`；队列元素 `{entry_id, lemma, gloss, sentence, count}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_api.py
from fastapi.testclient import TestClient
from app.db import init_db
from app.main import create_app

def test_empty_queue_returns_list(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db).close()
    r = TestClient(create_app(db)).get("/api/review/queue")
    assert r.status_code == 200 and r.json() == []

def test_grading_moves_entry(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO entries(kind,lemma) VALUES('word','run')")
    conn.execute("INSERT INTO review(entry_id,bucket,due_at,consecutive_known,graduated) VALUES(1,0,'2026-11-05',0,0)")
    conn.commit(); conn.close()
    r = TestClient(create_app(db)).post("/api/review/1", json={"known": True})
    assert r.status_code == 200
    assert TestClient(create_app(db)).get("/api/review/queue").json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_api.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Build the page**

`review.html` 卡片为主视图，顶部显示 `12 / 41`；两个按钮「认识」「不认识」调用 POST；空队列显示「今天没有要复习的」。列表入口放在页面右上角，可切换到频次列表（读 `/api/export` 同款数据接口）。

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_review_api.py -v`
Expected: 2 passed

- [ ] **Step 5: Manual check**

打开 `http://127.0.0.1:8000/review`，空库时应看到空状态文案而非白屏。

- [ ] **Step 6: Commit**

```bash
git add web/review.html web/review.js app/main.py tests/test_review_api.py
git commit -m "feat: review page with card flow"
```

---

### Task 11: 端到端冒烟

**Files:**
- Create: `tests/test_e2e.py`
- Create: `README.md`

**Interfaces:**
- Consumes: 全部
- Produces: 无

- [ ] **Step 1: Write an integration test with a fake model runner**

```python
# tests/test_e2e.py
from app.db import init_db, connect
from app.sources import ingest_article
from app.analyze import analyze_article
from app.main import create_app
from fastapi.testclient import TestClient
from pathlib import Path

FAKE = '[{"term":"albeit","type":"word","gloss_zh":"尽管","grammar_role":"conj","sentence":"albeit short","why":"让步"}]'

def test_ingest_analyze_lookup_confirm(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    html = (Path(__file__).parent / "fixtures" / "sample_article.html").read_text(encoding="utf-8")
    aid = ingest_article(conn, "u9", "T", "Quanta", "tech", html, "2026-11-05")
    analyze_article(conn, aid, runner=lambda p: FAKE)
    conn.close()
    c = TestClient(create_app(db))
    assert c.get("/api/lookup", params={"article_id": aid, "text": "albeit"}).json()["hit"] is True
    body = {"article_id": aid, "text": "albeit", "sentence": "albeit short",
            "item": {"term": "albeit", "type": "word"}}
    assert c.post("/api/occurrences", json=body).json()["recorded"] is True
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_e2e.py -v`
Expected: 1 passed

- [ ] **Step 3: Full suite**

Run: `uv run pytest -v`
Expected: 全部通过，无失败

- [ ] **Step 4: Real run**

Run: `uv run uvicorn app.main:app --reload`，浏览器读一篇真实文章并划词。
Expected: 正文正常显示、预分析完成后右栏有内容、划词浮层 1 秒内出现。

- [ ] **Step 5: README + commit**

README 写清：启动命令、数据文件位置、如何换订阅源、如何导出。

```bash
git add README.md tests/test_e2e.py
git commit -m "test: end-to-end smoke and usage readme"
```

---

### Task 12: 手动收集、启动抓取与降级横幅

**Files:**
- Create: `app/collect.py`
- Modify: `app/main.py`
- Modify: `app/sources.py`
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `ingest_article`, `extract_text`, `fetch_items`, `analyze_article` (Tasks 3、4)
- Produces:
  - `ingest_text(conn, title: str, text: str, topic: str = "manual") -> int`
  - `ingest_url(conn, url: str) -> int | None`
  - `ingest_pdf(conn, path: str) -> int | None`
  - `POST /api/articles/ingest` body `{url?, text?, title?, topic?}` → `{"article_id": int}`
  - `GET /api/health` → `{"claude_available": bool, "db": "ok"}`
  - startup hook：对每个 enabled 源抓取新条目并把 `status='pending'` 的文章送去预分析

- [ ] **Step 1: Write the failing test**

```python
# tests/test_collect.py
import pytest
from app.db import init_db
from app.collect import ingest_text, ingest_pdf
from app.main import create_app
from fastapi.testclient import TestClient

def test_ingest_text_creates_article(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = ingest_text(conn, "Pasted", "world " * 500, "manual")
    assert conn.execute("SELECT title FROM articles WHERE id=?", (aid,)).fetchone()["title"] == "Pasted"

def test_ingest_rejects_empty_text(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    with pytest.raises(ValueError):
        ingest_text(conn, "Empty", "   ", "manual")

def test_health_reports_missing_model(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db"); init_db(db).close()
    monkeypatch.setattr("app.main.shutil.which", lambda name: None)
    r = TestClient(create_app(db)).get("/api/health")
    assert r.json()["claude_available"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_collect.py -v`
Expected: FAIL — `No module named 'app.collect'`

- [ ] **Step 3: Implement collection paths**

`ingest_text`：`strip()` 后少于 400 词仍接受（手动粘贴是明知要读的），但空字符串抛 `ValueError`。`ingest_url`：`urllib.request` 取页面 → `extract_text` → `ingest_article`。`ingest_pdf`：`uv add pypdf`，逐页 `extract_text()` 拼接。`/api/health` 用 `shutil.which("claude")` 判断。

- [ ] **Step 4: Startup hook**

在 `create_app` 内用 FastAPI `lifespan`：后台线程依次抓取各 enabled 源、入库、对 `pending` 文章调用 `analyze_article`。抓取失败只记日志，不阻塞启动（满足设计文档 D9「正文立即可读、预分析后台进行」）。

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_collect.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add app/collect.py app/main.py app/sources.py tests/test_collect.py pyproject.toml uv.lock
git commit -m "feat: manual ingestion, startup fetch, model health check"
```

---

## 交付后的旧方案处置

设计文档第 15 节。**执行前单独向用户确认一次**，再按顺序：备份 `english-immersion/data/` → 删除 skill 目录 → 删除 `E:\AI_Project\plan\english-learning-plan.md` → 更新项目记忆。
