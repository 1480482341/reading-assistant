# 取消低产出重试 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让低产出分块只调用一次模型，同时保留解析失败时的一次重试。

**Architecture:** 只改 `_run_with_retry` 的重试触发条件；低产出仍抛 `LowOutputError`，由 `analyze_article` 保留并记 warning。阈值、提示词、分块都不动。

**Tech Stack:** Python 3.12、pytest、ruff、mypy、uv。

**Spec:** `docs/superpowers/specs/2026-11-10-drop-low-output-retry-design.md`

## Global Constraints

- 只用本机 claude 命令行，不引入 API key。
- 划词用 haiku，预分析用默认模型；两者不互换。
- 预分析并发 6，分块 500 词，密度每 5 词 1 条。
- 低产出判定：块 ≥200 词且条目 < 目标 50%。
- 解析失败重试一次；模型调用失败不重试；单次超时 300 秒。
- 严格 RED→GREEN；提交信息用 Conventional Commits。

## Review Focus

- 解析失败仍只重试一次：首次无效、第二次有效时必须成功，且总调用数为 2。
- 低产出块不得因取消重试而丢失条目：全块低产出时整篇仍 ready 且条目保留。
- 短尾块（<200 词）不判密度，也不应因此触发重试。
- 划词路径（`analyze_snippet`，`min_items=0`）行为不变。
- 单块模型调用失败不影响其他块，仍不重试。

---

### Task 1: 低产出不再重试

**Files:**
- Modify: `app/analyze.py:160-173` (`_run_with_retry`)
- Test: `tests/test_analyze.py`（4 个现有断言改写 + 1 个新回归测试）

**Interfaces:**
- Consumes: `_run_with_retry(runner: Runner, prompt: str, min_items: int = 0) -> list[dict]`（签名不变）
- Produces: 同一函数；仅在解析失败时重发一次提示词

- [ ] **Step 1: 改写现有低产出测试，使它们按新行为失败**

`test_low_output_chunk_is_retried_once` 改名为 `test_low_output_chunk_is_not_retried`，runner 始终返回 `_items(10)`，断言：

```python
assert len(calls) == 1
assert row["status"] == "ready"
assert len(json.loads(row["payload_json"])) == 10
```

其余三处断言改为期望 1 次调用：
- `test_all_low_output_chunks_keep_items_and_stay_ready`：`len(calls) == 1`
- `test_density_check_applies_at_200_words`：`len(calls) == 1`
- `test_low_output_chunk_does_not_discard_other_chunks`：`calls.count("marker") == 1`

- [ ] **Step 2: 新增解析失败重试的回归测试**

```python
def test_parse_failure_is_retried_once(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    aid = _article(conn, " ".join(["word"] * 500))
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return "not json" if len(calls) == 1 else _items(60)

    analyze_article(conn, aid, runner=runner)
    row = conn.execute("SELECT status, payload_json FROM analysis WHERE article_id=?", (aid,)).fetchone()
    assert len(calls) == 2
    assert row["status"] == "ready"
    assert len(json.loads(row["payload_json"])) == 60
```

- [ ] **Step 3: 运行测试确认 RED**

Run: `uv run pytest tests/test_analyze.py -q`
Expected: 步骤 1 的 4 个断言失败（实际 2 次调用）；步骤 2 的回归测试通过（保护的是保留行为）。

- [ ] **Step 4: 改 `app/analyze.py` 的触发条件**

把

```python
if retry or len(items) < min_items:
```

改为

```python
if retry:
```

- [ ] **Step 5: 运行测试确认 GREEN**

Run: `uv run pytest tests/test_analyze.py -q`
Expected: 全部通过。

- [ ] **Step 6: 全量验证**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy`
Expected: 全绿。

- [ ] **Step 7: 提交**

```bash
git add app/analyze.py tests/test_analyze.py
git commit -m "fix(analyze): stop retrying low-output chunks"
```

### Task 2: 交接文档

**Files:**
- Modify: `HANDOFF.md`（§1.7、§2.4、§3.1、§4、§7）

- [ ] **Step 1: 更新 HANDOFF**

- §1.7 增加「低产出不再重试，解析失败仍重试一次」。
- §3.1 把「解析失败或低产出重试一次」改为「仅解析失败重试一次」。
- §2.4 清空已决事项，或写明已按「不重试、保留产出」处理。
- §4 记录本轮提交与修改文件；§7 更新下一步。

- [ ] **Step 2: 提交**

```bash
git add HANDOFF.md
git commit -m "docs: record dropped low-output retry"
```
