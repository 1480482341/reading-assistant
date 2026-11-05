# 英语阅读工作台

本地单机阅读器：订阅源自动备好英文长文，划词即得中文释义与语法拆解，所有主动查阅的词条入库并按间隔重复复习。

## 启动

```bash
uv run uvicorn app.main:app --port 8000
```

打开 <http://127.0.0.1:8000> 阅读，<http://127.0.0.1:8000/review> 复习。

启动时后台线程会抓取订阅源、入库新文章并预分析（正文立即可读，词条随后出现）。没有常驻守护进程，关掉应用即停止。

## 数据

- 数据库：`data/library.db`（单文件 SQLite，删掉即清空重来）
- 预分析结果只服务划词提示，**不计入频次**；只有你确认过的词条才写命中记录
- 备份就是复制这个文件

## 手动收集

付费墙文章和 PDF 走接口兜底（`POST /api/articles/ingest`）：

```bash
# 粘贴正文
curl -X POST http://127.0.0.1:8000/api/articles/ingest \
  -H 'Content-Type: application/json' \
  -d '{"title":"我的文章","text":"正文……"}'

# 给一个链接（自动提取正文）
curl -X POST http://127.0.0.1:8000/api/articles/ingest \
  -H 'Content-Type: application/json' -d '{"url":"https://example.com/post"}'
```

PDF 走 `app.collect.ingest_pdf(conn, path)`。

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

所有模型调用走本机 `claude` 命令行（无 API key），每次调用在空的临时目录里执行。单次超时 300 秒，按 800 词一块分块分析。

## 测试

```bash
uv run pytest
```
