# 交接说明（英语阅读工作台）

- 日期：2026-11-05
- 项目根：E:\AI_Project\reading-assistant
- 分支：main（已与 origin/main 同步）
- 状态：12 / 12 任务完成，62 个测试全绿，真实文章与浏览器交互均已验证，最终审查的 Critical 与全部次要项已修复，代码已推送到 GitHub

## 1. 已完成的核心逻辑与关键决策

### 功能

- 本地单机阅读工作台：启动时后台抓 RSS → trafilatura 提取正文 → 按 800 词分块调本机 claude 预分析 → 阅读页划词即得中文释义与语法拆解 → 确认的词条入库 → 三档间隔复习。
- 阅读页：当天队列按 tech → history → humanities 轮换；划词先查本地预分析结果，未命中才现场调模型；右栏显示本篇已标记的词与语法点；顶栏「读完了」把文章移出队列并自动切下一篇。
- 复习页：卡片模式（认识 / 不认识）+ 列表模式（全部词条与频次）。
- 手动收集：POST /api/articles/ingest 支持粘贴正文、给 URL、给本地 PDF 路径。
- 导出：/api/export?format=md 与 format=csv。
- 健康检查：/api/health 返回 claude_available 与 db 状态；模型不可用时页面顶部出现横幅，划词降级为「只记录、不分析」。

### 关键决策

- 预分析结果不计频次，只有用户点「记下来」确认的划词才写 occurrences，否则频次排序失真。
- 词条按原形归并，释义按上下文存在每次命中上，避免一词多义互相覆盖。
- 复习三档间隔：今天 / 3 天 / 7 天；7 天档连续两次答对即毕业移出队列。
- 语法点独立成条，并登记进 grammar_terms 受控表（映射不上时新建，状态 pending 等人工收敛）。
- 模型调用约定：只用本机 claude 命令行，不引入 API key；每次调用在空的临时目录执行，避免继承项目上下文。
- 预分析参数（实测调优后）：每块 800 词、条目目标 = 词数 / 15、单次超时 300 秒、最多 3 路并发。实测 2312 词文章 3 块并发 151 条 84.8 秒（原 2000 词/块 + 150–200 条会超过 120 秒超时失败）。
- 分块失败处理：单块失败不再丢弃整篇，成功的块照常合并；全部失败才标记 failed。
- 重试策略：只有 JSON 解析失败才重试一次；超时 / 非零退出属于 ModelCallError，不重试。
- 无守护进程：打开应用时抓取与预分析在后台线程进行，错过批次下次补抓；中断后卡在 running 的预分析下次启动会重试。
- 订阅源按实测调整：Quanta、JSTOR Daily、Aeon（只取 essays 链接）为主源；Longreads 只提取到 194 词已移出；Hacker News 本机连不上。sources 表的 link_pattern 列承载链接过滤。
- 数据库为单文件 SQLite（data/library.db），路径基于项目根绝对定位，不依赖工作目录。

## 2. 遗留的 Bug 与待办事项

- 无已知 Bug；测试 62 passed（唯一噪音是第三方 httpx 弃用警告，非失败）。
- 可选清理：本地仍有一个改写历史前的备份分支 backup/rewrite-before-identity（未推到远端），确认 GitHub 显示正常后可删除。
- 隐私提醒：改写历史前远端根提交的作者是你的真实 QQ 邮箱，该提交已不在 main 历史中，但 GitHub 对旧提交有缓存，短时间内按提交哈希仍可能可见。
- 实际使用中可能想调：每日队列篇数（pick_today 的 limit，当前 5）、订阅源清单、复习卡片的字段展示。
- 旧方案处置已完成：english-immersion skill 与 12 周计划文件已删除，完整备份在 E:\AI_Project\backup\english-immersion-2026-11-05\。

## 3. 必须遵守的约束条件

- 模型通道只用本机 claude 命令行，不引入 API key；调用时工作目录设为空的临时目录。
- 所有模型输出必须按 JSON 解析，解析失败重试一次，再失败标记该块失败且不影响阅读。
- 预分析结果绝不写入 occurrences；频次只来自用户确认的查询。
- 数据库为单文件 SQLite，位置 data/library.db；无守护进程。
- 前端为原生 JS，无 npm、无构建步骤；界面文案中文，代码与注释英文。
- 开发方式：严格 RED→GREEN，每个改动先写失败测试，实现后跑全量测试。
- 破坏性操作（删 skill、删计划文件、改写历史、强推）执行前必须再次向用户确认。
- 提交身份已全局配置为 xhs / 128921592+1480482341@users.noreply.github.com，不再需要环境变量绕过。

## 4. 提交与仓库信息

- 远端：origin → git@github.com:1480482341/reading-assistant.git（走 SSH）
- 网络注意：本机 DNS 解析到的 github.com 亚洲节点 443 被封，已把 ~/.ssh/config 里的 github.com 指向 ssh.github.com:443，HTTPS 方式推不动，统一用 SSH
- 分支：main，跟踪 origin/main，本地与远端一致
- 最新提交：abbfec3 fix: grading an unknown entry returns 404
- 提交总数：22，作者全部为 xhs / 128921592+1480482341@users.noreply.github.com（历史已统一改写并强推）
- 本地备份分支：backup/rewrite-before-identity（改写前的旧哈希，未推送）
- 被 git 忽略的内容：data/（阅读数据）、.superpowers/（台账与工作区）、.venv/、.claude/、各类缓存
- 常用命令：启动 uv run uvicorn app.main:app --port 8000；测试 uv run pytest；提交 git add -A 后 git commit 再 git push

## 5. 文件索引

- 设计文档：E:\AI_Project\plan\2026-11-05-reading-assistant-design.md
- 实施计划：docs\superpowers\plans\2026-11-05-reading-assistant.md
- 台账（git 忽略）：.superpowers\sdd\2026-11-05-reading-assistant\progress.md
- 后端：app\db.py（库与 schema）、app\sources.py（抓取与提取）、app\analyze.py（分块、模型调用、JSON 容错）、app\collect.py（手动入库与启动任务）、app\review.py（复习状态机）、app\export.py（导出）、app\main.py（路由与 lifespan）
- 前端：web\index.html、web\app.js、web\style.css、web\review.html、web\review.js、web\review.css
- 测试：tests\ 下按模块划分，含 tests\test_collect.py、tests\test_e2e.py 与 tests\fixtures\
- 使用说明：README.md（启动、数据位置、换订阅源、导出、手动收集、健康检查）

## 6. 当前数据状态

- data/library.db：26 篇文章（1 篇已预分析 ready，25 篇 pending 等下次启动分析）
- 词条 1 个（introspection），对应复习记录 1 条
- 首次启动后后台会依次预分析积压文章，一篇约 1–2 分钟，期间不影响阅读
