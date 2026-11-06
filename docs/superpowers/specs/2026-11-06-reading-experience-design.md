# 阅读体验增强 · 设计文档

- 日期：2026-11-06
- 状态：**待批准**
- 项目：reading-assistant（本地单机 Web 应用）

---

## 1. 意图

第一版把"读 → 查 → 记 → 复习"的链路跑通了，但**读的过程本身**还是薄弱的：标记栏内容一多就看不见、只有一种配色、一篇文章读不完就只能从头再来、想强调的句子没法留下痕迹、下次打开文章时上次做的标记也看不到。

这一轮解决的是同一件事：**让"读到一半放下、下次接着读"成为可用状态**。文章本身是长文，读不完是常态；如果每次回来都要重新找位置、重新找回上次注意的句子，这个工具就会被弃用。

## 2. 目标

| 编号 | 目标 |
|---|---|
| G1 | 右侧信息栏内容超出视口时可独立滚动，不再被截断 |
| G2 | 提供四套可切换主题（护眼绿为默认、暗黑、浅色、护眼暖黄），三个页面统一生效并记住选择 |
| G3 | 文章内可插入多个书签，从侧栏列表一键跳回 |
| G4 | 可对任意选区标红 / 绿 / 黄，用于下次重点看 |
| G5 | 书签与标色持久化，重开文章原样复原 |
| G6 | 手动收藏文章到「书架」 |
| G7 | 自动记录阅读历史（每打开一次计一次） |
| G8 | 右侧信息栏在打开文章时就展示该篇已有的词条与语法点（现在刷新即空） |

## 3. 非目标

- 不做自动续读（滚动位置自动恢复）——用户明确选择手动书签
- 不做标注导出（md / csv 暂不含书签与标色）
- 不做标色备注（只上色，不挂文字）
- 不做多用户、云同步、移动端适配
- 不改动预分析、划词模型调用、复习算法

## 4. 反目标（做出来也算失败）

1. **标色与划词互相打断** —— 想标色时弹出释义框，或反过来。
2. **标记错位** —— 重开文章时高亮落在不相干的句子上。宁可丢弃该条标记，也不能错标。
3. **标色带来明显延迟** —— 上色必须是本地的、即时的，不经过模型。
4. **主题切换闪烁** —— 打开页面时先白后黑。

## 5. 方案选择

### 5.1 标记锚定方式（已在对话中确定）

正文在渲染时是 `articles.text` 按空行切段、一段一个 `<p>`。

- **方案一（选中）：段落索引 + 段内字符偏移 + 原文片段**
  标记存 `(para_index, start_offset, end_offset, quote)`。重开时按段落定位，再用 `quote` 与段落中对应区间的文字比对一次，不一致则丢弃该条标记并记日志。
  优点：与现有逐段渲染完全吻合；重复文本不成问题；越界与失效可安全处理；测试容易写。
  代价：文章被重新抓取、段落结构变化时旧标记失效（安全丢弃）。

- 方案二：全文字符偏移。数据结构更简单，但任何分段/空白归一化变动都会整体错位，脆弱，未选。
- 方案三：文本锚定（选中文字 + 前后上下文搜索定位）。对正文改动更鲁棒，但重复文本需消歧、实现成本最高，对"文章入库后基本不变"的本项目收益低，未选。

### 5.2 交互位置（已在对话中确定）

- 标色：**先点左侧色块进入"标色模式"，再划选**。标色模式下划选不弹释义框；非标色模式保持现有的划词即释义。
- 布局：**左 = 操作**（书签、标色、读完了），**中 = 正文**，**右 = 信息**（词条、语法点）。
- 书架：**手动收藏**，与**阅读历史**并列放在新页面 `/shelf` 的两个标签里。

## 6. 设计细节

### 6.1 数据库（user_version 1 → 2）

新增四张表，全部 `ON DELETE CASCADE` 挂在 `articles(id)` 上。

```sql
CREATE TABLE IF NOT EXISTS annotations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id   INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    para_index   INTEGER NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset   INTEGER NOT NULL,
    quote        TEXT NOT NULL,
    color        TEXT NOT NULL,          -- red | green | yellow
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_annotations_article ON annotations(article_id);

CREATE TABLE IF NOT EXISTS bookmarks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id   INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    para_index   INTEGER NOT NULL,
    offset_ratio REAL DEFAULT 0,          -- 段内位置 0.0–1.0，用于精确跳转
    label        TEXT DEFAULT '',         -- 段首约 40 字，列表展示
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

迁移沿用现有机制（`PRAGMA user_version` 门控），在 `init_db` 里追加 v2 步骤，只在旧库执行一次。已有数据不动。

**重叠规则**：新建标色时，删除与该区间重叠的旧标色（后建者覆盖前建者）。这样避免嵌套渲染的复杂度，行为也可预测。

### 6.2 段落索引的稳定约定

`para_index` 指 `articles.text.split(/\n+/).filter(Boolean)` 之后再做一次 trim 的数组下标。前后端必须用同一套切分规则；前端渲染与后端校验各自实现一份，但规则写进测试锁死（同一段文本切出的段数、每段内容一致）。

### 6.3 API

新增（全部在 `app/main.py`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles/{id}/annotations` | 该篇全部标色 |
| POST | `/api/articles/{id}/annotations` | 新建标色，body: `para_index,start_offset,end_offset,quote,color` |
| PATCH | `/api/annotations/{id}` | 改颜色，body: `color` |
| DELETE | `/api/annotations/{id}` | 删除 |
| GET | `/api/articles/{id}/bookmarks` | 该书签列表 |
| POST | `/api/articles/{id}/bookmarks` | 新建书签，body: `para_index,offset_ratio,label` |
| DELETE | `/api/bookmarks/{id}` | 删除 |
| GET | `/api/articles/{id}/marks` | 该篇已入库的词条与语法点，用于打开时就填充右栏 |
| POST | `/api/articles/{id}/open` | 记一次阅读历史 |
| GET | `/api/shelf` | 书架列表 |
| POST | `/api/shelf/{id}` | 加入书架（幂等） |
| DELETE | `/api/shelf/{id}` | 移出书架 |
| GET | `/api/history` | 阅读历史，按 `last_opened` 倒序 |

改动既有接口：

- `GET /api/articles/library` 每行追加 `in_shelf`、`annotation_count`、`bookmark_count`、`occurrence_count`。
- `GET /api/articles/{id}` 追加 `in_shelf` 与 `annotations`、`bookmarks`，使阅读页一次请求即可复原全部标记（减少首屏往返）。

路由顺序注意：`/api/articles/library` 必须继续注册在 `/api/articles/{article_id:int}` 之前。新增的带子路径的路由不受这条影响。

### 6.4 前端布局与结构

`web/index.html` 的 `main.layout` 改为三栏：

```
grid-template-columns: 176px minmax(0,1fr) 280px;
```

- **左栏 `.actions`**（sticky，可滚动）：`＋书签` 按钮、书签列表（点击跳转、× 删除）、三个色块（激活态高亮）、`读完了`。
- **中栏 `.reader`**：不变。
- **右栏 `.sidebar`**（sticky，新增 `max-height: calc(100vh - 48px); overflow-y: auto`）：`本篇已标记`、`语法点`。

G1 的修复就是右栏这两行；左栏同样处理。

窄屏（< 900px）退化为单栏堆叠，三块依次排列，不做抽屉。

### 6.5 标色渲染

渲染流程（`app.js`）：

1. 取 `full.text`，按同一规则切成段落数组。
2. 每段按该段内的标色区间排序，切成 `[纯文本][高亮][纯文本]…` 片段，逐片段 `escapeHtml` 后写入 `<span class="hl hl-red|hl-green|hl-yellow" data-annotation-id="N">`。
3. 点击高亮元素：弹出小浮层，提供「改红 / 改绿 / 改黄 / 取消标色」。

**标色模式**：点色块 → `colorMode = 'red'`，色块加 `.active`。此时 `mouseup` 走标色分支：取选区、换算成 `(para_index, start, end)`，`POST` 成功后本地插入高亮并退出……**不退出**，保持模式直到再次点击同一色块或按 Esc，便于连续标多处。非标色模式下 `mouseup` 行为不变。

选区跨段时：只取起点所在段落内的部分，不跨段标色（简化实现；跨段选区在长文里罕见，且视觉上会打断段落结构）。

### 6.6 书签

`＋书签` 时计算当前视口顶部对应的段落：

- 遍历所有 `<p>`，取第一个 `getBoundingClientRect().top >= topbar 高度` 的段落作为 `para_index`；
- `offset_ratio = clamp((视口顶 - 该段top) / 该段高, 0, 1)`；
- `label` 取该段前 40 字。

跳转时 `p.scrollIntoView()` 后按 `offset_ratio * p.offsetHeight` 做微调。

### 6.7 主题系统

`web/style.css` 顶部用属性选择器定义四套变量：

```css
:root, [data-theme="light"] { --ink:#1b1b1b; --bg:#faf9f6; … }      /* 现有配色 */
[data-theme="eye-green"] { --ink:#22301f; --bg:#d6e8d0; … }
[data-theme="dark"]      { --ink:#dfe3e8; --bg:#14161a; … }
[data-theme="eye-warm"]  { --ink:#33291b; --bg:#f5e9c8; … }
```

- 默认主题为 `eye-green`。若 `<html>` 上没有 `data-theme`，`:root` 规则保证有可用配色（= 浅色）。
- 三个页面 `<head>` 内联一小段脚本，读 `localStorage['ra-theme']` 并写 `document.documentElement.dataset.theme`，避免首屏闪烁（反目标 4）。
- 顶栏按钮循环 `eye-green → dark → light → eye-warm`，写回 localStorage。
- 现有硬编码色（`.banner` 的米黄、按钮白字、library.css / review.css 各一处白字）改为变量，新增 `--banner-bg`、`--banner-ink`、`--on-accent`。
- 高亮色用半透明 `rgba`，暗色主题下覆盖为更低透明度，避免刺眼。

### 6.8 书架页

新文件 `web/shelf.html` / `web/shelf.js` / `web/shelf.css`，路由 `GET /shelf`。

- 两个标签：「我的书架」按 `added_at` 倒序；「阅读历史」按 `last_opened` 倒序，显示打开次数与最后打开时间。
- 每项：标题（中文标题优先）、来源、状态、标色数 / 书签数，点击进入 `/ ?id=N`。
- 书架项提供「移出书架」；历史项提供「加入书架」。
- 顶栏四个页面统一为：阅读 / 文章库 / 书架 / 复习 /（主题按钮）/ 导出。

### 6.9 文章库

- 每行增加角标：`书签 N · 标色 M · 词条 K`，以及「＋书架 / 已在书架」按钮。
- 状态筛选旁增加一个 `有标注` 复选筛选（客户端过滤 `annotation_count + bookmark_count > 0`）。

## 7. 留给实现者的决定

- 左栏具体宽度、色块尺寸与间距，按视觉需要微调。
- 高亮浮层的定位与关闭方式（点击空白 / Esc）与现有 popup 保持一致即可。
- `reading_history` 的 `first_opened` 是否展示——默认可不展示。
- 各 API 的入参校验细节（颜色白名单、偏移非负、`end > start`）。
- 书架与历史空状态文案。

## 8. 验证方式

- 后端：pytest 覆盖四个新表、迁移（v1 库升级后数据完整）、API 的正常与非法输入、重叠标色的替换行为、段落切分规则。
- 前端：手工流程验证——开文章 → 标三处色 → 加两个书签 → 刷新 → 标记与书签原样复原；切换四套主题、跨页保持、刷新不闪白；文章库与书架角标与筛选；右栏内容足够长时可独立滚动。
- 回归：现有 108 个测试全绿；划词、预分析、复习、导出不受影响。

## 9. 约束

- 前端原生 JS，无 npm、无构建步骤；界面文案中文，代码与注释英文。
- 数据库单文件 SQLite，位置 `data/library.db`；迁移用 `PRAGMA user_version` 门控且只跑一次。
- 标色与书签全程本地，不调用模型。
- 严格 RED→GREEN：每个改动先写失败测试。
- 改动前备份 `data/library.db`。
