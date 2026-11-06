# 交接说明（英语阅读工作台）

- 日期：2026-11-06
- 项目根：E:\AI_Project\reading-assistant
- 分支：main（跟踪 origin/main）
- 测试：106 个全绿
- 服务：常用 `uv run uvicorn app.main:app --port 8000`，阅读页 http://127.0.0.1:8000
- 本文件是给新对话的唯一入口，读完即可接手；细节以代码为准

## 1. 已完成的核心逻辑与关键决策

### 1.1 阅读工作台

- 启动时后台线程抓 RSS（Quanta / JSTOR Daily / Aeon essays）→ trafilatura 提取正文 → 按 800 词分块调本机 claude 预分析 → 划词即得中文释义与语法拆解 → 确认的词条入库 → 三档间隔复习。
- 当天队列按 tech → history → humanities 轮换；顶栏「读完了」把文章移出队列并切到下一篇。
- 复习页：卡片模式（认识 / 不认识）+ 列表模式（全部词条与频次）。
- 手动收集：POST /api/articles/ingest 支持粘贴正文、给 URL、给本地 PDF。
- 导出：/api/export?format=md 与 format=csv；健康检查 /api/health。
- 关键决策：预分析结果与划词缓存都不计入频次，只有用户点「记下来」确认的词条才写 occurrences。
- 关键决策：词条按原形归并，释义按上下文存在每次命中上，避免一词多义互相覆盖。
- 复习间隔：今天 / 3 天 / 7 天；7 天档连续两次答对即毕业。
- 语法点独立成条，并登记进 grammar_terms 受控表；映射不上时新建，状态 pending 等人工收敛。
- 无守护进程：抓取、元数据、预分析都在启动时后台执行；中断后卡在 running 的预分析下次启动会重试。

### 1.2 文章库与标签

- /library 列出全部文章（含已读），按发布日期倒序；published_at 统一存 ISO 日期。
- 筛选：状态（全部 / 待分析 / 可读 / 已读）+ 16 个兴趣标签多选叠加（按「同时包含」），筛选在前端完成。
- 中文标题与标签由独立后台任务生成（每 8–10 篇一批），失败留空、下次启动重试；以 title_zh 是否为空作为「是否已处理」的标记。
- 标签走受控词表（16 个），每篇 1–3 个；非法标签丢弃、去重、最多 3 个；词表由 GET /api/tags 下发，前端不再维护第二份常量。
- 空态文案区分「文章库为空 / 加载失败 / 没有匹配」三种。
- 阅读页按 /?id=N 打开任意文章；非数字 id 前端先校验、后端详情路由用 int 转换器，均给「文章不存在」提示。
- 已知约束：/api/articles/library 必须注册在按 id 查详情的路由之前。

### 1.3 划词性能（第三轮重点，含实测数据）

- 模型通道只用本机 claude CLI；单次调用约 8.6 s，其中约 3.8 s 花在加载本机 MCP server 上 → 所有调用统一加 `--strict-mcp-config`，降到约 5.8 s。
- 划词的单次分析固定用 `--model haiku`（稳定 4.5–5.4 s；默认模型 6.3–18.5 s 波动大）；预分析仍用默认模型。
- 未命中的模型结果写入 lookups 表（article_id + 归一化文本），同一篇重复划同一个词毫秒返回；预分析重跑成功时清空该篇缓存。
- 匹配顺序：完全匹配 → 词形变化（复数 / 时态 / 副词）→ 单词落在 ≤6 词短语内（优先最短短语；选区至少 5 个字母才做模糊匹配）。
- 预分析密度：每 15 词 1 条 → 每 5 词 1 条；提示词要求「语境中含义不明显的常见词也要收」「同一词不重复」。
- 覆盖率：28 篇、15642 个长词实测 74%（中位 72%，最低 58%，最高 86%）；纯字符匹配时期约 17%。
- 端到端实测：预分析/缓存命中 1–2 ms，未命中 5.8–6.6 s，重复划词 1–2 ms。
- 两个交互缺陷已修：关闭弹框时清空选区（否则再划同一个词会被浏览器当成拖动已选文字，mouseup 不触发）；关闭时作废在途请求（否则模型结果回来会重新弹出）。

### 1.4 数据库与迁移

- 单文件 SQLite，位置 data/library.db，绝对路径，不依赖工作目录。
- 结构变更：articles.title_zh、article_tags、lookups、published_at 归一化（RSS 原文 → YYYY-MM-DD）。
- 迁移用 PRAGMA user_version 门控，只在旧库跑一次。
- 排序问题复盘：真因是 RSS 日期按字符串排序，不是 NULL（SQLite 的 DESC 本来就把 NULL 排在最后）。

## 2. 遗留的 Bug 与待办事项

- 仍然存在（非关键）：测试输出有一条第三方 httpx 弃用警告。
- 仍然存在：项目未安装 mypy / ruff（代码风格检查只能靠人工与测试）。
- 数据卫生：grammar_terms 已累积 7246 条，多轮预分析会不断新增近义标签；需要一次人工收敛或规则合并。
- 可选优化：继续加密预分析到每 4 词（预计覆盖率 +3 点左右，需再跑 30 分钟以上）。
- 可选优化：跨文章缓存（同一词在另一篇文章仍需首次调用模型）。
- 可选优化：未命中的 6.5 s 是 CLI 启动 + 模型延迟的下限，除非改用 API（约束禁止）。
- 可选优化：超长文章（1 万词）预分析单篇要 6.5 分钟，长文可以单独降密度。
- 已知行为：模型偶尔把选区理解成「截断词」，取决于选中边界，正常使用不影响。
- 临时工具：UI 实测脚本与重跑脚本都在 %TEMP%\ra-ui（不在仓库，可随时丢弃）。

## 3. 必须遵守的约束条件

- 模型调用只用本机 claude 命令行，不引入 API key；每次调用在空的临时目录执行，并带 `--strict-mcp-config`。
- 划词用 haiku，预分析用默认模型，两者不要随意互换（延迟与质量的平衡已验证）。
- 所有模型输出必须按 JSON 解析；解析失败或项数不符重试一次，再失败标记该批失败且不影响阅读。
- 预分析结果与 lookups 缓存绝不写入 occurrences；频次只来自用户确认的查询。
- 中文标题与标签只存在数据库，不在前端现算；生成失败不阻塞阅读。
- 标签只能取自受控词表；非法标签丢弃、去重、最多 3 个。
- 数据库为单文件 SQLite，位置 data/library.db；无守护进程。
- 前端为原生 JS，无 npm、无构建步骤；界面文案中文，代码与注释英文。
- 开发方式：严格 RED→GREEN，每个改动先写失败测试，实现后跑全量测试。
- 重跑预分析前必须先备份 data/library.db（现有 bak / bak2 / bak3 三份）。
- 破坏性操作（删 skill、删计划文件、改写历史、强推、删除备份）执行前必须再次向用户确认。
- 提交身份已全局配置为 xhs / 128921592+1480482341@users.noreply.github.com。
- 网络：本机 HTTPS 推 GitHub 不通，统一走 SSH（~/.ssh/config 已把 github.com 指向 ssh.github.com:443）。

## 4. 提交与仓库信息

- 远端：origin → git@github.com:1480482341/reading-assistant.git（SSH）
- 分支：main，跟踪 origin/main
- 已推送的历史：d089568（文章库错位修复）→ 9044c39 / fb12ffc / 32d67d4（第二轮：日期归一化、划词缓存与接口整理、文档）
- 本地尚未推送的提交：
  - e2b2bdf perf: cut lookup latency and widen pre-analysis coverage
  - 88265ab fix: keep lookup popup closed and clear stale selection
  - 随后一个文档提交（更新本文件与 README）
- 常用命令：启动 `uv run uvicorn app.main:app --port 8000`；测试 `uv run pytest`；提交 `git add ...` → `git commit` → `git push`
- 被 git 忽略：data/（含三份备份）、.superpowers/、.venv/、.claude/、各类缓存

## 5. 文件索引

- 后端：app/db.py（库与 schema、迁移）、app/sources.py（抓取与日期归一化）、app/analyze.py（分块、模型调用、提示词、JSON 容错）、app/metadata.py（标签词表、中文标题与标签生成）、app/library.py（文章库查询）、app/lookup.py（划词归一化、匹配与缓存）、app/collect.py（手动入库与启动任务）、app/review.py（复习状态机）、app/export.py（导出）、app/main.py（路由、lifespan、日志、Pydantic body）
- 前端：web/index.html、web/app.js、web/style.css、web/library.html、web/library.js、web/library.css、web/review.html、web/review.js、web/review.css
- 测试：tests/ 下按模块划分；本轮新增覆盖日期归一化、标签接口、非数字 id、空态、划词匹配（词形 / 短语 / 等长短语）、缓存；前端交互（关闭作废请求、选区清空）靠浏览器实测
- 文档：README.md（使用说明）、HANDOFF.md（本文件）

## 6. 当前数据状态

- data/library.db：28 篇文章，全部 ready；预分析条目共 14843（约 188 条/千词）；schema user_version = 1
- 用户数据：词条 1、命中记录 2、复习记录 1、文章标签 58 条
- lookups 表：8 条（本轮测试留下，可安全清空）
- 备份：data/library.db.bak-20261106（密度 15 原库）、bak2-20261106（密度 8）、bak3-20261106（密度 6）
