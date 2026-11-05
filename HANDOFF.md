# 交接说明（英语阅读工作台）

- 日期：2026-11-05
- 分支：feat/reading-assistant
- 项目根：E:\AI_Project\reading-assistant
- 状态：**12 / 12 任务完成，54 个测试全绿，真实文章与浏览器交互均已验证，最终审查的两个 Critical 已修复**

## 1. 交付内容

一个本地阅读工作台：启动后后台抓取 RSS、提取正文、按 800 词分块调本机 `claude -p` 预分析；阅读页划词即得释义与语法拆解，确认的词条入库并按三档间隔复习。

- 设计文档：E:\AI_Project\plan\2026-11-05-reading-assistant-design.md
- 实施计划：docs\superpowers\plans\2026-11-05-reading-assistant.md
- 启动：`uv run uvicorn app.main:app`（阅读 `/`，复习 `/review`）
- 数据：`data/library.db`（单文件 SQLite）
- 测试：`uv run pytest` → 54 passed

## 2. 本轮修掉的问题（按重要性）

1. **预分析超时**：2000 词/块 + 要求 150–200 条会超过 120s。改为 800 词/块、条目目标 = 词数/15、超时 300s，并让 `claude` 调用在空临时目录执行（原先会继承项目 cwd）。真实文章 2312 词 → 3 块并发 151 条 84.8s，`status=ready`。
2. **确认的词条不进复习队列**（审查 Critical）：`record_occurrence` 从不建 review 行，复习永远为空。现已接线，并回填了本机已有词条。
3. **复习列表存储型 XSS**（审查 Critical）：`review.js` 用 `innerHTML` 拼接来自文章文本的 lemma/gloss。改为 `/api/entries` + DOM `textContent`。
4. 单块失败不再丢弃整篇结果；卡在 `running` 的预分析启动时重试；长选区改为截断而非静默丢弃；语法点登记进 `grammar_terms`；ingest 接口支持 `pdf_path`；预分析成功后文章状态置 `ready`。
5. 模型不可用时的顶部横幅与「只记录、不分析」降级（设计 §风险表要求）。

## 3. 已知遗留（非阻塞）

- git 提交身份是临时环境变量指定的，仓库仍未配置 user.name/email
- 最终审查的 5 个次要项已全部修掉：JSON 解析改用 `raw_decode` 扫描；新增「读完了」按钮与 `POST /api/articles/{id}/read`，`pick_today` 的已读过滤不再是死逻辑；启动抓取先查 URL 再下载正文；超时/非零退出不再触发重试（新增 `ModelCallError`），`data/library.db` 改为绝对路径；`POST /api/review/{id}` 对不存在的词条返回 404

## 4. 仍需用户拍板

- 旧方案处置：删除 `english-immersion` skill 目录与 `E:\AI_Project\plan\english-learning-plan.md`（按流程需再次确认）
- 分支归宿：仓库只有 `feat/reading-assistant`，没有 main；是否新建 main 并合并

## 5. 文件索引

- 后端：app\db.py、sources.py、analyze.py、collect.py、review.py、export.py、main.py
- 前端：web\index.html、app.js、style.css、review.html、review.js、review.css
- 测试：tests\（数据库、采集、预分析、接口、队列、复习、导出、页面、收集、端到端）
