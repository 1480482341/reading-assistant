# 工程清理 · 预分析加固 · 两条 Minor（设计）

- 日期：2026-11-09
- 范围：reading-assistant，三项互相独立的小改动，一次提交序列完成
- 状态：待用户确认

## 1. 意图与目标

1. 把 ruff / mypy 固化为项目 dev 依赖，检查命令不再依赖 `uv run --with` 临时环境。
2. 降低预分析解析失败率；对"块成功但产出极少"加失败判定，避免低质量结果被当成成功入库。
3. 修两条已记录的 Minor：复习列表分组顺序、表外类别覆盖已有类别。

非目标：
- 不回溯已有 31 篇文章的预分析结果，不改动 schema，不迁移数据。
- 不引入 JS 测试框架；前端仍用页面脚本断言 + 浏览器实测。
- 不改变密度规格（每 5 词 1 条）、并发（6）、模型分工（预分析默认模型、划词 haiku）。
- 不做截断 JSON 的局部抢救（理由见 3.2）。

## 2. 诊断数据（2026-11-09 实测）

本机 `claude` 2.1.319，空临时目录，`--strict-mcp-config --bare`，与生产调用一致。

- 样本一：article 17 两个 800 词块，均成功，157/156 条，输出 2.3–2.8 万 token。
- 样本二：article 4 前 8 个 800 词块并发 6 路：
  - 6 块成功：140–160 条，输出 2.58–3.11 万 token，结果 4.2–5.3 万字符。
  - 2 块失败（25%）：输出 3.40 万 / 3.60 万 token，但 `result` 只剩 5863 / 5912 字符的碎片；一块尾部截断（以 `},` 结束），一块头部截断（保留完整结尾 `}]` 但无起始 `[`）。两次外层 `subtype` 都是 success、退出码 0。
- 样本三：把失败的两个块按 500 词重新切分（各 500+300 词，共 4 次调用）：4/4 成功，输出 1.24–2.56 万 token，条目 62–102（密度仍≈每 5 词 1 条）。

结论：失败不是格式跑偏，而是**单次调用输出量过大**导致 `result` 被裁成碎片；成功样本的最高输出为 3.11 万 token，失败均 ≥3.40 万。500 词分块把单次输出压到 2.6 万以内，样本内失败率为 0。

## 3. 方案与决策

### 3.1 ruff / mypy 固化

- `pyproject.toml` 的 `[dependency-groups] dev` 增加 `ruff>=0.17.4`、`mypy>=2.4.1`（与实测通过的版本一致；uv.lock 固定实际版本）。
- 增加 `[tool.mypy]`：`ignore_missing_imports = true`、`files = ["app"]`，使 `uv run mypy` 一条命令即可复现第七轮的结果。
- ruff 用默认规则，不新增 `[tool.ruff]` 配置。
- 验收：`uv run ruff check .` 与 `uv run mypy` 均零问题；`uv run pytest` 仍全绿。

### 3.2 预分析加固

**决策 A：默认分块从 800 词改为 500 词**（`DEFAULT_CHUNK_WORDS = 500`）。
- 依据：500 词样本单次输出 ≤2.56 万 token，距 3.1 万的成功上限有余量；800 词已实测 25% 失败。
- 代价：调用数约 ×1.6；单次时长约减半，6 路并发下整篇墙钟时间大致不变。
- 密度不变：提示词目标仍是块词数/5。

**决策 B：低产出即失败**（用户已选 50% 档）。
- 判据：块词数 ≥200 且解析出的条目数 < 目标（块词数/5）的 50%，视为低产出。
- 处理：低产出与解析失败共用现有"重试一次"路径（第二次带 "Return ONLY the JSON array."）；仍不达标则该块记为失败块，不影响其他块。
- 短尾块（<200 词）不判密度，避免难文本误伤。
- 记录 warning 日志（块词数、目标、实际条目数），便于事后统计。

**决策 C：不做截断 JSON 的局部抢救。**
- 实测失败碎片只有期望内容的约 3%（5.9k/50k 字符），局部抢救最多拿到十几条，必然低于 50% 阈值而被丢弃；重发同一提示词也可能再次超限。缩小分块才是根因修法。

**重试语义**：每次块分析最多 2 次模型调用（首次 + 一次重试），与现状一致；模型调用本身失败（`ModelCallError`）仍不重试。

### 3.3 复习列表分组顺序（用户已选：词汇第一，其余拼音）

- `web/review.js` 排序改为两段：`词汇与短语` 固定 rank 0，其余 rank 1；同 rank 内先按组名 `localeCompare("zh")`，再按 lemma 排序。
- 只动前端，不改接口。

### 3.4 表外类别不覆盖（用户已选）

- `app/main.py` 写路径：仅当 `kind == "grammar"` 且原样类别在 `GRAMMAR_CATEGORIES` 内时才传类别；表外类别一律传空串。
- 依赖现有 `upsert_entry` 的"空值不覆盖已有类别"语义。
- 语义变化：首次保存时模型编造类别 → 词条显示"未分类"（而不是"其他"）；字面"其他"仍按有效类别入库。
- `app/analyze.py::map_grammar_category` 不变：预分析阶段的语法词表仍把表外类别折叠为"其他"。
- 移除 `main.py` 中对 `normalize_grammar_category` 的引用（若无其他用途）。

## 4. 改动清单

- `pyproject.toml`、`uv.lock`：dev 依赖与 mypy 配置。
- `app/analyze.py`：`DEFAULT_CHUNK_WORDS=500`；密度常量；低产出校验与重试路径；warning 日志。
- `app/main.py`：表外类别按空处理，去掉不再使用的 import。
- `web/review.js`：分组排序助手。
- `tests/test_analyze.py`、`tests/test_api.py`、`tests/test_db.py`（如需）、`tests/test_pages.py`：按 RED→GREEN 调整与新增。
- `README.md`、`HANDOFF.md`：命令、分块大小、已解决项与新约束。

## 5. 测试计划（RED→GREEN）

1. 分块默认值：1700 词 → 4 块（500/500/500/200）。
2. 低产出：500 词块返回 20 条（目标 100）→ 触发重试；两次都低 → 该块失败，其他块的结果仍入库。
3. 短块豁免：100 词块返回 1 条 → 不重试、不判失败。
4. 正常块不重试：500 词块返回 60 条 → 仅 1 次调用。
5. 表外类别：先存有效类别，再存表外类别 → 类别保持；新词条表外类别 → 空串。
6. 复习页：`review.js` 含词汇组固定排前的排序助记；浏览器实测两个语法组 + 词汇组的 DOM 顺序。
7. 全量 `uv run pytest`、`uv run ruff check .`、`uv run mypy`。

前端排序改动需用系统 Edge 实测（本机无 Chrome），无自动化回归。

## 6. 风险与回退

- 500 词分块使同篇文章的调用数上升，模型不可用时启动抓取耗时变长；可通过 `PREANALYSIS_WORKERS` 与已有失败横幅观测，无数据破坏。
- 低产出阈值只在块级生效，最坏情况是丢弃一个低质量块，其他块不受影响；阈值常量集中，便于按日志回调。
- 表外类别不再覆盖后，极端情况下用户重存也无法把类别改回"其他"以外的值——与"模型编造类别不可信"一致；有效类别重存仍可覆盖。
- 无 schema 变更，无需备份；不触碰 `data/library.db`。

## 7. 提交拆分（Conventional Commits）

1. `chore(deps): add ruff and mypy to dev dependencies`
2. `fix(analyze): shrink preanalysis chunks and fail low-output batches`
3. `fix(review): always list vocabulary before grammar groups`
4. `fix(entries): never overwrite category with an unrecognised label`
5. `docs: update handoff and readme for these changes`

每步先写失败测试，最后跑全量 pytest / ruff / mypy；推送前确认 `git status` 与远端差异。
