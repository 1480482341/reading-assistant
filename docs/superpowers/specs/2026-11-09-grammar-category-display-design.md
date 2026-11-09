# 语法类别展示与复习分组 · 设计文档

- 日期：2026-11-09
- 状态：**待批准**
- 项目：reading-assistant（本地单机 Web 应用）

---

## 1. 意图

第五轮把语法类别收成了 45 个受控枚举，预分析结果里每条语法项都带 `grammar_category`，但这个信息只进了词表，用户在阅读和复习时看不到：右栏「语法点」只列短语，复习卡片也不区分类别。结果是「受控词表」只对数据库有意义，对学习过程没有产生价值。

这一轮让类别回到用户眼前：阅读时能看出这个语法点属于哪一类，复习时能按类别成组回顾。

## 2. 目标

| 编号 | 目标 |
|---|---|
| G1 | 语法词条在数据库中有稳定的类别（entry 级） |
| G2 | 右栏「语法点」显示类别标签，并按类别分组 |
| G3 | 划词浮层显示语法类别（预分析结果已有该字段） |
| G4 | 复习卡片显示类别徽标 |
| G5 | 复习页列表视图按类别分组展示，复习算法与卡片粒度不变 |
| G6 | 旧数据不回溯，类别为空时界面降级为无标签 / 「未分类」 |

## 3. 非目标

- 不合并复习卡片：评级仍以单个短语为单位，不改 `review` 算法
- 不回溯旧文章与已有词条的类别（与第五轮「旧文章不回溯」一致）
- 不改导出格式（Markdown / CSV 不加类别列）
- 不做类别的手工编辑或纠正 UI
- 不改预分析并发、分块与密度

## 4. 反目标（做出来也算失败）

1. **迁移丢数据** —— `ALTER TABLE` 失败或中途中断导致词条/复习进度损坏。
2. **复习顺序被类别打乱** —— 卡片队列仍按 `count DESC, due_at ASC`，分组只作用于列表视图。
3. **右栏被标签撑破** —— 窄栏下类别标签换行溢出，遮挡正文。
4. **同一短语类别漂移** —— 反复划词导致类别来回跳动。

## 5. 方案选择

### 5.1 类别存放位置（已在对话中确定）

- **方案一（选中）：存放在 `entries.category`（短语级）**
  只加一列 `entries.category`；`/marks`、`/api/review/queue`、`/api/entries` 都已 JOIN `entries`，无需改查询结构。复习分组稳定，迁移仅为 `ALTER TABLE ... ADD COLUMN`，不重建表。
- 方案二：存放在 `occurrences`（每次命中带类别）
  展示更精确，但复习页跨文章只能取「最近一次命中」，分组随阅读顺序跳动，SQL 更绕。
- 方案三：不改库，读时从文章 payload 反查
  复习页无文章上下文，旧 payload 也可能缺字段，不可靠，排除。

### 5.2 复习页呈现方式（已在对话中确定）

卡片仍为单个短语；卡片显示类别徽标，**列表视图**按类别分组。队列顺序不变。

## 6. 数据与接口变更

### 6.1 Schema v4

- `SCHEMA_VERSION` 3 → 4。
- `entries` 建表语句增加 `category TEXT NOT NULL DEFAULT ''`（新库）。
- `init_db` 在 `version < 4` 分支执行：
  `ALTER TABLE entries ADD COLUMN category TEXT NOT NULL DEFAULT ''`。
- 不建外键、不建索引；类别以受控枚举的中文标签文本直接存储。

### 6.2 `upsert_entry`

- 签名改为 `upsert_entry(conn, kind, lemma, category: str = "")`。
- 冲突更新时，仅当新类别非空才覆盖旧值：

```sql
INSERT INTO entries(kind, lemma, category) VALUES(?, ?, ?)
ON CONFLICT(kind, lemma) DO UPDATE SET
  category = CASE WHEN excluded.category <> ''
                  THEN excluded.category ELSE entries.category END
RETURNING id
```

### 6.3 `POST /api/occurrences`

- 仅当 `item.type == "grammar"` 且 `item.grammar_category` 非空时写入类别，
  经 `normalize_grammar_category()` 规范化（列表外折叠为「其他」）。
- 其他类型、字段缺失时写 `''`，不误标「其他」。

### 6.4 读接口

- `GET /api/articles/{id}/marks`：SELECT 增加 `e.category`，条目 dict 增加
  `category`。
- `GET /api/review/queue`：`due_queue` SELECT 增加 `e.category`。
- `GET /api/entries`：`export.QUERY` 增加 `e.category`；导出函数按 HEADER
  白名单取列，因此 Markdown / CSV 输出不变。

### 6.5 即时分析提示词

- `analyze_snippet` 的提示词补上 `grammar_category`：仅 `type == "grammar"`
  时需要，从与预分析相同的 45 个受控类别中原样复制，否则填「其他」。
  避免「划词未命中 → 即时分析」的语法词条永远无类别。

## 7. 前端变更

- `web/app.js`
  - `appendMark`：`item.category` 非空时追加类别标签（文本节点 + `textContent`，
    不用 innerHTML 拼接用户数据）。
  - `renderRightPanel`：语法列表按 `category` 稳定排序，插入分组标题；
    类别为空归入「未分类」。
  - `showPopup`：`grammar_category` 并入现有的 `grammar_role · why` 行。
  - `save()`：POST 成功后**重新 `GET /marks` 并整体重渲染右栏**，不再本地
    `addToSidebar`。理由：预分析 item 的字段名是 `grammar_category`，与读接口的
    `category` 不同；且 `/api/occurrences` 对重复保存返回 `recorded: false`，
    本地追加会产生重复项。服务端为准可同时解决这两个问题，删除 `addToSidebar`。
- `web/review.html`：卡片内新增类别徽标槽位。
- `web/review.js`：卡片渲染类别徽标；列表视图按类别插入分组行，
  非语法词条归入「词汇与短语」。队列顺序不变。
- `web/style.css`：新增 `.cat-chip`、`.group-head`、`.card-category`，
  只用既有 CSS 变量（`--accent` / `--muted` / `--line`），四套主题无需新增色值。

## 8. 迁移与备份

- `app/main.py` 末尾在导入时就执行 `app = create_app(str(DB_PATH))`，而 `create_app`
  首先调用 `init_db`；测试文件普遍 `from app.main import create_app`。因此
  **一旦 `SCHEMA_VERSION` 改成 4，下一次 `uv run pytest` 就会迁移真实库**，
  不会等到手动启动服务。
- 因此备份是**硬前置步骤**，必须在改 `SCHEMA_VERSION` 之前完成：
  把 `data/library.db` 复制为 `data/library.db.bak7-pre-entry-category`，
  并向用户确认。沿用 bak6 的手工做法，不在 `init_db` 内新增自动备份（避免扩大范围）。
- 迁移只加列，不改旧行；旧 word / phrase 词条类别为空。

## 9. 测试计划（严格 RED → GREEN）

1. `test_db`：新库 `entries` 含 `category` 列，`user_version == 4`。
2. `test_db`：v3 结构的库经 `init_db` 后新增列，旧行保留。
3. `test_db`：`upsert_entry` 写入类别；再次以空类别 upsert 不覆盖已有值。
4. `test_api`：`/api/occurrences` 对语法项写入规范化类别，未知类别折叠为「其他」。
5. `test_api`：`/marks`、`/api/review/queue`、`/api/entries` 返回 `category`。
6. `test_analyze`：即时分析提示词包含 `grammar_category` 与受控类别列表。
7. `test_pages`：`app.js` / `review.js` / `style.css` / `review.html` 含新增的
   分组与徽标钩子；`save()` 在 POST 之后走 `renderRightPanel` 重新拉取，
   不再调用 `addToSidebar`。
8. 全量 `uv run pytest`；浏览器手工复验右栏分组、浮层类别、复习两种视图。

## 10. 风险与边界

- 同一短语在不同文章被判成不同类别时，以最后一次写入为准；受控枚举下
  预期稳定，不再额外做投票或冲突提示。
- 类别标签使用中文，CSS 需允许换行/省略，避免撑破窄右栏。
- 旧文章 payload 仍有类别字段，本次不借用它回填 `entries`。

## 11. 实施顺序

0. 备份真实库为 `data/library.db.bak7-pre-entry-category`（在改任何 schema 之前，
   因为测试导入会触发迁移）。
1. schema v4 + `upsert_entry` + 写接口（TDD）。
2. 三个读接口返回类别（TDD）。
3. 即时分析提示词补类别（TDD）。
4. 前端：右栏 / 浮层 / 复习卡片 / 列表分组（test_pages + 浏览器复验）。
5. 启动一次确认迁移已完成，检查数据量与全量测试。

## 12. 留给实施者的决定

- 右栏分组标题的具体间距与字号，沿用右栏既有 `side-head` 视觉体系即可。
- 列表视图分组行的顺序：语法组按类别标签拼音序，其后为「词汇与短语」；
  若实现时发现更自然的顺序（如按数量降序），可自行调整。
