# 交接说明（英语阅读工作台）

- 日期：2026-11-05（文章库功能完成后更新）
- 项目根：E:\AI_Project\reading-assistant
- 分支：main（与 origin/main 已同步）
- 状态：96 个测试全绿，文章库功能与第二轮修复已完成（改动尚未提交）

## 1. 已完成的核心逻辑与关键决策

### 原有功能（保持不变）

- 本地单机阅读工作台：启动时后台抓 RSS → trafilatura 提取正文 → 按 800 词分块调本机 claude 预分析 → 阅读页划词即得中文释义与语法拆解 → 确认的词条入库 → 三档间隔复习。
- 阅读页：当天队列按 tech → history → humanities 轮换；划词先查本地预分析结果，未命中才现场调模型；右栏显示本篇已标记的词与语法点；顶栏「读完了」把文章移出队列并自动切下一篇。
- 复习页：卡片模式（认识 / 不认识）+ 列表模式（全部词条与频次）。
- 手动收集：POST /api/articles/ingest 支持粘贴正文、给 URL、给本地 PDF 路径。
- 导出：/api/export?format=md 与 format=csv。
- 健康检查：/api/health 返回 claude_available 与 db 状态；模型不可用时页面横幅提示，划词降级为只记录。

### 本次新增：文章库与兴趣标签

- 新增文章库页面 /library：列出全部文章（含已读），默认按发布日期倒序。
- 筛选：状态（全部 / 待分析 / 可读 / 已读）与 16 个兴趣标签，标签可多选叠加，按「同时包含」过滤；「全部」按钮复位状态并清空标签；筛选在前端完成。
- 每篇文章卡片显示：英文标题、中文释义、来源 · 日期 · 字数 · 状态、标签；中文释义为空时只显示英文标题。
- 点击卡片进入 /?id=N，阅读页按 id 打开任意文章；无 id 时仍按当天队列取第一篇；文章不存在时显示友好提示。
- 所有页面顶栏加入「文章库」入口。
- 中文标题与标签由独立后台任务生成（方案 A）：启动时在抓取之后、预分析之前，把缺中文标题的文章每 8–10 篇打包成一次模型调用，结果写入数据库。
- 标签走受控词表（16 个）：AI、Computing、Physics、Math、Biology、Medicine、Psychology、Philosophy、History、Politics、Economics、Environment、Art、Literature、Culture、Society；每篇 1–3 个，模型可留空但不硬贴；非法标签丢弃、重复去重、超过 3 个截断。
- 中文标题上限 30 字，超出截断。
- 以 title_zh 是否为空作为「是否已处理」的标记：生成失败保持为空，下次启动重试。
- 重试策略：模型输出解析失败或返回项数与输入批次不符时，重试一次并追加「只返回 JSON 数组」的提示；再次失败则整批丢弃、不写库，下次启动重试，避免错位写库。
- 数据库变更：articles 增加 title_zh 列；新增 article_tags 表（article_id + tag 联合主键）；旧库启动时自动迁移补列。
- 文章库接口 /api/articles/library 返回 id、title、title_zh、topic、source、published_at、word_count、status、tags；必须注册在按 id 查详情的路由之前，否则会被路径参数吞掉。
- 文章详情接口返回值增加 title_zh。

### 本次新增：第二轮修复（2026-11-05）

- 划词提速： `/api/lookup` 与 `/api/lookup/miss` 都先归一化（去首尾标点、转小写）再匹配；未命中的模型结果写入新的 `lookups` 表（article_id + 归一化文本），同一篇里重复划同一个词直接命中缓存，不再调模型。实测首次 10.8 s，重复 3 ms。
- 实测换模型没用：本机 `claude -p` 单次约 8.2–8.5 s，haiku 与默认模型几乎一样，瓶颈在 CLI 启动，所以只做「少调模型」不做「换模型」。
- 文章库排序真正的 bug：`published_at` 存的是 RSS 原文（`Wed, 04 Nov 2026…`），按字符串倒序得到的是错序。现在入库时用 `email.utils.parsedate_to_datetime` 归一化成 `YYYY-MM-DD`，`init_db` 启动时把旧数据一并迁移。原交接里「NULL 排最前」的说法不成立：SQLite 的 `DESC` 本来就把 NULL 排最后，已加回归测试锁住。
- 标签词表改为后端下发：新增 `GET /api/tags`，前端不再重复维护 16 个常量。
- 文章库空态：区分「文章库为空」「加载失败」「没有匹配的文章」三种文案（原先空库时提示被隐藏）。
- `/?id=` 非数字：后端详情路由改为 `{article_id:int}`（非数字 404），前端也先校验，显示「文章不存在」而不是卡在「载入中…」。
- 审查后补的两处：对不存在的 article_id 划词直接 404（不再白跑一次模型再 500）；预分析重跑成功时清空该篇的 lookups 缓存（pending 文章本来就在队列里，可先产生缓存）。
- 审查建议也做了两条：日期迁移用 `PRAGMA user_version` 门控（只在旧库跑一次，不再每次启动全表扫描）；POST 接口改用 Pydantic body 模型，缺 `article_id` 等字段返回 422 而不是 500。
- 日志：`create_app` 里配置 `app` 命名空间 logger（INFO + StreamHandler），启动任务的「启动任务完成: 新增 x 篇…」现在会打印。

### 既有设计决策（继续有效）

- 预分析结果不计频次，只有用户点「记下来」确认的划词才写 occurrences，否则频次排序失真。
- 词条按原形归并，释义按上下文存在每次命中上，避免一词多义互相覆盖。
- 复习三档间隔：今天 / 3 天 / 7 天；7 天档连续两次答对即毕业移出队列。
- 语法点独立成条，并登记进 grammar_terms 受控表（映射不上时新建，状态 pending 等人工收敛）。
- 模型调用约定：只用本机 claude 命令行，不引入 API key；每次调用在空的临时目录执行，避免继承项目上下文。
- 预分析参数（实测调优后）：每块 800 词、条目目标 = 词数 / 15、单次超时 300 秒、最多 3 路并发。
- 分块失败处理：单块失败不丢弃整篇，成功的块照常合并；全部失败才标记 failed。
- 重试策略（预分析）：只有 JSON 解析失败才重试一次；超时 / 非零退出属于 ModelCallError，不重试。
- 无守护进程：打开应用时抓取与预分析在后台线程进行，错过批次下次补抓；中断后卡在 running 的预分析下次启动会重试。
- 订阅源：Quanta、JSTOR Daily、Aeon（只取 essays 链接）为主源；sources 表的 link_pattern 列承载链接过滤。
- 数据库为单文件 SQLite（data/library.db），路径基于项目根绝对定位，不依赖工作目录。
- 开发方式：严格 RED→GREEN，每个改动先写失败测试，实现后跑全量测试。

## 2. 遗留的 Bug 与待办事项

### 已修复（本轮）

- 原先记录的四条小问题全部修掉：非数字 id、文章库空态无提示、标签前后端两份常量、文章库排序（真因是 RSS 日期原文按字符串排，不是 NULL）。
- 原先「应用未配置 logging」也已修复。

### 仍然存在

- 测试输出有一条第三方 httpx 弃用警告，非失败。

### 可选调整项

- 每日队列篇数（pick_today 的 limit，当前 5）。
- 订阅源清单与链接过滤规则。
- 复习卡片的字段展示。
- 新增标签只需改后端 `app/metadata.py` 的 `INTEREST_TAGS`，前端已改为从 `/api/tags` 读取。

## 3. 必须遵守的约束条件

- 模型通道只用本机 claude 命令行，不引入 API key；调用时工作目录设为空的临时目录。
- 所有模型输出必须按 JSON 解析；解析失败或项数不符重试一次，再失败标记该批失败且不影响阅读。
- 预分析结果绝不写入 occurrences；频次只来自用户确认的查询。划词缓存（lookups）只存展示用释义，同样不计频次。
- 中文标题与标签只存在数据库，不在前端现算；生成失败不阻塞阅读。
- 标签只能取自受控词表；非法标签丢弃、去重、最多 3 个。
- 数据库为单文件 SQLite，位置 data/library.db；无守护进程。
- 前端为原生 JS，无 npm、无构建步骤；界面文案中文，代码与注释英文。
- 开发方式：严格 RED→GREEN，每个改动先写失败测试，实现后跑全量测试。
- 破坏性操作（删 skill、删计划文件、改写历史、强推）执行前必须再次向用户确认。
- 提交身份已全局配置为 xhs / 128921592+1480482341@users.noreply.github.com。
- 网络：本机 HTTPS 推 GitHub 不通，统一走 SSH，且 ~/.ssh/config 已把 github.com 指向 ssh.github.com:443。

## 4. 提交与仓库信息

- 远端：origin → git@github.com:1480482341/reading-assistant.git（SSH）
- 分支：main，跟踪 origin/main，本地与远端一致
- 最新提交：d089568（修复元数据错位问题）
- 本次功能共 10 个提交（31495f6..d089568），已全部推送
- 提交信息依次为：设计文档与计划、数据库结构、元数据模块、启动任务接入、文章库接口、文章库页面路由、文章库前端、阅读页按 id 打开、README、错位修复
- 测试：全量 96 个通过
- 第二轮修复的改动目前只在工作区，尚未提交
- 分支已合并并删除，worktree 已清理（.claude/worktrees/article-library 不再存在）
- 被 git 忽略的内容：data/（阅读数据）、.superpowers/、.venv/、.claude/、各类缓存
- 常用命令：启动 uv run uvicorn app.main:app --port 8000；测试 uv run pytest；提交 git add -A 后 git commit 再 git push

## 5. 文件索引

- 设计文档：docs/superpowers/specs/2026-11-05-article-library-design.md
- 实施计划：docs/superpowers/plans/2026-11-05-article-library.md
- 原有设计文档：E:\AI_Project\plan\2026-11-05-reading-assistant-design.md（项目外）
- 后端：app/db.py（库与 schema、迁移）、app/sources.py（抓取与提取）、app/analyze.py（分块、模型调用、JSON 容错）、app/metadata.py（标签词表、中文标题与标签生成）、app/library.py（文章库查询）、app/lookup.py（划词归一化与缓存）、app/collect.py（手动入库与启动任务）、app/review.py（复习状态机）、app/export.py（导出）、app/main.py（路由与 lifespan）
- 前端：web/index.html、web/app.js、web/style.css、web/library.html、web/library.js、web/library.css、web/review.html、web/review.js、web/review.css
- 测试：tests/ 下按模块划分，新增 tests/test_metadata.py、tests/test_library_api.py；含 tests/test_collect.py、tests/test_e2e.py 与 tests/fixtures/
- 使用说明：README.md（启动、文章库、数据位置、换订阅源、导出、手动收集、健康检查）

## 6. 当前数据状态

- data/library.db：26 篇文章，全部状态为 ready（已完成预分析）
- 26 篇全部已有中文标题与标签（本次功能上线后已实际跑过生成任务）
- 词条 1 个，命中记录 2 条，复习记录 1 条
- 数据库已完成新 schema 迁移（含 title_zh 列与 article_tags 表）；`lookups` 表与 published_at 归一化迁移会在下次启动时自动应用（UI 实测用的是库的副本，原库未被改动）
