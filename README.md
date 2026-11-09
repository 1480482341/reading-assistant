# 英语阅读工作台

本地单机阅读器：订阅源自动备好英文长文，划词即得中文释义与语法拆解，所有主动查阅的词条入库并按间隔重复复习。

## 启动

```bash
uv run uvicorn app.main:app --port 8000
```

打开 <http://127.0.0.1:8000> 阅读，<http://127.0.0.1:8000/library> 逛文章库，<http://127.0.0.1:8000/shelf> 看书架，<http://127.0.0.1:8000/review> 复习。读完一篇点阅读页左侧「读完了」，当天队列就不会再推它。

启动时后台线程会抓取订阅源、入库新文章并预分析（正文立即可读，词条随后出现）。没有常驻守护进程，关掉应用即停止。

## 文章库

文章库列出全部文章（含已读），可按状态与兴趣标签筛选，每篇标题带中文释义，点击即进入阅读页。标签为受控词表（AI、Computing、Physics、History 等 16 个），一篇文章 1–3 个。

中文标题与标签由启动时的后台任务调用本机模型生成并存入数据库。尚未生成的文章只显示英文标题，下次启动会自动重试；模型不可用时阅读不受影响。

## 书签、标色与书架

- **标色**：先点阅读页左侧的色块（红 / 绿 / 黄）进入标色模式，再划选正文即着色；同一选区换个颜色会覆盖原色。色块右侧的「×」是取消标色：点它进入擦除模式，划选即可清除——选中范围里只要碰到已标色的文字，那条标色就整条删除；同时选中普通文字不受影响。也可以直接点已标色的文字，在弹出的小框里改色或取消。标色与书签全程本地，不调用模型。
- **书签**：阅读页左侧「＋ 书签」把当前位置存为书签（锚定到所在段落），列表支持点击跳转与删除。
- **书架**：阅读页左侧「加入书架」收藏文章；书架页有两个标签——「书架」与「阅读历史」，历史记录每次打开的文章，历史项可一键加入书架。
- **主题**：顶栏「护眼绿」按钮循环切换四套主题（护眼绿 / 暗黑 / 浅色 / 暖黄），选择保存在浏览器里，跨页面保持、刷新不闪白。
- 每篇的标色数与书签数显示在文章库角标里，并可用「只看有标注的」筛选；四个页面顶栏统一为 阅读 / 文章库 / 书架 / 复习 / 主题 / 导出。

## 数据

- 数据库：`data/library.db`（单文件 SQLite，删掉即清空重来）
- 预分析结果只服务划词提示，**不计入频次**；只有你确认过的词条才写命中记录
- 划词缓存（`lookups` 表）也在同一个库里，删库一并清空
- 备份就是复制这个文件

## 手动收集

付费墙文章和 PDF 走接口兜底（`POST /api/articles/ingest`）：

```bash
# 粘贴正文
curl -X POST http://127.0.0.1:8000/api/articles/ingest \
  -H 'Content-Type: application/json' \
  -d '{"title":"我的文章","text":"正文……"}'

# 给一个本地 PDF
curl -X POST http://127.0.0.1:8000/api/articles/ingest \
  -H 'Content-Type: application/json' -d '{"pdf_path":"C:/papers/attention.pdf"}'
```

## 换订阅源

订阅源存在数据库 `sources` 表里，启动时按 `enabled = 1` 抓取：

```sql
-- 停用某个源
UPDATE sources SET enabled = 0 WHERE name = 'JSTOR Daily';
-- 加一个新源（link_pattern 只保留链接含该子串的条目，留空表示不过滤）
INSERT INTO sources(name, feed_url, topic, link_pattern, enabled)
VALUES('The Marginalian', 'https://www.themarginalian.org/feed/', 'humanities', '', 1);
```

`topic` 决定每日队列轮换的顺序（`tech` → `history` → `humanities`）。改完重启应用生效。

默认源：Quanta Magazine（tech）、JSTOR Daily（history）、Aeon 的 essays（humanities）。

## 导出

浏览器打开即可下载：

- Markdown：<http://127.0.0.1:8000/api/export?format=md>
- CSV：<http://127.0.0.1:8000/api/export?format=csv>

## 健康检查

```bash
curl http://127.0.0.1:8000/api/health
# {"claude_available": true, "db": "ok"}
```

`claude_available` 为 false 时，阅读页顶部会出现横幅：划词降级为「只记录、不分析」，预分析暂停，阅读与复习不受影响。

## 依赖本机模型

所有模型调用走本机 `claude` 命令行（无 API key），每次调用在空的临时目录里执行。单次超时 300 秒，按 800 词一块分块分析，预分析目标为每 5 词 1 条。

划词先查预分析结果与本地缓存（同一篇里查过的词会记住），命中即毫秒返回；都没命中才调模型，单次约 5 秒（划词用 haiku 且关闭 MCP 加载，预分析仍用默认模型）。

## 测试

```bash
uv run pytest
```
