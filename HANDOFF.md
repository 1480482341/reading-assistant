# 交接说明（英语阅读工作台）

- 日期：2026-11-05
- 分支：feat/reading-assistant
- 项目根：E:\AI_Project\reading-assistant
- 状态：**10 / 12 任务完成，真实运行验证未通过，需要修一处预分析超时**

## 1. 已完成的核心逻辑与关键决策

- 设计文档已定稿并获批准：E:\AI_Project\plan\2026-11-05-reading-assistant-design.md
- 实施计划（12 个任务，含每步的失败测试与判据）：E:\AI_Project\reading-assistant\docs\superpowers\plans\2026-11-05-reading-assistant.md
- 已完成并提交的任务：1 骨架与数据库、2 词条归并与频次、3 RSS 采集与正文提取、4 预分析（分块/JSON 容错/术语映射）、5 划词查询与确认接口、6 每日队列与方向轮换、7 复习状态机、8 导出、9 阅读页前端、10 复习页前端
- 测试现状：37 个测试全绿（唯一噪音是第三方 httpx 弃用警告，非失败）
- 关键技术决策（均已落入代码与台账）
  - 预分析结果不计频次，只有用户主动确认的划词才写命中记录，否则频次排序失真
  - 词条按原形归并，释义按上下文存在每次命中上，避免一词多义互相覆盖
  - 复习用三档间隔（今天 / 3 天 / 7 天），7 天档连续两次答对即毕业
  - 语法点独立成条，通过受控术语表归并，避免"非限定从句"与"非谓语从句"被算成两条
  - 不设常驻进程：打开应用时抓取与预分析在后台进行，错过批次下次补抓
  - 订阅源按实测调整：Quanta、JSTOR Daily、Aeon（仅 essays 链接）为主源；Longreads 只提取到 194 词已移出；Hacker News 在本机连不上
- 实测数据（重要）
  - 单次小提示词调用约 12–13 秒
  - 两个调用并发互不拖累
  - **800 词一块 + "每 15 词一条" 的提示词：51 条，41.5 秒**
  - **2000 词一块要求 150–200 条：超过 120 秒超时，真实运行失败**

## 2. 遗留的 Bug 与待办事项

- **阻塞项**：预分析参数与当前实现不匹配。计划里写的"2000 词一块、每篇 150–200 条"会让单次调用超时；实测 800 词 + 按词数比例要条目可以在 42 秒内完成。下一步应改默认分块大小为 800 词、把提示词改成按词数比例产出、并把单次超时从 120 秒放宽到 300 秒，然后重跑真实文章验证
- 任务 11（端到端冒烟）进行中：集成测试已通过，但真实文章运行因上述超时未通过；README 尚未编写
- 任务 12（手动收集、启动抓取、健康检查、降级横幅）完全未开始
- 全分支的最终代码审查尚未进行
- 浏览器中的实际交互（划词浮层、右栏、复习卡片）尚未人工验证
- 旧方案尚未删除：english-immersion skill 与 12 周学习计划仍在原位，按约定需在新工具跑通并经确认后再删
- 两个小瑕疵：git 提交身份是用临时环境变量指定的（仓库未配置 user.name/email）；测试输出有一条第三方弃用警告

## 3. 必须遵守的约束条件

- 模型通道只用本机 claude 命令行，不引入 API key，调用时工作目录设为空的临时目录
- 所有模型输出必须按 JSON 解析，失败重试一次，再失败标记该块失败且不影响阅读
- 预分析结果绝不写入命中记录；频次只来自用户确认的查询
- 数据库为单文件 SQLite，位置 data/library.db；无守护进程
- 前端为原生 JS，无 npm、无构建步骤；界面文案中文，代码与注释英文
- 开发方式：严格 RED→GREEN，每个任务结束跑全量测试并提交；偏差必须写进台账
- 台账位置：E:\AI_Project\reading-assistant\.superpowers\sdd\2026-11-05-reading-assistant\progress.md（该目录被 git 忽略，不会随仓库走，新对话需要它请先确认存在）
- 破坏性操作（删 skill、删计划文件）执行前必须再次向用户确认

## 4. 环境与运行方式

- Python 3.11 + uv；依赖已装好，测试命令为 uv run pytest
- 本地启动命令为 uv run uvicorn app.main:app，默认端口 8000
- 真实文章已在 data/library.db 中留有一篇（id=1，Quanta，2312 词），其预分析状态为 failed，可复用重跑

## 5. 文件索引

- 设计文档：E:\AI_Project\plan\2026-11-05-reading-assistant-design.md
- 实施计划：E:\AI_Project\reading-assistant\docs\superpowers\plans\2026-11-05-reading-assistant.md
- 台账与各任务简报：E:\AI_Project\reading-assistant\.superpowers\sdd\2026-11-05-reading-assistant\
- 后端：app\db.py、app\sources.py、app\analyze.py、app\review.py、app\export.py、app\main.py
- 前端：web\index.html、web\app.js、web\style.css、web\review.html、web\review.js、web\review.css
- 测试：tests\（覆盖数据库、采集、预分析、接口、队列、复习、导出、页面、端到端）
- 测试夹具：tests\fixtures\sample.rss、tests\fixtures\sample_article.html
