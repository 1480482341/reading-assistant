# 文章库与兴趣标签 — 设计

- 日期：2026-11-05
- 状态：待批准
- 范围：新增文章库页面、细粒度兴趣标签、标题中文释义

## 目标

1. 新增「文章库」页面，列出全部文章，可按细粒度兴趣标签筛选。
2. 每篇文章显示英文标题与中文释义。
3. 从文章库点开任意文章即可进入阅读页阅读。

## 非目标

- 不做推荐算法、个性化排序或学习偏好建模。
- 不做标签的手工编辑界面；标签由模型按受控词表生成。
- 不改变当天队列（`pick_today`）的轮换规则。

## 已确认的决策

### 标签受控词表

16 个，存储用英文短标签，页面直接显示：

`AI`, `Computing`, `Physics`, `Math`, `Biology`, `Medicine`, `Psychology`,
`Philosophy`, `History`, `Politics`, `Economics`, `Environment`, `Art`,
`Literature`, `Culture`, `Society`

每篇文章由模型从中选 1–3 个；都不贴切时允许为空，不硬贴。词表以代码常量维护，页面的筛选按钮由该常量渲染。

### 元数据生成方式：独立后台任务（方案 A）

启动任务中新增一步，在 `collect_new` 之后、`analyze_pending` 之前执行：

- 选出 `title_zh IS NULL` 的文章（`title_zh` 同时作为「已处理」标记）。
- 每 8–10 篇打包为一次模型调用，输入为「标题 + 正文开头约 100 词」，输出按序号对齐的 `[{title_zh, tags}]`。
- 成功则写入 `articles.title_zh` 与 `article_tags`；整批解析失败只重试一次，再失败则本批保持 `title_zh` 为空，下次启动自动重试。
- 标签若不在受控词表内则丢弃；结果去重。
- 与预分析解耦：元数据失败不影响阅读，预分析失败也不影响元数据。

### 存储

- `articles` 新增列 `title_zh TEXT`。
- 新表 `article_tags(article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE, tag TEXT, PRIMARY KEY(article_id, tag))`。
- 旧库迁移：`init_db` 中用 `PRAGMA table_info` 检查后 `ALTER TABLE articles ADD COLUMN title_zh TEXT`。

### 页面与交互

- 路由 `/library` 提供 `web/library.html`。
- 顶部栏所有页面增加「文章库」链接。
- 文章库默认按 `published_at DESC, id DESC` 排序，显示全部状态（待分析 / 可读 / 已读）。
- 筛选区包含状态筛选与标签按钮（多选叠加），另有「全部」复位。
- 标签筛选在前端完成（数据量小）。
- 每张文章卡片显示：英文标题、中文标题、来源 · 日期 · 字数 · 状态、标签。
- 点击卡片进入 `/?id=<article_id>`。
- 阅读页：存在 `?id=` 时打开该文章，否则沿用当天队列第一篇；标题下方显示中文标题（若有）。
- 「读完了」只将当前文章标为已读，不影响当天队列。

## 接口

- `GET /api/articles/library` → 数组，元素为
  `{id, title, title_zh, topic, source, published_at, word_count, status, tags: [..]}`。
  需注册在 `/api/articles/{article_id}` 之前，避免路径参数误匹配。
- `GET /api/articles/{id}` 返回值增加 `title_zh`。

## 模块划分

- `app/metadata.py`：受控词表常量、批量提示词、`enrich_metadata(conn, runner=None)`。
- `app/main.py`：library 接口、`/library` 页面路由。
- `app/collect.py`：`startup_job` 调用 `enrich_metadata`。
- `web/library.html` / `web/library.js` / `web/library.css`。
- `web/app.js`：支持 `?id=` 与中文标题显示。

## 考虑过的其它方案

- **B：折进预分析提示词**。零额外调用，但会污染纯词汇/语法分析提示词，并发分块下标题由哪个块负责不确定，解析失败连累整块分析，且已分析文章需重跑。否决。
- **C：打开文章库时现算**。首次打开等待数分钟，否决。

## 测试计划

- `tests/test_metadata.py`：词表校验、批量输出解析、成功写库、非法标签丢弃、解析失败不写入、仅选未处理文章、重试一次。
- `tests/test_library_api.py`：接口字段、标签聚合、包含已读与 pending、排序。
- `tests/test_pages.py`：`/library` 可访问。
- `tests/test_api.py`：文章详情包含 `title_zh`。
- 全量 `uv run pytest` 必须全绿。

## 留给实现者的细节

- 批大小（8–10）、提示词措辞、卡片与筛选区样式。
- 中文标题长度上限（建议 30 字以内，超出截断）。
