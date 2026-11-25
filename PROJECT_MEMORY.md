# 《金匮要略》临床思辨训练系统 — 项目记忆文件

## 项目概述

构建基于大模型的《金匮要略》临床思辨训练智能体，帮助学生通过"病脉证并治"框架进行三阶梯多轮交互训练。
- 周期：2026年4月 — 2027年3月
- **当前完成度**：后端+前端可运行，**258 例训练病案**（原有 10 + 2026-11-24 从《金匮_病案题.xlsx》批量导入 248），生产库 762 条经典条文，279 个自动化测试（0 skip，全套约 5 秒）；P0 安全风险已处置（P0-10 的 HTTPS 待服务器配置）；公网实例已部署（YOUR_SERVER_IP，256 例病案）

---

## 技术架构

```
FastAPI (Python 3.11) + SQLite + 原生 HTML/CSS/JS
AI: OpenAI 兼容接口（当前配置为 DeepSeek 官方 api.deepseek.com / deepseek-chat）
```

三层结构：
- `app/routers/` — API 路由层
- `app/services/` — 业务逻辑层
- `app/models.py` + `database.py` — 数据层

---

## 文件结构

```
backend/
├── run.bat                    # 一键启动（双击）
├── seed_cases.py              # 9例结构化病例初始化脚本
├── seed_texts.py              # 条文批量导入脚本
├── requirements.txt           # Python 依赖
├── .env                       # AI API 密钥配置
├── app/
│   ├── main.py                # FastAPI 主入口，路由注册
│   ├── database.py            # SQLite 连接 + 会话管理
│   ├── dependencies.py        # 共享依赖（认证、限流）
│   ├── models.py              # 数据表定义
│   ├── schemas.py             # Pydantic 请求/响应模型
│   ├── routers/
│   │   ├── texts.py           # 条文 CRUD API
│   │   ├── cases.py           # 病案 CRUD API
│   │   ├── analysis.py        # AI 分析 API（旧版单次分析）
│   │   ├── documents.py       # 文档上传+解析 API
│   │   ├── agent.py           # 智能体训练 API（核心，6个端点）
│   │   ├── import_review.py   # 导入审核 API（10个端点）
│   │   └── feedback.py       # 用户反馈 API（4个端点）
│   ├── services/
│   │   ├── agent_service.py   # 智能体核心引擎（对话、进度、评价）
│   │   ├── scoring.py         # 结构化要点评分（按难度过滤 + 关键词对照）
│   │   ├── guidance.py        # 阶段引导提示（问诊→析证→定治→已完成）
│   │   ├── examination.py     # 诊法直出（号脉/看舌等返回客观体征）
│   │   ├── progress.py        # 阶段进度判定与关键词表
│   │   ├── prompts_config.py  # 可编辑的 AI 提示词配置文件
│   │   ├── matcher.py         # 条文-病案匹配算法
│   │   ├── parser.py          # PDF/Word/Excel/TXT 解析器
│   │   ├── session_token.py   # 会话归属令牌（HMAC）
│   │   └── import_validator.py # 导入质量闸门（398条号完整性校验）
│   └── utils/
├── static/
│   ├── index.html             # 教师管理端
│   ├── user.html              # 首页导航
│   ├── train.html             # 学生训练端（核心前端）
│   ├── study.html             # 条文学习页（按病证分类）
│   └── showcase.html          # Showcase 展示页（Awwwards 级设计）
├── tests/                     # 6 个测试文件 + conftest，257 用例
│   ├── conftest.py            # 公共夹具（临时 DATA_DIR、样本病案、agent）
│   ├── test_services.py       # 服务层纯函数 + 进度/评分/诊法
│   ├── test_api_agent.py      # 训练 API（会话、令牌、恢复）
│   ├── test_api_admin.py      # 管理端 CRUD 与分页
│   ├── test_api_misc.py       # 条文/文档/反馈等杂项
│   ├── test_security.py       # 认证、限流、XSS、路径穿越
│   └── test_parser.py         # 解析器回归（运行期生成 DOCX）
├── data/tcm.db                # SQLite 数据库（不入库，由 tools/backup_local.py 备份）
├── uploads/                   # 上传文档存储
├── .coveragerc                # 覆盖率配置
└── .github/workflows/test.yml # CI 工作流

tools/                         # 运维脚本（本地）
├── restart.ps1 / restart.cmd  # 干净重启（杀旧进程 + 等端口 + 校验代码新鲜度）
├── backup_local.py            # 本机每日备份
├── sync_server.py             # 从服务器拉取数据
└── README.md
```

---

## 数据库表

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `categories` | 分类表 | name, description |
| `classic_texts` | 经典条文（396条） | source_book, chapter, content, keywords, raw_content, source_file 等 |
| `medical_cases` | 训练病案（9例） | title, content, symptoms, diagnosis, prescription, difficulty_level, teaching_points, correct_answer, **examinations**（客观体征）, **key_facts**（问诊要点）, **scoring_points**（评分要点） |
| `text_case_relations` | 条文-病案关联 | text_id, case_id, similarity_score |
| `documents` | 上传文档 | filename, file_type, parsed_content, status, error_message |
| `learning_history` | 旧版学习记录 | user_query, analysis_result |
| `training_sessions` | 训练会话 | student_id, difficulty_level, case_id, status, decision_path, score, **examinations_done**（已做检查）, **evaluation**（评价原文）, **scoring**（要点得分明细） |
| `session_messages` | 会话消息 | session_id, role, content, message_type, key_decision |
| `import_batches` | 导入批次（2026-08新增） | source_file, source_book, total_count, status |
| `import_staging` | 导入暂存（2026-08新增） | batch_id, raw_content, parsed_number, review_status |
| `feedbacks` | 用户反馈（2026-08新增） | session_id, category, content, contact, status, admin_note |
| `chapter_meta` | 篇章元数据 | book, chapter, chapter_number, description |

---

## API 端点

### 智能体训练（核心）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/agent/session/start` | 开始训练（选难度，自动分配病案） |
| POST | `/api/agent/session/{id}/message` | 发送消息，获取 AI 回复 |
| GET | `/api/agent/session/{id}` | 获取会话完整记录 |
| POST | `/api/agent/session/{id}/evaluate` | 结束训练+生成评价+揭晓病案 |
| GET | `/api/agent/sessions` | 会话列表（教师端） |
| DELETE | `/api/agent/session/{id}` | 删除会话 |
| GET | `/api/agent/public-stats` | 公开聚合统计（条文/病案/训练次数/平均分） |

### 条文管理
- CRUD + 批量删除（`/api/texts/`）
- 篇章树 + 分布统计 + 互联网校验

### 其他
- 病案管理：CRUD + 批量删除（`/api/cases/`）
- AI 分析：单次条文分析（`/api/analysis/`）
- 文档管理：上传+解析（`/api/documents/`）
- 导入审核：批次列表、质检报告、逐条批准/驳回/编辑/删除、一键发布（`/api/import/`）
- 用户反馈：提交反馈（公开）+ 列表/更新/删除（管理端）（`/api/feedback/`）

---

## 智能体核心设计

### 三阶梯训练

| 等级 | 目标 | 教学重点 |
|------|------|---------|
| 初级 | 辨病 + 主证识别 | 从症状识别病证类型，建立方证对应 |
| 中级 | 平脉 + 析证 | 脉象辅助辨证，相似方证鉴别 |
| 高级 | 定治 + 整体决策 | 复杂病案、矛盾信息、传变坏病 |

### 教学策略：引导→追问→纠错→反思

- AI 扮演模拟患者+训练导师双重角色
- 不直接透露病名和方剂，引导学生自己推导
- 学生连续错误时给出提示，但**不强制结束**
- 学生主动点击评价才结束训练

### 防暴力破解

`agent_service.py` 中 `_detect_jailbreak()` 检测以下模式：
- "直接告诉答案"、"别废话"、"忽略之前指令"
- "假设你不是老师"、"从现在开始你是"
- 检测到后统一回复拒绝语

### AI 辅助进度判断

`_ai_check_progress()` 调用 LLM 判断学生是否完成辨病/平脉/析证/定治，与关键词匹配双重保障。

### 经典范围自适应

`_detect_classic_context()` 根据病案内容自动识别属于《金匮要略》还是《伤寒论》，避免 AI 硬扯不相关经典。

---

## 前端页面

| 路径 | 页面 | 功能 |
|------|------|------|
| `/` | 教师管理端 | 训练记录看板、病案编辑、文档上传、条文管理、导入审核 |
| `/user` | 首页 | 数据概览、条文学习入口、训练入口 |
| `/train` | 学生训练端 | 难度选择、聊天交互、进度追踪、评价+病案揭晓 |
| `/study` | 条文学习 | 8大病证分类、关联条文展示、AI解读 |
| `/showcase` | Showcase 展示 | Awwwards 级设计：Canvas 水墨粒子、弹簧动效、破格排版 |

---

## 部署信息

> **2026-10-21 状态更新**：原阿里云实例已到期下线，公网无访问地址，系统当前仅在本地运行。
> 以下信息保留为历史部署记录，重新部署时需重新确认。

- **服务器**：阿里云轻量服务器，Ubuntu 22.04（已下线）
- **公网 IP**：`YOUR_SERVER_IP`（已不可访问）
- **端口**：80 → iptables 转发到 8000（安全组已开放80、8000）
- **systemd 服务**：`/etc/systemd/system/jingui.service`（开机自启）
- **部署方式**：服务器已安装 Git，`cd /root/JinGui && sudo git pull && sudo systemctl restart jingui`
- **一键部署脚本**：`server_deploy.sh`（优先 git pull，失败降级 wget）
- **生产数据库**：`/var/lib/jingui/tcm.db`（仓库外持久化，部署前自动备份到 `/var/backups/jingui/`）
- **Python 命令**：服务器用 `python3`，不是 `python`

## 关键配置

`.env` 文件（本地）：
```
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=请在服务器环境中配置
AI_MODEL=deepseek-chat
ADMIN_PASSWORD=请在服务器环境中配置
```

服务器 systemd 环境变量同上。

---

## 改进清单

> 创建日期：2026-07-25
> 目的：记录从专业软件工程角度识别的改进项，逐条跟踪推进状态。

### 改进优先级说明

| 级别 | 含义 | 建议时间 |
|------|------|---------|
| **P0** | 安全/稳定性风险，必须尽快修复 | 本周 |
| **P1** | 影响可维护性和可观测性，强烈建议 | 本月 |
| **P2** | 工程化提升，显著改善开发体验 | 本季度 |
| **P3** | 锦上添花，提升产品质量 | 有时间就做 |

### P0-1. API 路由缺少认证保护

- **问题**：当前只有 `/`（管理端首页）有 HTTP Basic Auth。`/api/texts/`、`/api/cases/`、`/api/documents/` 等 CRUD 端点全部公开，任何知道 IP 的人都能增删改条文和病案。
- **影响**：数据可被恶意篡改或删除，训练会话记录也可被清空。
- **位置**：`app/main.py:54-63`（仅保护了 `/` 路由），`app/routers/` 下所有路由
- **建议方案**：给所有 `/api/texts/`、`/api/cases/`、`/api/documents/`、`/api/agent/sessions` 等写操作路由添加认证依赖；或使用 FastAPI 中间件统一拦截 `/api/` 下非 GET 请求。
- **状态**：✅ 已完成（2026-07-25）
- **实现**：创建 `app/dependencies.py` 共享 `verify_admin`；所有写操作端点（POST/PUT/DELETE）添加 `_admin: str = Depends(verify_admin)`；覆盖 texts/cases/documents/analysis/agent 五个路由模块共 13 个端点。后续（2026-07-31）分离了页面认证与 API 认证，避免公开页面触发浏览器密码弹窗。
- **⚠️ 2026-10-21 审计更正**：本条只覆盖了**写**操作。读接口仍在泄漏答案——`GET /api/cases/` 未认证返回 `correct_answer`/`teaching_points`，`/api/agent/session/{id}/evaluate` 无归属校验且返回 `case_correct_answer`。详见 P0-5、P0-7。

### P0-2. 无请求频率限制（Rate Limiting）

- **问题**：AI 训练端点 `/api/agent/session/{id}/message` 每次调用都消耗 DeepSeek API 费用。目前无任何频率控制，单个用户可在短时间内发起大量请求耗尽 API 额度。
- **影响**：经济成本不可控，恶意用户可刷爆 API Key。
- **位置**：`app/routers/agent.py` 所有端点
- **建议方案**：自实现 `SimpleRateLimiter`（基于内存滑动窗口），对 agent-message 限制 30次/分，agent-start/evaluate 限制 10次/分，analysis-query 限制 10次/分，documents-upload 限制 5次/时。
- **状态**：✅ 已完成（2026-07-25）
- **实现**：`app/dependencies.py` 新增 `SimpleRateLimiter` 类和预置限流函数（`limit_agent_message`、`limit_agent_start`、`limit_upload`、`limit_analysis`）；所有受保护端点通过 `Depends()` 注入限流检查。避免了 `slowapi` 在 Windows 上的 GBK 编码兼容问题。

### P0-3. 文件上传无大小限制

- **问题**：`/api/documents/upload` 未限制上传文件大小，攻击者可上传超大文件耗尽磁盘。
- **影响**：DoS 风险，服务器磁盘满导致服务不可用。
- **位置**：`app/routers/documents.py:199-257`
- **建议方案**：分级限制：≤20MB 直接上传，20MB~200MB 需在请求头 `X-Upload-Password` 中附加管理员密码，>200MB 硬拒绝。流式读取时二次校验防止 Content-Length 伪造。
- **状态**：✅ 已完成（2026-07-25）
- **实现**：`app/routers/documents.py` 新增 `MAX_UPLOAD_NORMAL=20MB` / `MAX_UPLOAD_HARD=200MB` 常量；上传端点增加 Content-Length 预检 + 分块写入时大小追踪 + 分级密码验证；超限时返回 413 状态码。

### P0-4. 部署覆盖生产数据库

- **问题**：生产 SQLite 数据库位于 Git 工作树内，且部署脚本执行 `git reset --hard origin/main`，在线训练记录会被仓库中的旧数据库快照覆盖。
- **影响**：每次部署都可能永久丢失训练会话、消息和学习记录。
- **位置**：`server_deploy.sh`、`deploy.sh`、`jingui.service`、`backend/data/tcm.db`
- **解决方案**：生产数据库迁移到仓库外的 `/var/lib/jingui/tcm.db`；首次迁移短暂停止服务以避免写入竞态；systemd 固定设置 `DATA_DIR`；部署前通过 SQLite Online Backup API 备份；部署后比较会话、消息、学习记录、病案和条文数量，发现减少立即报错。
- **状态**：✅ 已完成（2026-07-30）
- **实现**：安全部署脚本首次运行自动迁移旧库，后续部署只操作持久化库；备份保存在 `/var/backups/jingui/`；本地部署入口统一调用服务器安全部署脚本。

---

### P1-1. 结构化日志 & 请求追踪

- **问题**：全项目使用 `print()` 输出调试信息，无日志级别、时间戳、请求上下文。线上问题排查全靠 `journalctl` 看 print 输出。
- **影响**：故障定位效率低，无法关联请求链路。
- **位置**：全局
- **建议方案**：接入 Python `logging` 模块，配置 JSON 格式输出；使用 `starlette-context` 或自定义中间件注入 `X-Request-ID`；AI 调用记录请求耗时和 token 用量。
- **状态**：✅ 已完成（2026-10-21 更正：`app/logger.py` 已实现结构化日志 + `ContextVar` request_id，`main.py` 中间件注入 `X-Request-ID` 并回写响应头，全项目已改用 `get_logger`）
- **遗留**：AI 调用的耗时/token 用量尚未记录；`text_verifier.py` 漏了 logger 定义（见 P1-7）。

### P1-2. 添加健康检查端点

- **问题**：无 `/health` 端点，部署后无法自动化验证服务是否正常、数据库是否可连接、AI 客户端是否就绪。
- **影响**：负载均衡器/监控系统无法自动摘除故障节点。
- **位置**：`app/main.py`
- **建议方案**：添加 `GET /health` 返回 `{"status":"ok","db":"connected","ai":"ready"}`，返回 200 或 503。
- **状态**：✅ 已完成（2026-11-13 更正）：端点早已存在，且 2026-10-21 的 P0-6 已修掉 `return {...}, status`
  的问题——现在 `/live`（存活）、`/ready`（就绪，DB 异常返回 503）、`/health`（兼容别名）三者齐备，
  状态码与响应体都正确。本条此前一直挂着「部分完成」，属于状态未同步

### P1-3. Router 层测试覆盖（当前 ~0% 覆盖）

- **问题**：`texts.py`（15%）、`cases.py`（35%）、`documents.py`（19%）、`analysis.py`（15%）四个路由模块基本没有测试。任何 CRUD 改动都无回归保护。
- **影响**：重构或新增功能时容易引入 bug，且需要手动验证。
- **位置**：`backend/tests/`（缺少 `test_texts.py`、`test_cases.py` 等）
- **建议方案**：参考 `test_api_routes.py` 的 `dependency_overrides` 模式，为 CRUD 路由补充集成测试。
- **状态**：✅ 已完成（2026-10-21 更正：`test_texts.py`、`test_cases.py`、`test_documents.py` 均已存在，路由层已有集成测试）

### P1-4. agent_service.py 拆分解耦

- **问题**：`TrainingAgent` 类 580 行，承载了越狱检测、LLM 调用、进度分析、西医数据生成、评价生成、会话管理、条文匹配等全部职责。违反单一职责原则。
- **影响**：修改任一功能需通读全类，测试也只能间接测。
- **位置**：`app/services/agent_service.py`
- **建议方案**：拆分为：
  - `services/agent.py` — 会话编排（`create_session`、`process_message`、`evaluate_session`）
  - `services/llm_client.py` — LLM 调用封装（`_call_llm`、`_fallback_response`、模型 fallback）
  - `services/safety.py` — 越狱检测 + 玩笑请求处理（`_detect_hard_jailbreak` 等）
  - `services/progress.py` — 进度分析与判断（`_analyze_progress`、`_ai_check_progress`）
  - `services/western_data.py` — 西医检查数据生成（`_generate_western_test_context`）
- **状态**：🟠 部分完成（2026-10-21 更正：`safety.py`、`progress.py`、`western_data.py`、`treatment_safety.py` 已拆出；`agent_service.py` 仍约 660 行，会话编排、LLM 调用、提示词拼装、评价逻辑仍在类内）

### P1-5. `get_agent()` 全局单例问题

- **问题**：`get_agent()` 使用模块级 `_agent_instance` 全局变量，导致：
  - 多用户并发共享同一 agent 状态
  - 测试时必须 mock 整个 `get_agent` 函数才能隔离
  - 无法按请求配置不同的 agent 参数
- **影响**：潜在的并发状态污染，测试复杂度上升。
- **位置**：`app/services/agent_service.py:573-579`
- **建议方案**：改为 FastAPI 依赖注入模式——用 `Depends(get_agent)` 创建请求级实例，或使用 `contextvars` 实现请求作用域单例。
- **状态**：✅ 已完成（2026-10-21 更正：`get_agent()` 已改为每次返回新的 `TrainingAgent()`，路由经 `Depends(get_agent)` 注入）

### P1-6. 文档上传失败可诊断与可重试

- **问题**：后台解析异常仅标记为 `failed`，没有持久化错误原因，无法从管理端排查。
- **影响**：文档上传失败后教师无法知道原因，也无法重试。
- **位置**：`app/routers/documents.py`、`static/index.html`
- **状态**：✅ 已完成（2026-08-03）
- **实现**：`documents.error_message` 通过启动时轻量迁移补齐；后台任务失败时保存异常摘要和处理时间；管理端在失败文档旁显示错误详情并提供"重试"按钮；重试只允许失败记录、要求管理员认证、确认原始文件存在，不删除既有条文或重新上传文件。

---

### P2-1. 数据库迁移（Alembic）

- **问题**：表结构变更是通过直接修改 `models.py` + 重建数据库进行。生产环境无法安全演进 schema。
- **影响**：未来新增字段或表时，要么丢失数据重建，要么手动写 SQL。
- **位置**：`app/models.py`、`app/database.py`
- **建议方案**：接入 Alembic，`alembic init` → 配置 `alembic.ini` → 生成 migration 脚本。
- **状态**：✅ 已完成（2026-10-21 更正：`alembic/` 已就位，`database.init_db()` 调用 `command.upgrade(cfg, "head")`；含 `bb356c8cc735` 建表与 `d32e4c7f91ab` 遗留库补列两个 revision）

### P2-2. 前端工程化

- **问题**：4 个 HTML 文件各有 500-800 行内联 CSS/JS。无组件复用（顶栏导航每个文件复制一遍），无构建工具，无代码分割。
- **影响**：维护成本随页面增加线性增长，样式一致性问题频发。
- **位置**：`backend/static/*.html`
- **建议方案**：
  - 短期：提取公共 CSS/JS 到独立文件，HTML 引用
  - 长期：考虑 Vue.js / React 或轻量方案（Alpine.js + Tailwind CSS），Vite 构建
- **状态**：🟠 部分完成（2026-10-21 更正：已抽出共享 `jingui-theme.css`（40 KB）与 `jingui-motion.js`；各页 HTML 仍为内联 CSS/JS 单体）

### P2-3. API 分页元数据

- **问题**：所有列表接口只返回数据数组，不返回 `total`、`page`、`page_size` 等元数据。前端无法实现真正的分页器。
- **影响**：条文 396 条、训练记录增长后，前端无法知道总数和当前页。
- **位置**：`app/routers/texts.py`、`cases.py`、`agent.py`（`/sessions`）、`documents.py`
- **建议方案**：定义通用 `PaginatedResponse[T]` 泛型 schema，包含 `items`、`total`、`skip`、`limit`。
- **状态**：✅ 已完成（2026-11-07，改用响应头方案）：新增 `app/pagination.py`，7 个列表端点通过 `X-Total-Count`/`X-Skip`/`X-Limit` 返回分页元数据，响应体保持数组以兼容既有调用；管理端三张主表加入翻页控件，并补齐 `difficulty_level` 筛选、`sort_order` 排序与 `/api/agent/session-summary` 汇总

### P2-4. Docker 容器化

- **问题**：当前部署依赖服务器手动配置 Python 3.11 环境、systemd 服务。新服务器部署需要参照部署指南手动操作。
- **影响**：部署门槛高，不可重复构建。
- **位置**：项目根目录
- **建议方案**：编写 `Dockerfile` + `docker-compose.yml`（可选），使用 `python:3.11-slim` 基础镜像。
- **状态**：🟠 待处理

### P2-5. 废弃 API 迁移

- **问题**：`declarative_base()`（来自 `sqlalchemy.ext.declarative`）在 SQLAlchemy 2.0 已标记废弃；`@app.on_event("startup")` 在 FastAPI 已标记废弃（推荐 `lifespan` 上下文管理器）。
- **影响**：未来升级依赖时可能报错。
- **位置**：`app/database.py:31`、`app/main.py:100`
- **建议方案**：`declarative_base` → `sqlalchemy.orm.declarative_base`；`on_event` → `lifespan` async context manager。
- **状态**：🟠 待处理

### P2-6. 条文导入系统重构

- **问题**：原 `parser.py` 以"第X条"为边界，无法处理句末条号 `（9）` 格式和中文数字 `（一）` 格式，且罗马数字 `ⅠⅡⅢ` 被当作正文。
- **影响**：无法正确解析《金匮要略》格式的条文文档。
- **位置**：`app/services/parser.py`
- **状态**：✅ 已完成（2026-08-03）
- **实现**：parser.py 全新切分算法（句末条号收束 + 缓冲区累积 + 同号合并 + 中文数字支持 + 罗马数字清除）；新增 raw_content/content 双字段 + 7个溯源字段；质量闸门（398条号完整性校验）；暂存→审核→发布流程（ImportBatch/ImportStaging + 10个审核API）；管理端导入审核面板。

---

### P3-1. 数据库备份策略

- **问题**：SQLite 是单一文件 `data/tcm.db`，无自动备份。服务器故障或误操作可能丢失所有训练记录和病案数据。
- **影响**：数据丢失风险。
- **位置**：运维层面
- **建议方案**：每日 cron 任务 `cp data/tcm.db data/backups/tcm-$(date +%Y%m%d).db`，保留最近 7 天。
- **状态**：✅ 已完成（2026-11-06）
- **实现**：`tools/backup_local.py` 负责本机每日备份（SQLite Online Backup API + `integrity_check`，保留 90 份，产物 `backups/local/`）；`tools/sync_server.py` 从生产服务器拉取（recent 14 / daily 180 天，产物 `backups/server/`）；`tools/db_tool.py` 提供校验与恢复；部署前备份仍由 `server_deploy.sh` 负责。定时任务用 `schtasks` 注册，完整用法与恢复步骤见 `tools/README.md`。

### P3-2. 前端加载状态 & 错误边界

- **问题**：训练端发送消息后无明确加载指示器（仅按钮禁用），AI 调用超时时用户看到空白无反馈；JS 错误会导致整个页面白屏。
- **影响**：用户体验差，尤其是 AI 响应慢时。
- **位置**：`backend/static/train.html`
- **建议方案**：添加骨架屏/打字动画；`window.onerror` 全局错误处理；超时提示"AI 响应较慢，请稍候"。
- **状态**：🟠 部分完成（2026-10-21 更正：`train.html` 已有 `showLoading()` 打字动画与按钮禁用；仍缺 `window.onerror` 与超时提示）

### P3-3. 数据导出功能

- **问题**：教师端无导出训练记录、条文、病案的功能。教师需要手动复制或读数据库。
- **影响**：教学数据分析、汇报材料准备不便。
- **位置**：`app/routers/agent.py`、`texts.py`、`cases.py`
- **建议方案**：添加 `GET /api/agent/sessions/export?format=csv` 端点，支持 CSV 导出。
- **状态**：🟢 待处理

### P3-4. CHANGELOG & 版本管理

- **问题**：无版本号和变更日志，无法追踪每个版本的改动内容。
- **影响**：部署后不知道改了哪些功能。
- **位置**：项目根目录
- **建议方案**：添加 `CHANGELOG.md`，每次发布记录版本号 + 变更摘要。
- **状态**：✅ 已完成（2026-10-21）：新增 `CHANGELOG.md`（记录 1.0.0 与 1.1.0），FastAPI `version` 同步为 `1.1.0`，发布以 annotated tag `v1.1.0` 标记

### P3-5. Code Linting & Formatting

- **问题**：无代码风格约束。`agent_service.py` 存在不一致的缩进（有的用 `;` 在同一行写多条语句如 `db.add(session); db.commit()`）。无 flake8/ruff 配置。
- **影响**：代码风格不一致，review 成本高。
- **位置**：全局
- **建议方案**：添加 `ruff` 或 `black` + `isort` 配置，加入 CI 流程。
- **状态**：🟢 待处理

### P3-6. Showcase 展示页

- **问题**：项目缺乏展示型页面体现设计品质和现代 Web 交互能力。
- **位置**：`backend/static/`（新增 showcase.html）、`app/main.py`（新增路由）
- **状态**：✅ 已完成（2026-07-31）
- **实现**：Canvas 水墨粒子背景、弹簧物理文字动效、破格实验性排版、磁性光标交互、全站 Lucide 图标、实时数据接入（`/api/agent/public-stats`）

---

### 2026-10-21 审计新增项

> 来源：2026-10-21 全项目审计（见工作日志）。状态标记：🔴 未修复 / 🟡 待处理 / 🟠 部分完成 / ✅ 已完成。
> 纪律：1.0.0 基线已冻结于 tag `v1.0.0`，以下修复须遵守"不改软件名称与版本号、不删除 git 历史"。

#### P0-5. 病案读接口未认证即返回标准答案

- **问题**：`GET /api/cases/`、`GET /api/cases/{id}` 无认证依赖，而 `MedicalCaseResponse` 含 `correct_answer`、`teaching_points`、`diagnosis`、`prescription`。实测未带凭据即返回答案原文。
- **影响**：训练系统唯一的约束（学生看不到答案）可被一条 `curl` 绕过，产品逻辑失效。
- **位置**：`app/routers/cases.py:30-48`、`:66-75`、`app/schemas.py:100-106`
- **方案**：新增 `MedicalCasePublicResponse`（仅症状/内容/难度/标题），公开列表与详情改用它；管理端读取走新增的 `/api/cases/admin/`（`Depends(verify_admin)`）；`static/index.html` 改调该端点。
- **状态**：✅ 已完成（2026-10-21）：公开 `GET /`、`GET /{id}` 已改用 `MedicalCasePublicResponse`，新增 `GET /admin/`、`GET /admin/{id}`；`index.html` 病案管理改调 admin 端点；回归测试 `test_security_fixes.py::TestCaseAnswerExposure`（断言 4 个答案字段均不下发）

#### P0-6. `/health` 返回码恒为 200，响应体被编码成数组

- **问题**：`return {...}, http_status` 不被 FastAPI 支持，实测 `GET /health` → `200` + `[{"status":"ok","db":"connected","ai":"not_configured"},200]`。
- **影响**：部署脚本与外部监控永远认为服务健康；`server_deploy.sh` 的部署验收形同虚设。
- **位置**：`app/main.py:99-137`、`server_deploy.sh:235-253`
- **方案**：改用 `JSONResponse(status_code=..., content=...)`；拆分为 `/live`（进程存活，恒 200）与 `/ready`（DB + AI，异常 503）；部署脚本改查 `/ready`。
- **状态**：✅ 已完成（2026-10-21）：新增 `/live`（恒 200）、`/ready`（DB 异常 503），`/health` 保留为兼容别名，状态码改由 `JSONResponse` 指定；回归测试 `test_security_fixes.py::TestHealthProbes`（含 DB 故障返回 503、返回体必须是对象）。`server_deploy.sh` 仍查 `/health`（现可正确失败），待第二批改为 `/ready`

#### P0-7. 评价接口无归属校验，且泄漏参考答案

- **问题**：`POST /api/agent/session/{id}/evaluate` 既无管理员认证、也不校验 `session.student_id` 归属，响应含 `case_correct_answer`。`session_id` 为自增整数。
- **影响**：枚举 id 可批量获取全部病案答案，并可给他人会话写入 `score`、污染教学数据。
- **位置**：`app/routers/agent.py:146-198`
- **方案**：创建会话时签发不可猜测的 `session_token`，`message` / `evaluate` 校验 token 归属；答案揭晓改为一次性 `reveal_token`；如需教师端跨会话评价，走带 `verify_admin` 的独立端点。
- **状态**：✅ 已完成（2026-10-21，实现方式与原方案不同）：新增 `services/session_token.py`，用 `HMAC-SHA256(session_id, SESSION_SECRET|ADMIN_PASSWORD)` 派生令牌，**不落库、无需 Alembic 迁移**；`session_token` 随 `start_session` 下发，`/message` 与 `/evaluate` 校验 `X-Session-Token`（缺失/错误 → 403），`GET /session/{id}` 改为 `verify_admin`；`train.html` 已保存并回传令牌；回归测试 `TestSessionOwnership`

#### P0-8. 上传文件名未净化，可路径穿越

- **问题**：`safe_filename = f"{timestamp}_{file.filename}"` 直接用客户端提供的 `file.filename` 拼 `os.path.join`，未取 basename、未校验扩展名。
- **影响**：`filename="../../x.txt"` 或绝对路径可写出上传目录（需管理员凭据，但可与 XSS 叠加升级为任意写）。
- **位置**：`app/routers/documents.py:231-234`
- **方案**：`Path(filename).name` + 扩展名白名单 + UUID 前缀；原始文件名仅用于展示与 `Document.filename` 字段。
- **状态**：✅ 已完成（2026-10-21）：落盘名改为 `时间戳_UUID8.扩展名`，原始名只作展示；新增 `ALLOWED_EXTENSIONS` 白名单，非白名单扩展名直接 400；回归测试 `TestUploadPathTraversal`（含 `../../evil.txt` 与 `.sh` 两个用例）

#### P0-9. 管理端存储型 XSS（学生输入 → 教师后台执行）

- **问题**：`static/index.html` 会话详情 `dInfo.innerHTML` / `dChat.innerHTML` 直接拼接 `student_id`、`case_title`、`m.content`；训练记录表拼接 `r.student_id`。文件内已有 `escHtml()` 但未用于这些位置。
- **影响**：学生在对话中提交 `<img src=x onerror=...>`，教师打开会话详情即在 Basic Auth 上下文执行脚本，可读删全部数据。
- **位置**：`static/index.html:356-365`、`:377-381`
- **方案**：改用文本节点或 `escHtml()`；导出/渲染类拼接统一走同一转义函数。
- **状态**：✅ 已完成（2026-10-21）：训练记录表与会话详情改为"白名单校验 + `escHtml` + `textContent`"，反馈面板补转义 `category`，`FeedbackCreate.category` 改为 `Literal` 枚举收口（避免任意字符串入库再被渲染）；回归测试 `TestFeedbackValidation`

#### P0-10. 网络与凭据基线

- **问题**：`CORSMiddleware(allow_origins=["*"], allow_credentials=True)`；`/docs`、`/redoc` 公开；`ADMIN_PASSWORD` 缺省回落成 `jingui2026`；生产以明文 HTTP 提供 Basic Auth。
- **影响**：管理凭据随每个请求在网络明文传输；默认口令可被直接试探。
- **位置**：`app/main.py:48-54`、`app/main.py:36-37`、`app/dependencies.py:21`
- **方案**：CORS 收敛到实际域名；生产关闭或认证保护 `/docs`；`ADMIN_PASSWORD` 未设置时启动即失败；前置 Nginx + HTTPS。
- **状态**：🟠 部分完成（2026-10-21）：已取消内置默认口令（未配置 `ADMIN_PASSWORD` 时任何密码都不通过）、CORS 改为默认不放行任何来源并可按 `CORS_ORIGINS` 显式配置、`DISABLE_DOCS=1` 可关闭交互式文档；**HTTPS 与 Nginx 反向代理属服务器侧配置，仍未落地**

#### P1-7. `text_verifier.py` 未定义 `logger`

- **问题**：第 159 行使用 `logger.warning`，但全文件无 `logger = get_logger(__name__)`（实测模块内不存在该名字）。
- **影响**：LLM 调用失败时本应降级为"校验失败"，实际抛 `NameError` 变 500，且丢失原异常。
- **位置**：`app/services/text_verifier.py:159`
- **方案**：补 logger；同时把 `expected_section`、`fixed` 补进 `TextVerifyResponse`（当前被 response_model 静默丢弃）。
- **状态**：✅ 已完成（2026-10-21）：补 `logger = get_logger(__name__)`，两个字段已进 `TextVerifyResponse`；回归测试 `TestVerifierLogging`（模拟 LLM 失败时降级返回 `{}` 而非抛 `NameError`）

#### P1-8. 解析器 golden 回归测试长期空转

- **问题**：`test_parser_regression.py` 的 16 个用例依赖 `backend/uploads/20260801_165919_伤寒论原文398条整理.docx`，而 `backend/uploads/*` 被 `.gitignore` 排除（目录内仅有测试残留 `test.txt`）。
- **影响**：全项目最复杂、最易回归、直接决定数据正确性的解析器，唯一有 golden sample 的测试在本地与 CI 均 skip；"176 passed" 存在虚高。
- **位置**：`backend/tests/test_parser_regression.py:17-25`
- **方案**：把该 DOCX（或裁剪后的小样本 + 纯文本 golden）放入 `backend/tests/fixtures/`，并让 `.gitignore` 例外放行。
- **状态**：✅ 已完成（2026-10-21，实现方式更彻底）：`test_parser.py` 在运行期用 python-docx **即时生成**样本（章标题切换、行首罗马数字、中文数字条号、异体字、重复条号），不再需要任何外部二进制文件；原 16 个 skip 归零，并补了 source_book 推断与短文档回退用例

#### P1-9. 测试环境未隔离，污染工作区

- **问题**：`test_analysis.py` 在有 Key 时真实调用 LLM；`backend/uploads/` 累积 17 个 `*_test.txt` 无清理；`backend/data/tcm.db` 被 git 跟踪，跑测试后出现 `M`；`.codex_tmp/`、`output/` 未纳入 `.gitignore`（合计 65 MB 未追踪）。
- **影响**：测试慢（417s）且结果依赖外部服务；`git status` 长期带噪音，易误提交运行时数据。
- **位置**：`backend/tests/*`、`backend/.gitignore`（仓库根 `.gitignore`）
- **方案**：测试统一 `monkeypatch` AI 服务返回桩；`DATA_DIR` 指向 `tmp_path`；上传目录用临时目录；`backend/data/tcm.db` 移出版本控制并由 `seed_*.py` 首次生成；补 `.gitignore` 条目。
- **状态**：✅ 已完成（2026-11-06）：`conftest.py` 把 `DATA_DIR` 指向进程级临时目录（数据库与上传目录都不再落在仓库）、启动期迁移与上传后台解析打桩、AI 环境变量默认置空、`.gitignore` 补 `.codex_tmp/`/`output/`/`*.log`；`backend/data/tcm.db` 已 `git rm --cached` 移出版本控制，本地数据保留，备份交由 `tools/backup_local.py`

#### P2-7. 无学员身份与会话恢复

- **问题**：`student_id` 由前端生成 `'student_' + Date.now()`，每次训练都是新身份；`sessionId` 仅存内存（`train.html:303`），刷新即断。
- **影响**：教师无法按学生/班级归档训练与评分；学生误刷新丢失整轮训练。
- **位置**：`static/train.html:303`、`:324`、`app/routers/agent.py`
- **方案**：学号/昵称存 localStorage + 服务端 `session_token`；会话 id 落 localStorage 支持恢复。
- **状态**：✅ 已完成（2026-11-07）：训练页新增学号输入并记忆；会话 id + 令牌 + 难度存入 localStorage，刷新后校验 `/session/{id}` 并可一键恢复历史消息；`GET /session/{id}` 放行令牌持有者；`student_id` 增加长度校验；无数据库迁移

#### P2-8. 阶段进度判定可被关键词刷分

- **问题**：`_analyze_progress` 的 `disease_hit` / `pulse_hit` 对 `history[-10:]` 的**全部文本（含 AI 患者消息）**做子串匹配。
- **影响**：学生一句"太阳病，脉浮"即可同时点亮中级/高级的辨病与平脉；AI 患者若意外提到病名也会误判。
- **位置**：`app/services/agent_service.py:448-455`
- **方案**：仅统计 `role == "user"` 的消息；要求关键词出现在判断性语境中，或改为"规则兜底 + 一次 LLM 复核"双判。
- **状态**：✅ 已完成（2026-11-13）：分两层处理，见工作日志「进度判定加固」。
  1. `progress.statement_text()` 剔除问句与否定句——「是不是少阳病？」「不像少阳」不再点亮阶段；
  2. 规则点亮「辨病 / 析证」后，让模型确认一次「是判断还是提问/否定」；只做否决，
     判不了就采信规则（fail-open），一场会话最多两次调用。
  已实机验证（2026-11-13）：问句与纯否定不点亮，陈述点亮，且复核结果写入 `verified_stages`

#### P2-9. 配置与常量重复

- **问题**：读取 `.env` 的"load_dotenv + 手工解析写 os.environ"在 `analysis.py` 出现 3 次，`main.py`、`ai_service.py`、`agent_service.py` 各 1 次；病证/方剂关键词表在 `_detect_classic_context`、`_analyze_progress`、`progress.extract_decision_point` 三处重复维护。
- **影响**：改一处漏两处；运行期写 `os.environ` 有副作用、难以测试。
- **位置**：`app/routers/analysis.py:17-96`、`app/services/agent_service.py:117-137`、`app/services/progress.py:22-35`
- **方案**：抽 `app/config.py`（pydantic-settings）统一加载；病证/方剂表收敛为单一常量模块。
- **状态**：🟠 部分完成（2026-10-21）：`analysis.py` 中 4 处 `load_dotenv(override=True)` 与手工 `.env` 解析已全部删除（它们会在请求期把密钥写回 `os.environ`），配置改为启动时一次加载；**`config.py` 统一入口与关键词表收敛仍未做**

#### P2-10. 备选模型在 MaaS 平台下无效

- **问题**：`AI_FALLBACK_MODELS` 未配置（空值）时，`ai_service._openai_compatible_analyze` 会回退到
  `["deepseek-v3", "deepseek-v2", "deepseek-chat"]`；当前平台（自建 MaaS）只有 `example-model` 等模型，
  主模型一旦失败就会依次用不存在的模型名重试。
- **影响**：故障时每条请求额外多打 3 次无效调用（单次约 40s 量级），响应显著变慢；最终错误信息指向"模型不存在"，
  掩盖真正原因（网络、配额、限流）。
- **位置**：`app/services/ai_service.py:216-223`
- **方案**：空值时 `fallbacks = []`（只试主模型），显式配置才启用回退；或按 `OPENAI_BASE_URL` 的平台前缀推断候选模型。
- **状态**：✅ 已完成（2026-11-06）：已移除内置的 DeepSeek 默认回退，只尝试 `AI_FALLBACK_MODELS` 中显式列出的模型；`.env` 现设为 `deepseek-chat`（MaaS 平台暂只开放 `example-model`，故当前不会触发）

#### P3-7. 评分全靠模型自由发挥，且不区分难度

- **问题**：`evaluate_session` 只做一次 LLM 调用，由模型直接给出「辨病准确度 / 平脉分析度 / … / 综合评分」。
  评分要点存在于教师脑中和 `correct_answer` 的自由文本里，代码没有可对照的清单。
- **影响**：
  1. **不可复现**：同一份病案、同一段对话，两次评价能差几十分（模型温度 + 每次重新理解标准）；
  2. **不可解释**：学生只知道「析证清晰度 70」，不知道哪一句话没说到；
  3. **不区分难度**：初级、中级、高级共用一套标准，初级学生反复被「你要能说出方证鉴别」这类高级要求扣分，
     而这恰恰是系统分成三阶梯的意义所在。
- **位置**：`app/services/agent_service.py`（`evaluate_session`）、`app/services/prompts_config.py`（`EVALUATION_PROMPT`）
- **方案**：病案增加结构化评分依据，评分改为「逐条对照 + 按难度过滤」。
- **状态**：✅ 已完成（2026-11-10）：
  1. `medical_cases` 新增 `key_facts`（问诊要点）与 `scoring_points`（评分要点，含 `weight` / `keywords` / `min_level`），
     迁移 `c8d52e3a1f47`；四个新列全部可空，**未配置要点的病案继续沿用原来的模型评分，行为不变**；
  2. 新增 `app/services/scoring.py`：按 `min_level` 过滤（初级只计初级要点、中级追加、高级全计）、
     关键词逐条命中、分阶段小计、问诊完整度；缺 `keywords` 的要点不判定也不进分母，避免配置不全时误扣；
  3. 评价接入：配了要点的病案以要点百分比为 `score`，模型给的综合分降级为 `AI综合评分` 保留；
     评价响应新增 `scoring` 字段，训练页弹窗新增「要点得分」面板（逐条 ✓/✗、权重、漏问项）；
  4. 示范数据：病案 #12 录入 9 条问诊要点 + 11 条评分要点，按档累计满分为
     初级 45 分（3 条）、中级 110 分（+4 条）、高级 170 分（+4 条），
     脚本 `backups/case12_scoring.py` 可作其他病案的录入模板；
  5. 验证：同一份回答在高级档得 76.5%（130/170）、初级档得 77.8%（35/45，另有 8 项高难度不计入），
     区分度符合设计；新增 20 个用例，全套 `257 passed`。
- **未做**：语义判定仍是关键词匹配（同义表达如「枢机不畅」不含「枢机」会漏判），P2-8 提到的双判方案留待后续

---


#### P3-8. 评分要点只覆盖 1/10 病案

- **问题**：`key_facts` / `scoring_points` 目前只有病案 #12 配了，其余 9 例仍走模型自由评分。
- **影响**：「可复现、可解释」的评分框架只对一例生效，大部分训练仍在用旧算法。
- **方案**：在管理端逐例录入（编辑器已就绪）。可按「初级 3 条 / 中级 +3 / 高级 +3」
  的骨架起步，权重按该例教学重点分配。
- **状态**：🟢 待处理（2026-11-13 记录）

#### P3-9. 病案难度字段与标题不一致

- **问题**：`#8 胸痹合病`、`#9 痰饮动态传变` 标题写着【高级】，`difficulty_level` 却是「中级」；
  `#11 百合病` 标题【高级】、字段是「初级」。
- **影响**：按难度筛选时分错档，学生看到的标题与筛选结果对不上。
- **方案**：逐例确认实际难度后统一（管理端可直接改），或改标题与之匹配。
- **状态**：🟢 待处理（2026-11-13 记录）

---


### 当前进度统计

| 优先级 | 总数 | 已完成 | 部分完成 | 待处理 |
|--------|------|--------|--------|--------|
| P0     | 10   | 9      | 1      | 0      |
| P1     | 9    | 8      | 1      | 0      |
| P2     | 10   | 6      | 2      | 2      |
| P3     | 9    | 4      | 1      | 4      |
| **合计** | **38** | **27** | **5** | **6** |

> 2026-11-13 更正：P1-2（健康检查）与 P2-8（进度刷分）此前一直挂着「部分完成」，核对代码后确认
> 前者早已修好、后者本轮补齐，因此各记 +1 完成；同时新增 P3-8（评分要点覆盖不足）、
> P3-9（难度字段与标题不一致）两项待办。当前剩余：P0-10（HTTPS 待服务器）、
> P2-2 / P2-9 / P3-2 部分完成、P2-4 / P2-5 / P3-3 / P3-5 待处理、P3-8 / P3-9 待处理。

> 2026-10-21 更新：新增审计项 12 项（P0-5～P0-10 共 6、P1-7～P1-9 共 3、P2-7～P2-9 共 3）；同时按代码实际状态更正原条目（P1-1/P1-3/P1-5 已完成、P2-1 已完成、P1-2/P1-4/P2-2/P3-2 部分完成）。
> 2026-10-21 第一批修复：P0-5～P0-9 与 P1-7 已完成，P0-10 部分完成（HTTPS/Nginx 待服务器侧配置）。P0 的实质风险已处置，统计记作「完成 9 + 部分 1」。
> 2026-10-21 测试精简：P1-8 完成（解析器 golden 改为运行期生成）、P1-9 大部分完成、P2-9 部分完成；**P1 已清零**。剩余 P2（分页元数据、Docker、废弃 API、学员身份、进度刷分）与 P3。
> 2026-11-10 更新：新增 P3-7（结构化要点评分）并已完成，P3 由 6 项增至 7 项；P2-3/P2-7/P2-8（半）/P2-10 已在此前的会话里收尾。

---

## 改进记录

| 日期 | 编号 | 描述 | 涉及文件 |
|------|------|------|---------|
| 2026-07-25 | — | 创建改进日志文件 | `IMPROVEMENT_LOG.md`（现已合并至本文件） |
| 2026-07-25 | P0-1 | API 路由认证保护（13 个写端点） | `app/dependencies.py`、`app/main.py`、`app/routers/texts.py`、`cases.py`、`analysis.py`、`agent.py` |
| 2026-07-25 | P0-2 | 请求频率限制（自实现 SimpleRateLimiter） | `app/dependencies.py`、`app/routers/agent.py`、`analysis.py`、`documents.py` |
| 2026-07-25 | P0-3 | 文件上传大小限制 + 分级密码（20MB/200MB） | `app/routers/documents.py` |
| 2026-07-27 | — | **修复 AI 患者对正确诊断的识别反馈**：提示词从"绝对不确认"改为"允许患者语言自然肯定"，新增 `_build_progress_hint()` 根据后端进度动态注入行为指令（信任感流露→主动补充细节→完全配合），SAFETY_GUARD 新增"进度感知与行为变化"段落 | `app/services/prompts_config.py`、`app/services/agent_service.py` |
| 2026-07-30 | P0-4 | 生产数据库移出 Git 工作树；部署前自动备份并校验在线记录数 | `server_deploy.sh`、`deploy.sh`、`jingui.service`、`SERVER_DEPLOY_GUIDE.md` |
| 2026-07-30 | P0-4 | 部署健康检查增加约 30 秒重试；Git 降级同步同时更新服务器安全脚本 | `server_deploy.sh`、`SERVER_DEPLOY_GUIDE.md` |
| 2026-07-30 | P0-4 | 修复健康检查访问受保护 API 返回 401 的误报，改为检查公开 `/user` 页面 | `server_deploy.sh`、`SERVER_DEPLOY_GUIDE.md` |
| 2026-07-31 | P0-1 | 修复公开首页请求管理接口导致密码弹窗；分离页面/API认证；补齐公开统计及大文件上传交互 | `dependencies.py`、`main.py`、`agent.py`、`documents.py`、`user.html`、`index.html`、`test_api_routes.py` |
| 2026-07-31 | P3-6 | 新增 Showcase 展示页：Canvas水墨粒子背景、弹簧物理文字动效、破格实验性排版、磁性光标交互、全站Lucide图标；部署降级同步已包含该页面 | `static/showcase.html`、`app/main.py`（新增 `/showcase` 路由）、`server_deploy.sh` |
| 2026-08-03 | P1-6 | 文档解析失败保存错误原因；管理端可显示失败详情并安全重试，保留原始文件与既有数据 | `app/models.py`、`app/database.py`、`app/schemas.py`、`app/routers/documents.py`、`static/index.html` |
| 2026-08-03 | P2-6 | 条文导入系统全面重构：parser.py全新切分算法、raw_content双字段、质量闸门、暂存审核流程、管理端导入面板 | `parser.py`（重写）、`models.py`、`database.py`、`documents.py`（重写）、`import_validator.py`（新增）、`import_review.py`（新增）、`main.py`、`index.html`、`server_deploy.sh` |
| 2026-08-04 | — | 新增用户反馈功能：feedbacks表 + 4个API端点 + 训练页反馈按钮/弹窗 + 管理端反馈面板 | `models.py`、`schemas.py`、`routers/feedback.py`（新增）、`main.py`、`train.html`、`index.html`、`server_deploy.sh` |
| 2026-08-05 | — | 修复文档解析三大Bug：阈值过高导致金匮单章被丢弃、legacy正则括号方向错误、PDF/Excel缺paragraphs字段 | `parser.py` |
| 2026-10-21 | — | 全项目审计并更正文档：新增 P0-5～P0-10、P1-7～P1-9、P2-7～P2-9 共 12 项；按代码实际状态更正 P1-1/P1-3/P1-5/P2-1（已完成）与 P1-2/P1-4/P2-2/P3-2（部分完成）；测试数 127→176 | `PROJECT_MEMORY.md` |
| 2026-10-21 | P0-5～P0-10、P1-7 | 第一批安全修复落地：病案读接口答案裁剪、会话归属令牌、`/live`+`/ready` 探针、上传文件名净化、管理端 XSS 转义、取消内置默认口令、校验器 logger；新增 19 个安全回归测试（195 passed） | `main.py`、`dependencies.py`、`schemas.py`、`routers/cases.py`、`routers/agent.py`、`routers/documents.py`、`services/text_verifier.py`、`services/session_token.py`（新增）、`static/index.html`、`static/train.html`、`tests/conftest.py`、`tests/test_api_routes.py`、`tests/test_security_fixes.py`（新增）、`README.md` |
| 2026-10-21 | P1-8、P1-9、P2-9 | 测试精简与流程隔离：13→6 个文件、183 用例、0 skip、552.91s→3.78s；解析器 golden 改为运行期生成 DOCX；移除 `analysis.py` 四处 `load_dotenv(override=True)`（会在请求期把密钥写回 `os.environ`，是慢与不确定的根因）；`/api/analysis/status`、`/models` 加管理员认证；`.gitignore` 补 `.codex_tmp/`、`output/`；清理 uploads 残留 | `backend/tests/*`（重构）、`app/routers/analysis.py`、`.gitignore`、`.github/workflows/test.yml`、`README.md`、`PROJECT_MEMORY.md` |
| 2026-11-09 | P2-8（半） | 诊法直出：新增 examinations 字段与 examination 服务，号脉看舌直接返回体征（0.84s、不耗 token），重复检查拒绝，未记录项明确提示；`_analyze_progress` 改为只统计学生消息 | `services/examination.py`（新增）、`models.py`、`schemas.py`、`services/agent_service.py`、`alembic/versions/b7c41f2d9e05`、`tests/test_services.py` |
| 2026-11-07 | P2-7 | 学员身份与会话恢复：训练页学号输入 + localStorage 记忆；会话 id/令牌落本地，刷新可继续；`GET /session/{id}` 放行令牌持有者；新增 5 个用例 | `app/dependencies.py`、`routers/agent.py`、`schemas.py`、`static/train.html`、`tests/test_api_agent.py` |
| 2026-11-07 | P2-3 | 列表分页落地：新增 `pagination.paginate` 与 `X-Total-Count` 响应头（响应体不变），接入 7 个端点；配套病案难度筛选、条文排序方向、训练汇总端点；管理端三表加分页控件 | `app/pagination.py`、`routers/texts.py`、`routers/cases.py`、`routers/agent.py`、`main.py`、`static/index.html`、`tests/test_api_admin.py` |
| 2026-11-06 | P2-10、P3-1 | AI 切换至自建 MaaS、8 个阻塞端点由 async 改 sync（避免阻塞事件循环）、备选模型改由 `AI_FALLBACK_MODELS` 配置；新增 `tools/` 备份同步工具集，**P3-1 每日备份完成**；记录 P2-10（空配置时回退到无效模型名）；`maas_check.py` 仅本地保留、不入库 | `app/routers/agent.py`、`analysis.py`、`texts.py`、`app/services/ai_service.py`、`tools/`、`.gitignore` |
| 2026-11-10 | P3-7 | 结构化要点评分：病案新增 `key_facts` / `scoring_points`，评分改为「按要点逐条对照 + 按难度过滤」，评价响应下发 `scoring` 明细，训练页新增「要点得分」面板；示范数据落在病案 #12 | `app/services/scoring.py`（新增）、`app/models.py`、`app/schemas.py`、`app/services/agent_service.py`、`app/routers/agent.py`、`alembic/versions/c8d52e3a1f47_add_structured_scoring.py`（新增）、`static/train.html`、`tests/test_services.py`、`backups/case12_scoring.py` |
| 2026-11-10 | — | 训练对话语义修正三处：诊法识别由名词改为动词（「脉象主肝脾郁」不再被当成要号脉）、四阶段重定义（平脉=切诊完成、析证=病机+鉴别、定治=治法+方剂）、判断错误改为隐晦回应而非附和；训练页进度区改为四步三态并按难度收敛 | `app/services/examination.py`、`app/services/progress.py`、`app/services/guidance.py`、`app/services/agent_service.py`、`app/services/prompts_config.py`、`static/train.html` |
| 2026-11-10 | — | 新增 `tools/restart.ps1`：干净重启（结束旧进程含 `--reload` 父子树 → 等端口真正释放 → 启动 → 轮询 `/ready` → 校验进程启动时间晚于最新 `.py`），解决「旧 worker 占端口导致改了代码却跑旧逻辑」 | `tools/restart.ps1`（新增）、`tools/restart.cmd`（新增）、`tools/README.md` |

---

## 已完成功能清单

以下是本项目从启动到当前已完成的各项功能与改进（按时间顺序）：

1. ✅ 智能体核心：单次分析→三阶梯多轮交互
2. ✅ 结构化病例：含"病脉证并治"教学要点，从7例扩充到9例
3. ✅ 训练中隐藏病案信息，评价后揭晓
4. ✅ 独立条文学习页面（按病证分类）
5. ✅ AI 输出清理（去 markdown 符号）
6. ✅ AI 辅助进度判断
7. ✅ 防暴力破解（两级：硬越狱拦截 + 玩笑请求适配）
8. ✅ 经典范围自适应（不硬扯金匮/伤寒）
9. ✅ 训练不强制结束（学生主动评价）
10. ✅ 管理端手动录入条文
11. ✅ 提示词可编辑（prompts_config.py）
12. ✅ 迁移至 DeepSeek 官方 API（更快更稳定）
13. ✅ 提示词重构：AI 纯患者角色，禁用教师行为
14. ✅ 患者人格系统：语气风格池+情绪升级+贴吧老哥模式
15. ✅ 导入伤寒论398条全文
16. ✅ Study 页面：金匮要略/伤寒论分组显示
17. ✅ 管理端新增条文管理面板（CRUD+批量删除）
18. ✅ 修复 AI 空返回导致数据库写入失败
19. ✅ 修复 DeepSeek API 角色映射（student→user）
20. ✅ 西医检查适配：学生要求抽血/CT时，AI根据病案生成合理数据
21. ✅ 提示词增强：输入内容感知、6种人格、多样化拒绝语
22. ✅ 新增2例病案：黄疸（中级）+百合病（高级），共9例
23. ✅ 情绪分级细化：2轮→5轮基础耐心，完整升级节奏拉长至20轮，增加"医生是否有进展"条件判断
24. ✅ 医学常识约束：AI发挥不能编造核心症状，检查结果要与病案症状一致，口语化转述不背检验单
25. ✅ 评价附加原条文：训练结束后自动匹配并展示与病案相关的《金匮》/《伤寒》经典条文
26. ✅ 补充核心测试体系：从0→127个自动化测试，pytest + SQLite内存引擎
27. ✅ 修复全局异常处理器：RequestValidationError(422) 不再被吞成 500
28. ✅ pytest-cov 覆盖率报告 + GitHub Actions CI 集成
29. ✅ API 路由认证保护：13 个写端点全部加管理员密码验证
30. ✅ 请求频率限制 + 文件上传分级管控（≤20MB/200MB + 密码分级）
31. ✅ 生产数据库移出 Git 工作树，部署前自动备份并校验在线记录数
32. ✅ AI 患者对正确诊断的识别反馈（进度感知与行为变化）
33. ✅ 公开页面避免触发管理密码弹窗（页面/API认证分离 + public-stats）
34. ✅ Showcase 展示页：Canvas 水墨粒子 + 弹簧动效 + Lucide 图标
35. ✅ 文档上传失败可诊断与可重试
36. ✅ 条文导入系统全面重构（parser重写 + 质量闸门 + 暂存审核流程）
37. ✅ 用户反馈功能：训练页提交反馈 + 管理端反馈面板（4个API端点）

---

## 当前状态

- **版本**：**1.1.0**（2026-10-21 发布，变更见 `CHANGELOG.md`，tag `v1.1.0`）；1.0.0 基线见 tag `v1.0.0`
- **部署**：原阿里云轻量服务器 `YOUR_SERVER_IP`（systemd 自启、80→8000 转发、生产库在 `/var/lib/jingui`）**已到期下线**，公网无访问地址；当前仅在本地运行（`uvicorn app.main:app`，数据落 `backend/data/`，由 `DATA_DIR` 控制）
- **数据**：本地 `backend/data/tcm.db` 实测（2026-11-24 晚）：条文 **804 条**（伤寒论 398 + 金匮要略 406，覆盖 23 篇）+ **256 例训练病案**（难度 初级 29 / 中级 178 / 高级 51，**全部**已配 `key_facts` 与 `scoring_points`）+ 条文-病案关联 **409 条**（覆盖 252 案）+ 23 会话 / 168 消息 / 57 条学习记录 / 4 个上传文档。生产库已同步至相同状态。数据库文件不在版本控制中（由 `tools/backup_local.py` 备份），首次启动由 Alembic 建空库，需先跑 `seed_texts.py` / `seed_cases.py`
- **AI**：某高校自建 MaaS（GPUStack，`https://maas.example.edu.cn/v1`），主模型 `example-model`；备用模型经 `AI_FALLBACK_MODELS` 配置（现为 `deepseek-chat`；平台暂只开放 `example-model`，故备用暂不触发）
- **备份**：`tools/` 提供本机每日备份（保留 90 份）与服务器同步（recent 14 / daily 180 天），统一走 SQLite Online Backup API + `integrity_check`；产物在 `backups/local/`、`backups/server/`（不入 git）
- **前端**：6个页面（管理端、首页、训练端、学习页、Showcase、新首页），管理端含条文管理+导入审核+用户反馈面板
- **提示词**：纯患者角色，含人格系统+情绪分级（大幅拉长节奏）+贴吧老哥模式+输入内容感知+西医检查适配+医学常识约束
- **评价**：训练结束后自动匹配并展示相关《金匮要略》/《伤寒论》原条文
- **测试**：**9 个文件、279 个自动化测试、0 skip**（2026-10-21 精简后为 6 文件 / 183 用例 / 3.78s；
  此后补诊法、会话恢复、结构化评分等用例，2026-11-10 按主题拆文件并合并重复用例；
  2026-11-18 实测 `279 passed in 4.85s`）；解析器回归改为运行期生成 DOCX，测试全程隔离在临时目录
- **覆盖率**：**65%**（2026-10-21 实测，`--cov` 全套 7.41 秒）；`.coveragerc` 的 `fail_under = 0`（不阻断 CI）
- **CI**：GitHub Actions（`.github/workflows/test.yml`），push/PR 自动运行测试+覆盖率；精简后本机全量约 4 秒，不再依赖外部 AI 服务
- **安全**：写操作认证保护 + 频率限制 + 上传分级管控。第一批修复后：病案读接口不再下发答案（公开视图与 `/admin/` 分离）、训练会话凭 `X-Session-Token` 校验归属、`/live` + `/ready` 探针状态码正确、上传文件名 UUID 化并限定扩展名、管理端渲染已转义、内置默认口令已取消。**剩余：HTTPS/Nginx 未配置（P0-10 部分完成）、限流为单进程内存态**
- **改进追踪**：P0-5～P0-9 全部修复、P0-10 部分完成（HTTPS）；P1 已无待处理项（P1-2/P1-4/P1-9 三项部分完成）；全清单 36 项中剩 4 项待处理、7 项部分完成（详见上方改进清单）
- **评分体系**：病案可配 `key_facts` / `scoring_points` 走「按要点逐条对照 + 按难度过滤」，
  未配置的病案沿用模型评分；当前示范数据只有病案 #12，其余 8 例仍是旧路径
- **本地运维**：服务重启统一用 `tools/restart.ps1`（`-Check` 体检），避免旧进程占端口导致"假重启"

---

## 工作日志

### 2026-11-10 会话记录

**训练对话语义修正（诊法、四阶段、纠错）**

- **问题**（都是实机试出来的，不是设想）：
  1. 学生说「脉象主肝脾郁」，系统当成"要号脉"，回了一句脉象——正则匹配的是**名词**而非动作；
  2. 重复号脉没有任何提示，学生不知道已经查过；
  3. 患者自己接话时带出「（医生进一步分析病机，但未提及具体方剂）」这类旁白，出现在学生视野里；
  4. 学生把病判错（说"我是少阳证"）时，患者回「您说得对」——把错误判断确认了。
- **四阶段重定义**（这是根因，诊法问题只是表象）：
  - 原实现把「平脉」当成"说出脉象含义"，导致学生一报脉名就点亮，与切诊行为脱节；
  - 现定义：**平脉 = 完成切诊**（号过脉即完成，不看是否解释含义）；**析证 = 病机 + 鉴别**（两者都要）；**定治 = 治法 + 方剂**（两者都要）；
  - 脉象的**含义**归入析证，符合"切诊收集信息、析证推演病机"的临床顺序；
  - 辨病支持六经简称（太阳/阳明/少阳…），并在匹配前剥离「与…鉴别」从句，否则鉴别句里的病名会把自己判成已辨病。
- **实现**：
  1. `examination.py` 的识别规则改为匹配**动作**（诊、号、看、摸、查…）并排除解读句；33 种说法全部回归；
  2. 新增 `services/guidance.py`：按阶段产出下一句引导（问诊 → 析证 → 定治 → 已完成），
     输入框下灰线每轮都在，聊天流提示只在阶段跃迁时插入——两种强度对应两种场合；
  3. `_strip_meta_commentary()` 剥离括号开头的评估旁白，但保留诊法直出的「（患者伸出手腕…）」；
  4. `_is_confirming_judgement()` + `_hedged_reply()`：学生下病名诊断时，患者不给评价，
     只回「这个我不太懂，医生您能说说我到底是啥毛病吗」——**保留纠错标签，但不确认病名**；
     身体感受（"是不是夜间加重"）仍可正常确认；
  5. 训练页进度区改为四步三态（已完成/进行中/未开启）+ 状态行，并按难度收敛（初级只看辨病、中级看到析证、高级四步全亮）。
- **实机验证**（会话 20，病案 #12，高级）：主诉 → 号脉（0.60s，直出「脉弦缓」）→ 判断 → 方案，
  辨病/平脉/析证在"判断"那轮同时翻转，定治在"方案"那轮翻转，提示依次 问诊 → 析证 → 定治 → 已完成。
- **涉及文件**：`app/services/examination.py`、`app/services/progress.py`、`app/services/guidance.py`（新增）、
  `app/services/agent_service.py`、`app/services/prompts_config.py`、`app/routers/agent.py`、`app/schemas.py`、`static/train.html`

**本地重启脚本（`tools/restart.ps1`）**

- **背景**：排查上面这些问题时反复遇到"改了代码但页面没变"。查下来是 21:03 启动的孤儿 uvicorn worker
  仍占着 8000 端口，新进程绑定失败即退出，旧进程照常响应——**"重启成功"是假象**。
- **脚本流程**：收集端口占用与本项目 uvicorn（含进程树）→ `taskkill /T /F` → 等端口真正释放 → 启动 →
  轮询 `/ready` → **校验新进程启动时间晚于最新 `.py` 修改**，否则直接警告"你跑的是旧代码"。
- **过程中又踩到三个 Windows 坑**：
  1. `--reload` 模式下杀子进程，父进程毫秒内重新拉起一个，端口永远不释放 → 改为最多 6 轮循环复查；
  2. Windows PowerShell 5.1 读无 BOM 的 UTF-8 脚本会按 GBK 解析，中文字符串被截断后报"缺少字符串终止符"
     ——是假语法错误，**脚本必须存成 UTF-8 with BOM**；
  3. `chcp 65001` 会改变 cmd 解析后续行的编码，`restart.cmd` 里的中文 `rem` 会被当命令执行 → 包装脚本写成纯 ASCII。
- **防护**：端口被非 python 进程占用时只警告不杀；项目进程匹配收紧到 `--port <目标端口>`，避免误伤别的项目。
- **验证**：`-Check` 能识别正常态；人为把 `progress.py` 时间戳推到进程启动之后，立刻报"当前跑的是旧代码"，
  改回后恢复；完整重启 5.6s 就绪；`-Port 8001` 不会把 8000 的进程算进来。
- **涉及文件**：`tools/restart.ps1`（新增）、`tools/restart.cmd`（新增）、`tools/README.md`

**P3-7 结构化要点评分**

- **背景**：见改进清单 P3-7。一句话概括——旧机制**奖励「猜对病名」**，新机制要求**「拿出依据」**。
- **数据**：`medical_cases.key_facts`（问诊要点）与 `scoring_points`（评分要点），
  `training_sessions.evaluation` / `scoring`（评价原文与明细落库），迁移 `c8d52e3a1f47`。
  四个列全部可空，**没配要点的病案行为完全不变**——这是渐进式改造的前提。
- **层级过滤**：每条要点带 `min_level`，语义是"从哪一档开始计入"。
  初级只统计初级要点，中级追加，高级全计。这样初级学生不会被"你要能说出方证鉴别"扣分。
- **评分器**（`services/scoring.py`）：关键词逐条命中 → 分阶段小计 → 按当前难度**实际参与的总权重归一**。
  缺 `keywords` 的要点不判定、也不进分母（`hit=None`），避免配置不全时把学生误判成没答对；
  一条都判不了时 `gradable=False`，不覆盖原有评分。
- **问诊完整度**：`key_facts` 只统计"问到了几项"，不参与主分——没问到不等于答错，它只用来提示「你漏问了头晕乏力」。
- **评价接入**：配了要点的病案，`score` 取要点百分比，模型给的综合分降级为 `AI综合评分` 保留
  （模型分会随温度浮动，规则分可复现）。
- **顺带修的两个旧问题**：
  1. 重复打开已评价会话时，`evaluation` 返回的是 `decision_path`（把辨治路径当评价报告）；
     现评价原文落库，旧数据仍回退 `decision_path`；
  2. 结算与安全复盘只取最近 20 条消息，超过 20 条的会话前半程被忽略——改为结算取全量。
- **前端**：评价弹窗新增「要点得分」面板，按阶段分组、逐条 ✓/✗、显示权重与漏问项，
  并注明「另有 N 项要点属于更高难度，本次不计分」。
- **示范数据**：病案 #12 配 9 条问诊要点 + 11 条评分要点（初级 3 条 45 分、中级 4 条 65 分、高级 4 条 60 分），
  录入脚本 `backups/case12_scoring.py` 可作其他病案的模板（支持 `--dry-run`）。
- **实机验证**：同一份学生回答——高级档 **76.5%**（130/170，11 条全计）、
  初级档 **77.8%**（35/45，另 8 项高难度不计入）。问诊完整度 5/6，正确指出漏问"头晕乏力"。
- **测试**：新增 20 个用例（层级过滤、关键词命中、无关键词不判、未配置返回 None、完整度、评价接入、
  同答案跨难度分数不同），全套 `257 passed`。
- **没做**：语义判定仍是关键词匹配，「枢机不畅」这类同义表达会漏判；P2-8 提到的
  "规则兜底 + LLM 复核"双判留待后续。
- **涉及文件**：`app/services/scoring.py`（新增）、`app/models.py`、`app/schemas.py`、
  `app/services/agent_service.py`、`app/routers/agent.py`、`alembic/versions/c8d52e3a1f47_add_structured_scoring.py`（新增）、
  `static/train.html`、`tests/test_services.py`、`backups/case12_scoring.py`（新增，本地保留）

**按实测反馈修正（同日第二轮）**

- **触发的实测**：教师按高级难度做了一遍病案 #12，六轮对话后被系统宣告"四阶段已完成"，
  可学生**一个方都还没开**；评价只给了 26.5 分，而 AI 评语还写着"定治合理"。
  三个问题叠在一起，正好把这套机制的短板全暴露了。
- **① 定治被 AI 复核点亮（真 bug）**：规则层判定是「辨病✓ 平脉✓ 析证✗ 定治✗」，
  但 `_merge_ai_progress` 允许模型补任意阶段。学生说了「应当调和营卫，疏肝解郁」，
  模型就认定定治完成——它不知道定治的定义是"治法 + 方剂"。
  **修复**：AI 只能补「辨病 / 析证」，平脉（=真做过切诊）与定治（=同时有治法与方剂）
  是硬条件；阶段名也一律按规则重算，不再采信模型说的「已完成」。
- **② 结束文案一律写"对话已达上限"**（前端写死）：四阶段完成和轮次上限本是两回事。
  现按 `guidance.stage` 区分。修复后实测六轮仍在进行，患者开始反过来催"您给我开点药吧"，
  这正是期望的行为。
- **③ 问诊完整度误报**：学生开场白里患者已经交代了病程、季节、口苦、心烦，
  系统却判"漏问 5 项"。现把信息分为三档：学生主动问到（asked）、患者自己交代（revealed）、
  真的双方都没提（missing）。只有第三档才算漏。
- **④ 关键词漏判**：学生说「疏风解表的话不能力达体内」，意思就是"前医之失"，
  但要点只收「伤正 / 壅邪 / 前医」，判成没答对。扩词解决了一部分，但治标不治本。
- **⑤ 语义复核（两轮翻车才做对）**：
  1. 第一版把"没判上"的条目交给模型复核，要求"同义表达也算"——**模型直接把 11 条全判命中，给了 100 分**；
  2. 第二版加了硬约束：必须引用学生原话作依据，且**依据必须能在原文里 substring 找到**，
     否则不采纳。这条闸挡住了编造，但挡不住"牵强引用"——模型用「调和营卫」去证明
     「方选柴胡桂枝汤」，学生明明没开方；
  3. 第三版加 `strict` 标记：**方剂、方义、是否做了鉴别**这类字面事实不送审，只认关键词。
  另外把输出从"逐条列出 true/false"改成"只列命中的"，并加了 JSON 解析兜底
  （模型偶尔输出超长非法 JSON，实测一次直接让整次复核白跑，还耗时 82 秒）。
- **⑥ 评价与规则打架**：AI 评语说"定治合理"、规则说方剂缺失。现把规则命中情况
  写进评价提示词，并要求模型分项评分与之对齐，不一致只能在「改进建议」里说明理由。
- **验证**（重放原始六轮对话）：不再提前结束；要点得分 26.5% → **55.9%**
  （方剂、方义、鉴别仍判未答，口苦、春秋病机确实没说过）；关键信息从"漏问 5 项"变为
  "患者已交代 5 项、无遗漏"；全套 `274 passed`。
- **教训**：拿 LLM 当裁判要两道闸——**证据必须可溯源**，以及**字面事实不交给模型猜**。
  只做第一道，它会把"相关"说成"就是"；两道都没有，就直接给满分。
- **涉及文件**：`app/services/agent_service.py`、`app/services/scoring.py`、
  `app/services/prompts_config.py`、`static/train.html`、`tests/test_services.py`、
  `backups/case12_scoring.py`、`backups/replay_session.py`（新增，本地保留）

**管理端要点录入界面（同日第三轮）**

- **问题**：`key_facts` / `scoring_points` 只能通过 API 或改脚本录入。
  可要点怎么定是教学判断，应该由教师自己填，不该让代码挡在中间。
- **实现**（`static/index.html` 病案编辑弹窗）：
  1. 新增「问诊要点」「评分要点」两个表格编辑器，逐行增删，输入即写回内存对象，不需要手动保存每一行；
  2. 问诊要点：标签 / 是否必问 / 匹配关键词 / 起始难度；
     评分要点：阶段 / 描述 / 权重 / 关键词 / 起始难度 / **只认字面**（`strict`）；
  3. 底部实时汇总「累计满分：初级 X / 中级 Y / 高级 Z」——权重是分档累加的，
     这个数字能直接看出当前难度梯度合不合理，不用心算；
  4. 编辑时按原 `id` 回填并原样写回，不丢既有字段；
  5. 未配置要点时明确提示"该病案仍按模型自由评分（旧算法）"，避免误以为不生效。
- **验证**（本机未装 Chrome，走静态 + 接口两层）：
  1. 静态引用检查——HTML 里 71 个 id 与 JS 的 58 处 `getElementById` 全部对得上，
     36 个 `onclick` 调用的函数都有定义（这类拼写错误只在浏览器里炸，最难查）；
  2. 用与前端完全相同的 payload 走 `PUT /api/cases/12` → `GET` 读回：
     新增一条、改一个权重，条数与数值都对；随后还原（11 条 → 12 条 → 11 条）；
  3. 内联 JS 经 `node --check` 通过。
- **涉及文件**：`static/index.html`

**测试脚本整理（同日第四轮）**

- **问题**：`test_services.py` 涨到 1064 行、24 个测试类，文本清理、越狱、进度、用药安全、
  诊法、引导、结构化评分全挤在一个文件里，改一处得滚半天；另外两个验证脚本
  （重放对话、验证评分）散在 `backups/`，不在版本控制里，参数写死，用完即弃。
- **拆分**：按主题切成 4 个文件，测试总数与行为不变。

  | 文件 | 内容 | 行数 |
  | --- | --- | --- |
  | `test_text_utils.py` | 文本清理、回复分类、决策点提取、经典范围识别 | 153 |
  | `test_safety.py` | 越狱拦截、玩笑降级、用药安全复盘、旁白清理 | 266 |
  | `test_training_flow.py` | 四阶段进度、诊法直出、阶段引导、AI 复核边界 | 305 |
  | `test_scoring.py` | 难度过滤、关键词命中、语义复核、完整度、评价接入 | 353 |

  做法是**按行切片保真**而不是手抄：原文件是 CRLF，切片时保留原始字节，
  四个新文件行尾统一（`stray LF = 0`）。搬移过程中补了 3 处漏掉的 import
  （`MedicalCase`、`TrainingSession`、`MagicMock`、`patch`），都是拆分后才发现。
- **整理验证脚本**：把 `backups/replay_session.py` 与 `backups/verify_scoring_live.py`
  合并为 `tools/verify_training.py`，两种模式：
  `quick`（写库补发言后直接评价，十来秒）与 `replay`（逐轮真实对话，验"会不会提前结束"）；
  参数化病案 id / 难度 / 服务地址，结束时自动删除自己造的会话（读 `.env` 的 `ADMIN_PASSWORD`），
  读不到就保留并打印 id。退出码区分「链路异常」与「提前结束」。
- **验证**：拆分后全量 `274 passed`（迁移 179 + 其余 95，与拆分前一致，无跳过）；
  `quick` 模式对病案 #12 打出 76.5%（130/170）与逐条命中；`replay` 模式六轮后仍为 `active`。
- **顺带发现（未改，待定）**：`replay` 那轮里语义复核采纳了 4 条，其中「口苦心烦胆郁化热」
  「春秋阴阳气交」两条学生并未提过——模型把相关语句当成了依据。说明证据闸门只能防编造，
  挡不住"牵强引用"，语义复核仍会虚高。是否默认关闭该机制，需要教师侧拍板。
- **涉及文件**：`tests/test_text_utils.py`、`tests/test_safety.py`、`tests/test_training_flow.py`、
  `tests/test_scoring.py`（均新增）、`tests/test_services.py`（删除）、`tools/verify_training.py`（新增）、
  `tools/README.md`

**测试用例合并（同日第五轮）**

- **问题**：274 个用例里有 24 个是「同一个函数的不同方向」被拆成了多个测试函数，
  例如 `select_points` 的四档行为占了 5 个函数、`_extract_decision_point` 的
  病名/脉象/方剂各占一个。看上去用例很多，实际上失败时定位也没更细。
- **合并原则**：只合并**同一函数、同一设施、连续断言**的场景；参数表、独立场景一律不动。
  合并后失败信息仍带具体断言行，不影响定位。
- **结果**：

  | 文件 | 函数 | 用例 | 变化 |
  | --- | --- | --- | --- |
  | `test_scoring.py` | 33 → 22 | 33 → 22 | 层级过滤 5→2、评价 3 组合并、语义复核 3 组合并、完整度 3→1 |
  | `test_text_utils.py` | 20 → 11 | 40 → 31 | 决策点 5→2、经典范围/玩笑上下文/西医检查各 3→1 |
  | `test_safety.py` | 20 → 16 | 78 → 74 | 用药安全 4→2、输出护栏 5→3 |
  | **合计** | **190 → 166** | **274 → 250** | −24 函数、−24 用例 |

- **明确没减**：越狱话术 58 组参数、解析器 18 条、API 认证/分页/路径穿越——每条对应一个独立失败模式，
  合并只会丢防护。全量 `250 passed in 4.46s`。
- **涉及文件**：`tests/test_scoring.py`、`tests/test_text_utils.py`、`tests/test_safety.py`

**语义复核拆分：要点计分默认关闭（2026-11-13）**

- **背景**：语义复核此前同时管两件事——把规则没判上的**要点**交给模型加分，
  以及核对**患者是否已交代**某条信息。实测三次，要点那块净作用是负的：
  | 实测 | 送审 | 结果 |
  | --- | --- | --- |
  | 初版 prompt | 7 条 | 全判命中，直接给满分 |
  | 加证据校验后 | 4 条 | 采纳 4 条，其中「口苦」「春秋病机」学生根本没提，虚高 30 分 |
  | 收敛后 quick | 3 条 | 采纳 0 条，对分数零贡献 |
- **判断**：病机、方剂这类判断有明确标准答案，学生说了关键词就能命中，模型反而会把
  「相关」当成「就是」。而信息完整度不同——患者说「嘴巴又干又苦」而要点写「口苦」，
  关键词认不出同义说法，模型能认出；这项不计分，判错也只影响提示。
- **改动**：
  1. `build_semantic_review` 拆成两个开关，默认 `SCORING_SEMANTIC_POINTS=关`、
     `SCORING_SEMANTIC_FACTS=开`；
  2. prompt 改为按需拼装：只有要点时发要点段、只有信息时发信息段，两者都空则**不发起调用**
     （多数会话能省掉这次请求）；
  3. `apply_semantic_review` 不变——传入的列表为空时自然不生效。
- **验证**：默认配置下送审要点数为 0、信息照常核对；信息已全部交代时返回 `None`（不调用）。
  测试新增「默认只审信息」「信息齐了不调用」两例。

**进度判定加固：陈述句过滤 + 模型否决（2026-11-13）**

- **背景**：P2-8 的剩余问题——「是不是少阳病？」「不像少阳」都含关键词，
  旧逻辑会把它们当成「学生做出了判断」并点亮阶段。
- **第一层：陈述句过滤（本地，零成本）**
  新增 `progress.statement_text()`：按句末标点切句，剔除问句（句末问号/语气词、句首疑问结构）
  与否定句；否定句再按逗号拆开，保留其中的肯定分句——「不像少阳，应该是太阳病」
  会保留后半句。`_analyze_progress` 只用过滤后的文本做匹配。
- **第二层：模型否决（只在阶段首次点亮时调用）**
  - 规则点亮「辨病 / 析证」后，把学生最近 6 条原话交给模型判断「这是判断，还是提问/否定/复述」；
  - **只做否决**：模型说不清、超时、返回坏 JSON 都保留规则结果（fail-open），进度不会被卡住；
  - 判定为否 → 撤销该阶段，并级联回退下游（析证没了定治也要退）；
  - 通过则记入 `training_sessions.verified_stages`，同一阶段不再重复调用，
    一场会话最多两次；
  - prompt 明确「宁可放过，不要误拦」——误拦比误判更影响学生。
- **存储**：迁移 `d9e63f4b2c18` 新增 `training_sessions.verified_stages`（可空）。
  旧会话为空按未复核处理，行为与之前一致。
- **验证**（环境恢复后补跑）：
  1. 迁移 `c8d52e3a1f47 → d9e63f4b2c18` 执行成功；
  2. 全量 `263 passed`；
  3. 实机对病案 #12 逐句验证：问句「是不是少阳病？」不点亮；纯否定「不像少阳病。」不点亮；
     混合句「不像少阳，应该是太阳病」点亮（后半句是判断，符合预期）；
     陈述「考虑少阳枢机不利。」点亮；
  4. 复核确实执行：第二句陈述后 `verified_stages = ["辨病"]`，说明模型确认通过并写入缓存；
  5. 顺带确认既有防猜设计仍生效——单条消息（`turns < 2`）不会点亮辨病。
- **过程记录**：本项改到一半时 DSH 的命令执行器出现 link-count 故障（与项目无关，
  任何命令都无法启动），迁移与测试是环境恢复后补跑的；期间只做了文件级改动，代码未丢。

**患者编造症状的检测与标注（2026-11-18）**

- **问题**：实测病案 #12（反复感冒、少阳枢机不利，症状只有头晕乏力、喷嚏、口苦口干、
  纳呆食减、心烦易怒）时，患者模型说「我就是咳得厉害、痰多」——咳嗽和痰都不在病案里。
  学生若信了，辨证就建在虚构信息上。
- **原因**：提示词里写着「可以补充次要日常细节」，模型把这个口子用到了症状上；
  而且没有任何输出侧校验。
- **三层处理**：
  1. **提示词收紧**（`prompts_config.py`）：改成白名单式——只允许补充睡眠、饮食、二便、
     情绪、作息、天气感受；明确「禁止新增任何身体不适」，并列了咳嗽、痰多、恶心等反例；
     病案没写的一律回答「没这回事」「这个我说不好」。
  2. **上下文强调**（`_format_case_info`）：给患者的症状段改成
     「【症状描述（这是你全部的不适，除此之外没有任何别的症状）】」，让"全部"这件事显式。
  3. **输出侧检测**（新增 `services/symptom_guard.py`）：32 组症状词表（同义归并），
     比对回复与病案 `symptoms/content/diagnosis/teaching_points`，找出病案外的症状；
     命中就在回复末尾加一行注记，同时写 warning 日志。
- **两个关键设计**：
  - **注记只进展示、不进对话历史**：入库的仍是原始回复。否则下一轮模型会在上下文里
    看到「注」并跟着模仿，评价也会被这行字污染；
  - **否定语境过滤**：患者回答「咳嗽倒是没有」「不咳嗽，也没痰」不能被当成编造。
    实现分两级——紧邻否定（关键词前两字是"不/没/无/未"）与窗口否定（前后六字内有
    "没有/不太/从不"等）。第一版只做了窗口级，实机立刻把「不咳嗽」误标了，补上紧邻判定才好。
- **注记措辞**（用户选定）：
  「（注：患者提到的「咳嗽、鼻塞流涕」病案未记载，属其自由发挥，不作为辨证依据）」
  环境变量 `SYMPTOM_NOTICE=0` 可关闭。
- **验证**：`279 passed`；实机两轮——
  「不咳嗽，也没痰。就是鼻子难受」→ 不标注；
  「鼻子堵，打喷嚏，流清鼻涕」→ 标注「鼻塞流涕」；库中助手消息零注记。
- **顺带发现**：病案 #12 的 `symptoms` 只写了「时时喷嚏」，没有鼻部症状，
  所以患者一说「鼻子堵、流清鼻涕」就会触发标注。这不是误报（确实没记载），
  但说明病案的症状记录偏简，补充病案描述能减少这类提示。
- **未做**：词表覆盖有限（「嗓子发痒」「肚子咕噜」不在表内），漏检仍会发生；
  本轮只做检测与提示，不做自动重写。

**医案批量导入：250 条医案入库（2026-11-24）**

- **来源**：桌面《金匮_病案题.xlsx》Sheet1，250 条医案原文（总 6.5 万字，平均 260 字）。
  每条是一整段：患者信息 → 病史 → 症状舌脉 → 辨证 → 治法 → 处方（部分带复诊）。
- **工具**：新增 `tools/import_cases.py`。逐条调模型解析成 8 个字段，
  支持 `--start/--limit` 断点续跑、`--dry-run` 只看不写、每 20 条自动落库；
  状态记在 `.codex_tmp/case_import_state.json`。
- **字段**：title / difficulty_level / content / symptoms / diagnosis / prescription /
  correct_answer / teaching_points。难度按**病情复杂程度**判定（不是按出自哪本书）。
- **踩了三个坑**：
  1. **模型在 JSON 字符串里直接换行**（teaching_points 多条要点），标准 JSON 不接受
     → `json.loads(..., strict=False)` 允许字符串内控制字符，并加正则兜底；
  2. **输出被截断**：`max_tokens=2000` 时 teaching_points 停在「4. 」，后面的
     correct_answer 根本没生成 → 提到 3000，并把「缺 correct_answer」判为失败重试；
  3. **模型偶发整个省略 correct_answer**（不是截断，`finish_reason=stop`）
     → 把 correct_answer 在 JSON 模板里提到 teaching_points 之前，并明确「八个字段一个都不能少」。
- **结果**：250 条全部解析成功，新增 **248 条**（2 条同名跳过），失败 0。
  单条耗时 17–50 秒，全程约 2 小时。
- **难度分布**（新导入 248 条）：中级 173、高级 50、初级 25。
  中级占比 70%——源数据本身多为有兼证、需鉴别或加减的医案，不是判定失灵；
  但初级偏少，若要做初级训练需要再补一批简单病案。
- **质量抽检**：8 个字段 258/258 齐全；content 含脉象 237/258（92%）、
  含舌象 164/258（64%）——原文没有舌象的那部分不强求。
- **与现有病案的关系**：#13「感冒——少阳枢机不利证」是现有 #12 的**原文版**
  （#12 是改写版且配了 examinations 与要点）。按「重复时保留网站现有」的处理，
  暂留 #12；#13 是否删除待定。
- **生产同步**（2026-11-24，用户要求病案数据绝不进 git）：
  1. 先备份生产库 `/var/lib/jingui/tcm.db.bak-20261124`；
  2. 本地导出 `id > 13` 的 247 条到 `.codex_tmp/`（该目录已在 `.gitignore` 内），
     JSON 356KB → gzip 101KB；
  3. `scp` 直传服务器 `/tmp`（首次直传被中断，压缩后成功），服务器端 python 脚本按标题去重插入；
  4. 结果：生产 10 → **256 例**（新增 246，同名跳过 1），会话 27 条未动；
  5. 验证：`/ready` 正常、`systemctl is-active` active、公开 `/api/cases/` 仍只返回
     id/title/content/symptoms/difficulty_level（**不含答案**）；
  6. 两端临时文件（导出 JSON、压缩包、导入脚本）已删除。
- **两地差异**：本地 258、生产 256。差的是 #13（与生产 #12 重复的原文版）与一条同名病案。
- **未做**：
  - 新病案没有 `examinations`（脉舌客观体征），训练时号脉会显示「本例未记录」，需要后续从
    `symptoms` 提取补充；
  - 没有 `key_facts` / `scoring_points`，仍走模型自由评分。
- **涉及文件**：`tools/import_cases.py`（新增）、`backend/data/tcm.db`（本地数据）

**生产库权限收紧与备份补档（2026-11-24）**

- **纠正一个判断**：此前说「备份完全没有自动化」是错的——当时只查了服务器 crontab，
  漏看了本机的 Windows 计划任务。实际有两个任务一直在跑：
  `JinGui-LocalBackup`（每天 03:00 备份本地库）与 `JinGui-ServerSync`（每天 04:00 拉生产快照）。
- **权限**：生产 `/var/lib/jingui/tcm.db` 及 `-wal`/`-shm`/`.bak` 由 644 改为 600；
  服务以 root 运行不受影响，改后 `/ready` 正常、systemd active。
- **补档**：手动同步一次（`tools/sync_server.py`），把 09:06 导入后的 256 条拉到
  `backups/server/recent/tcm-20261124-095841.db`；当日 `daily/tcm-20261124.db` 原为 04:00 的
  10 条旧版，已用最新快照覆盖。
- **备份现状**：本地备份 17 份（12MB，保留 90 天）、服务器 recent 3 份 / daily 2 份（4.4MB）。
  本地库 258 条包含生产全部 256 条，生产库丢失可用本地恢复。
- **仍缺**：生产服务器自身没有本地快照，恢复依赖本机；备份都在同一台机器上，没有异地副本。

**条文库补全、评分要点与条文关联（2026-11-24 晚）**

- **条文库补全**：从 `D:\文档表格\金匮条文库` 的 20 个 docx 解析，金匮由 58 条（3 篇）
  补到 **406 条（23 篇）**，全库 456 → **804**。工具 `tools/import_classics.py`：
  复用项目解析器按「句末（N）」切分，再清掉小节标题、方名行、方药组成、煎服法与附方，
  20 篇共切出 348 条、丢弃 21 段非条文，按篇去重可重复执行。
- **评分要点**：256 / 256 全部生成（`key_facts` + `scoring_points`），工具
  `tools/generate_scoring.py`。定了几条硬规则：权重按**阶段总和**归一（辨病 25 / 平脉 15 /
  析证 40 / 定治 20）、`key_facts` 只列开口问得到的（舌脉靠切诊，不列）、`must_ask`
  不超过一半、方名与鉴别类要点标 `strict`。
- **⚠ id 漂移事故**：生成任务按 id 回写，而任务运行期间库里有两条重复病案被删、
  后续 id 整体前移，导致 **245 条要点写到了邻居身上**（#238 妊娠恶阻拿到了「癫痫」的要点、
  #257 眩晕拿到了「肺癌术后」）。发现靠抽查，修复没有重跑：用 state 里保存的 title
  重新映射到当前 id 批量重写，再单独恢复 #12 与补跑 1 条只够拆 3 个要点的病案。
  **教训**：批量写库前要确认库不再变动；写库应认标题这类稳定键，而不是自增 id。
- **条文关联**：`text_case_relations` 从 0 补到 **409 条**（覆盖 252 个病案，平均 1.6 条）。
  - 先修匹配器：条文是繁体、病案是简体（`栝樓薤白白酒湯` vs `栝楼薤白白酒汤`），
    加 `zhconv` 繁简归一（带缓存），并给「病名直接命中条文」加权——此前靠 21 个固定症状词，
    「胸痹之病，喘息欬唾…」里一个都没有，永远匹配不上；
  - 再用 `tools/build_relations.py`：matcher 取 top-20 候选 → 模型挑 1–4 条真正相关的；
  - 抽检 8 条对 6 条。局限：候选池里没有正确条文时（病名与条文用词不同，如「湿病」vs「湿痹」）
    模型只能矮子里拔将军。
- **同步生产**：生产条文已是 804（先前整库同步过），本次补 `key_facts`/`scoring_points`
  256 条与关联 409 条。生产最终：条文 804 / 病案 256 / 有要点 256 / 关联 409，与本地一致；
  id 完全对齐（3–258），按 id 直接更新，传输走 gzip + ssh，临时文件两端已清。
- **涉及文件**：`tools/import_classics.py`、`tools/generate_scoring.py`、
  `tools/build_relations.py`（均新增）、`backend/app/services/matcher.py`（繁简与病名匹配）

**评分要点全量生成、金匮条文补全与双向同步（2026-11-24）**

- **评分要点**：`tools/generate_scoring.py` 逐条拆 `correct_answer`，为 256 个病案生成
  `key_facts` + `scoring_points`（参照 #12 的结构）。**256/256 全部完成**，仅 #165 在重试时
  被判不合格（此前已生成，不影响覆盖）。
  - 权重按「阶段总和」归一：辨病 25 / 平脉 15 / 析证 40 / 定治 20，避免模型把「每阶段 40」
    理解成「每条 40」（首版合计 160）。
  - `key_facts` 不列舌脉（那些靠切诊）、`must_ask` 限制在一半左右（否则完整度分母虚高）、
    过滤「哪里不舒服」这类泛关键词。
- **金匮条文补全**：从 `D:\文档表格\金匮条文库` 的 20 篇 docx 解析，切出 348 条正文
  （丢弃 21 段方剂/附方），金匮条文 **58 → 406**，总条文 456 → 804。工具
  `tools/import_classics.py`，复用项目解析器（句末条号收束）+ 清理规则。
- **方剂词表**：`FORMULA_KEYWORDS` 20 → **317**（从 256 个病案的处方与参考答案提取）。
  此前「小建中汤」识别不出来，导致用药安全复盘误报「未识别出明确方剂」。
- **时间 bug**：`started_at` 由 DB 默认值写入（UTC），`ended_at` 由 `datetime.now()` 写入（本地），
  相差 8 小时。models 里 11 处 `server_default=func.now()` 改为 `default=datetime.now`，
  历史数据按「结束早于开始 7 小时以上」识别并 +8（本地 11 条、生产 19 条）。
- **病案 id 对齐**：本地曾多出 #13（与 #12 重复的原文版）和一条同名「脏躁」，导致两边 id 错位。
  删除这两条并把后续 id 前移，现本地与生产 256 条完全对应（抽查 5 个 id 一致）。
- **匹配器改进**：`matcher.py` 加繁简归一（`zhconv`）与「病名命中」加权——条文是繁体
  「栝樓薤白白酒湯」、病案是简体「栝楼薤白白酒汤」，字面永远对不上。胸痹病案已能匹配到
  正确条文，痰饮/少阳仍有偏差。
- **双向同步**：生产条文 456 → 804、要点 1 → 256；反向拉回生产独有的 19 条会话
  （id 25–43）+ 159 条消息。**现在两边完全一致：804 条文 / 256 病案 / 42 会话 / 256 有要点**。

**舌脉提取、决策路径真实化与问诊完整度计分（2026-11-25）**

- **舌脉提取**：新增 `tools/extract_examinations.py`，从每个病案的 `symptoms + content`
  正则提取舌象与脉象，写入 `examinations`。256 条里 **244 条提取成功**（93%），
  12 条原文本身没写。此前只有 #12 有体征，学生号脉一律得到「本例未记录」，
  等于系统缺数据却让学生扣分（会话 41 的「平脉分析度 0 分」就是这么来的）。
  - 细节：`symptoms` 与 `content` 常各写一遍，会出现「舌淡红苔白腻 / 舌淡红 / 苔白腻」，
    按「被其他片段包含则丢弃」去重，只留最完整的一条。
- **`decision_path` 按实际进度**：原来硬编码 `路径：辨病 → 平脉 → 析证 → 定治`，
  不管做没做完都这么写。现在结算时重算进度，输出
  `辨病[✓] → 平脉[✓] → 析证[未完成：缺…]`，未完成阶段附一句「缺什么」（取自未命中的评分要点）。
- **问诊完整度计分**：综合分改为 `要点分 × 0.85 + 问诊完整度 × 0.15`，
  完整度 = (学生主动问到 + 患者主动交代) / 必问项。此前只看四个结论，
  学生认真问十几轮但一个要点没答对仍是低分，问诊过程完全不计。
- **关键词表扩充**（验证时暴露的连带问题）：扩完 `decision_path` 后发现学生明明说了
  「辨为胃脘痛…半表半里虚寒…方用乌梅丸」，四阶段却全标未完成——词表太窄。
  扩充后：病名 32 → 69（补胃脘痛、泄泻、眩晕、痉病等现代病名）、
  病机 32 → 62（补虚寒、寒热错杂、半表半里、上热下寒等）、
  治法 26 → 56（补温脏、安蛔、寒热并调等）。补齐后同一段话四阶段正常点亮。
- **验证**（病案 #235 实机）：
  - 号脉 → 「（患者伸出手腕，你搭上寸口）脉沉弦细」；看舌 → 「苔白腻」；
  - `decision_path` → `辨病[✓] → 平脉[✓] → 析证[✓] → 定治[✓]`；
  - 综合分 73.8 = 要点 75 × 0.85 + 完整度 67% × 0.15；评价报告含「问诊完整度 2/3」。
- **数据同步**：244 条体征已写入生产库。代码改动（decision_path / 完整度 / 词表）
  按双线策略走另一个发布流程，不在本次同步范围。

**网站公告功能（2026-11-25）**

- **需求**：只给学生看、手动开关上下线、一档普通、带已读（关掉就不再弹）。
  不做定时生效与分级——公告数量少时那些字段只是增加操作负担。
- **数据**：新增 `announcements` 表（title / content / is_active / 时间戳），迁移 `e5f72a9c3d81`。
- **接口**（`routers/announcements.py`）：
  - `GET /api/announcements/` 公开，只返回 `is_active` 的，最新在前；
  - `GET /api/announcements/admin/` 管理员看全部（含停用）；
  - `POST` / `PUT` / `DELETE` 管理员。
- **前端三处**：
  1. 首页横幅——**注意 `/user` 实际返回的是 `newcase.html`，不是 `user.html`**，
     公告加在 newcase.html（深色主题里用金色左边框卡片），多条时显示前 2 条；
  2. 训练页 `train.html` 顶部一行提示，进训练前就能看到；
  3. 管理端新增「网站公告」面板：发布 / 编辑 / 启用停用 / 删除。
- **已读**：关闭时把 id 记进 `localStorage.ann_read`，同一条不再自动出现；
  管理员改内容不会重置已读（按 id 记录）。
- **验证**：新增 11 个用例（公开只返回启用的、未认证 401、管理员 CRUD、停用后前台不可见），
  全量 `291 passed`；三个页面均 200，`node --check` 通过。

**训练反馈与判定加固（2026-11-25 下午）**

- **会话结束逻辑按难度分开**：此前所有难度都要求「四阶段全部完成」，初级永远达不到，
  只能靠 50 轮上限硬撑——这是生产 42 条会话里 22 条挂在 active 的主因。
  现在初级答出辨病即结束、中级到析证、高级才走满四阶段；轮数上限 15/30/50。
  同时修了一个隐藏 bug：判定用的 `history` 是给模型的上下文窗口（`limit=20`），
  最多 20 条，中级 30、高级 50 的上限永远触发不了，改为查真实消息数。
  `active` 超过 24 小时无新消息的会话由列表接口惰性标记为 `abandoned`。
- **三次答错强制结束**：新增 `training_sessions.wrong_diagnosis_count`
  （迁移 `f4a1b2c3d4e5`）。辨病连错 3 次结束会话，说对清零；
  提示条实时显示「已错 N 次，再错 M 次将结束」。
- **辨病判定从「说了病名」收紧到「说对病名」**：此前只要含**任意**病名声就判定完成，
  说错也算。现在比对病案标题里的病名，说错则给出【纠正】提示而不算完成。
  `DISEASE_KEYWORDS` 由 69 个补到 **192 个**（从 256 个病案标题提取，排除纯证型），
  此前连「痹病」都不在表里。
- **笼统病类会被指出来**：「情志病」「心病」这类不是中医诊断，提示要求学生给出具体病名。
- **患者对病名的反应**：学生说对后，患者此前会回「我不太懂，您说说我是啥毛病」——
  三层原因叠加：① 有一道「防止患者给教学评价」的过滤器把确认替换成了隐晦回应；
  ② system prompt 里写的确认指令模型不执行；③ 确认后面常跟一句反问。
  现在过滤器放行「辨病成立时的确认」，并加代码兜底：整段对话没确认过就补一句
  「（患者连连点头）对对，就是您说的这毛病！」，同时过滤掉「不太懂/X 是啥毛病」式反问。
- **开场先讲清要求**：患者第一条消息带一句难度说明（初级只要病名、不必辨证型；
  中级辨病→号脉→析证；高级加定治）。此前学生不知道初级不用开方，直接跳到方药。
- **揭晓按难度裁剪**：初级只给【辨病】，中级给到析证，高级才给完整方案；
  初级/中级也不再出现「治疗方案未形成」（本来就不要求定治）。
- **换难度重练**：`SessionStartResponse` 增加 `case_id`；评价弹窗给出
  「重来（当前难度）/ 挑战另两档 / 返回首页」，都用同一病案。
- **缺脉舌的病案**：切诊回复由「（本例未记录脉象结果）」改为
  「（本例病案没有提供脉象，可以继续问诊，靠症状与病史辨证）」，开场上下文也提示患者"没查过"。
- **数据修正**：#220 辨病要点由「前阴抽痛、胃脘痛，病属筋脉失养之证」改为「前阴抽痛（筋脉失养）」；
  #66 标题由「下焦湿热证」（证型当病名）改为「淋证——下焦湿热证」。
- **踩坑**：Windows 下 `kill`/`taskkill`/`Stop-Process` 都杀不掉 DSH 后台 job 启动的 uvicorn，
  会留下占着端口、`Get-Process` 又查不到的幽灵进程，导致改了代码「不生效」。
  正确做法是用 `job_kill` 停 job，再用 `run_in_background` 重新起；
  `nohup ... &` 起的进程脱离 job 管理后同样杀不掉，别用。
  另：`_trim_answer` 初次上线时漏了 `import re`，直接让 evaluate 接口 500、前端揭晓空白。

**三阶梯落地：同一医案分层训练（2026-11-25 凌晨）**

- **原来错在哪**：`difficulty_level` 同时承担「病案复杂度」和「训练深度」两个含义，
  结果成了三档题库——学生只在初级和高级之间跳，中级 42 条会话里只占 2 条。
- **改造**：把两个概念拆开。病案复杂度决定抽到哪道题，训练深度决定这次要走到哪一步。
  三层要点按**阶段硬映射**生成（不靠模型判断）：
  `辨病 → 初级`、`平脉/析证 → 中级`、`定治 → 高级`。
  评分器本来就是按学生难度过滤 `min_level`，架构没动，只是把数据配对。
- **生成**：`tools/generate_scoring.py` 重跑 256 条，每案都有三层（初级 267 / 中级 595 / 高级 298 条要点）。
  失败阈值从「至少 4 条」降到 3（不少病案的答案只够拆 3 条）。
- **验收**（`同案三练`，都做病案 #12）：同一段发言，初级 1 条要点/满分 25/只判定病；
  中级 3 条/满分 80/判到析证；高级 4 条/满分 100/判到定治。四项判定全通过。
  注意：`平脉` 靠「号一下脉」这个动作点亮，不是靠陈述"脉弦"——这是既有设计（诊法识别认动词）。
- **生产同步**：256 条要点覆盖写入，#12 层级已是 初级/中级/中级/高级。
- **顺带发现**：42 条生产会话里 12 条是 0 轮（点进来就走），22 条停在 active；
  `examinations` 缺 12 条，学生号脉看舌会撞到「本例未记录」。
- **涉及文件**：`tools/generate_scoring.py`、`backend/static/train.html`

**访问量统计模块（2026-11-25）**

- **需求**：做成与「条文管理」同级的独立模块，而不是一个小卡片。
- **数据**：`page_visits` 表（path / client_ip / created_at），迁移 `f6a82b1d3e94`
  （接在另一个对话的 `f4a1b2c3d4e5` 之后，链条已线性化）。
- **采集**：`main.py` 中间件，只记 `/user`、`/train`、`/study` 三个页面的 GET 200 请求，
  API 与静态资源不计——否则轮询接口会把数字撑爆。统计失败不影响页面返回。
- **接口**（`routers/stats.py`）：
  - `GET /api/stats/visits` 概览（今日/昨日/7 天/累计 + 分页面 + 逐日）；
  - `GET /api/stats/visits/summary` 面板顶部聚合，支持 `days`；
  - `GET /api/stats/visits/list` 明细分页（`skip/limit/path/days`），总数走 `X-Total-Count` 头。
- **前端**：管理端新增「访问统计」标签页——四张统计卡、天数与页面筛选、逐日柱状趋势、
  页面分布、明细表（20 条/页，上下页）。样式全部复用既有 `.stats`/`.stat-card`/`.filter`/`.pager`，
  无表情符号。
- **验证**：全量 `294 passed`；本地与生产接口实测通过（今日/分页面/明细分页正确）。
- **遗留**：本机 `127.0.0.1:8000` 被一个查不到的旧监听占用（PID 95048，taskkill 报 not found），
  浏览器需用 `10.112.24.113:8000`，重启电脑后恢复。

### 2026-11-09 会话记录

**诊法直出（结构化改造第一步）**

- **问题**：学生说「让我号脉」时，患者模型可能回「好，你号吧」、也可能含糊说「脉有点弦」，甚至完全漏给。
  脉象、舌象是**客观体征**，不该由患者即兴叙述；而且每次检查都要消耗一次 LLM 调用（本环境单次数十秒）。
- **设计**：把「问出来的信息」与「查出来的体征」分开。病案新增 `examinations` 字段，
  检查请求由系统直接返回体征，不经过患者模型。
- **实现**：
  1. 新增 `services/examination.py`：识别脉/舌/腹/面/咽五类检查，渲染「动作 + 客观结果」格式回复；
  2. `MedicalCase.examinations`（JSON）与 `TrainingSession.examinations_done`（JSON）经 Alembic 迁移
     `b7c41f2d9e05` 加入；**公开病案接口不下发体征**，学生只能通过训练取得；
  3. `process_message` 在调用 LLM 之前先判诊法，命中即直出并提前返回（不走模型、不做 AI 进度复核）；
  4. 重复检查提示「已获取，无需重复」；病案未记录的检查项明确提示「本例未记录」；
  5. 体征消息不带 `message_type`，前端不显示「提问」标签。
- **顺带修正**：`_analyze_progress` 改为只统计学生消息——患者直出的体征不再被算作学生的辨证
  （P2-8 的一半；学生仍可在单句内点亮多个阶段，语义判定未做）。
- **效果**：检查响应从数十秒降到 **0.84 秒**，且不消耗 token。
- **实机验证**（病案 #12，会话 11）：首次号脉 →「（患者伸出手腕，你搭上寸口）脉弦缓」0.84s；
  首次看舌 →「（患者伸出舌头）舌苔薄白」0.84s；重复号脉 →「（脉象已获取：脉弦缓，无需重复检查）」；
  未记录项（腹诊）→「（本例未记录腹诊结果）」。
- **测试**：新增 6 个用例（不调用 LLM、重复拒绝、未记录提示、体征不计入辨证、检查写入会话），
  全套 `199 passed`。
- **涉及文件**：`app/services/examination.py`（新增）、`app/models.py`、`app/schemas.py`、
  `app/services/agent_service.py`、`alembic/versions/b7c41f2d9e05_add_examinations.py`（新增）、
  `tests/test_services.py`

### 2026-11-07 会话记录

**P2-3 列表分页（响应头携带总数）**

- **背景**：8 个列表端点只有 `skip`/`limit`，不返回总数，前端只能把 `limit` 调到上限一次拉满
  （条文表 `?limit=2000`），数据量增长后不可持续，也无法做页码。
- **方案取舍**：采用**响应头** `X-Total-Count` / `X-Skip` / `X-Limit`，响应体仍是数组。
  不改成 `{items,total}` 包装，是因为那要同时改动全部端点、前端调用点与测试断言，收益相同而风险高得多。
- **后端**：新增 `app/pagination.py`（`paginate(query, skip, limit, response)`），
  接入 7 个列表端点（texts / cases 公开 / cases 管理端 / sessions / documents / feedback / analysis history）；
  CORS 增加 `expose_headers`，使跨域部署时 JS 也能读到计数头。
- **配套改动**（否则分页后筛选、排序、统计都会失真）：
  1. `cases` 两个列表端点新增 `difficulty_level` 筛选（原先前端在本页内过滤，分页后会漏数据）；
  2. `texts` 新增 `sort_order` 参数，排序字段扩展为 id / source_book / chapter / article_number + 方向；
  3. 新增 `GET /api/agent/session-summary`（需管理员），一次性返回总数 / 进行中 / 已完成 / 平均分——
     分页后前端只拿到一页，无法再自行统计这四项。
- **前端**（`static/index.html`）：三张主表加入翻页条（训练 20/页、病案 20/页、条文 50/页）；
  筛选与刷新回到第一页；条文排序改为传后端并重置页码；四个统计卡改用汇总接口。
- **顺带修复**：统计卡"总训练次数"此前取的是 `data.length`（本次拉回的条数），
  超过一页后会永远显示上限值，现改为真实总数。
- **验证**：新增 5 个分页用例（全套 `188 passed`）；`index.html` 的 JS 经 `node --check` 通过；
  临时 TestClient 探针 9 项全过（计数头、翻页窗口、升降序、难度筛选、汇总与未认证 401）。
- **未做**：`study.html` 的按病证分组仍拉全量，正确做法是改按篇章接口逐章加载，
  这属于独立优化，不在 P2-3 范围内。
- **涉及文件**：`app/pagination.py`（新增）、`app/routers/texts.py`、`app/routers/cases.py`、
  `app/routers/agent.py`、`app/main.py`、`static/index.html`、`tests/test_api_admin.py`、
  `README.md`、`CHANGELOG.md`

**P2-7 学员身份与会话恢复**

- **背景**：`student_id` 由前端临时生成 `'student_' + Date.now()`，每次训练都是新身份、无法归档；
  `sessionId` 只存在内存里，刷新页面就丢掉整轮训练；教师端按学号筛选因此没有意义。
- **后端**：
  1. `SessionStartRequest.student_id` 增加 `max_length=32`；
  2. 新增 `dependencies.verify_admin_optional`——不强制认证，只判定"是否管理员"；
  3. `GET /api/agent/session/{id}` 从"仅管理员"改为**管理员或持有效 `X-Session-Token`** 均可读，
     该令牌同时作为刷新后恢复训练的凭据。
- **前端**（`static/train.html`）：侧栏新增"学员"输入（学号/姓名，留空则以 `anonymous` 训练），
  填入后写入 `localStorage`；会话信息（id / token / 难度 / 学号）存入 `localStorage`，
  开始训练时写入、评价完成或重开时清除；页面加载时向服务端校验未完成会话，
  若仍为 `active` 则显示"继续上次训练"，可一键拉回历史消息接着问诊。
- **未改数据库**：`student_id` 字段早已存在，无迁移。
- **测试**：新增 5 个用例（令牌持有者可读、无凭据 401、他人令牌 401、管理员仍可读、学号超长 422），
  全套 `193 passed`。
- **行为变更**：`GET /session/{id}` 不再是"仅管理员"——学生凭令牌可读自己的会话记录。
- **涉及文件**：`app/dependencies.py`、`app/routers/agent.py`、`app/schemas.py`、
  `static/train.html`、`tests/test_api_agent.py`

### 2026-11-06 会话记录

**AI 接入切换、路由同步化与备份工具集**

- **AI 平台切换**：由 DeepSeek 官方改为某高校自建 MaaS（GPUStack，`https://maas.example.edu.cn/v1`），主模型 `example-model`；
  `.env` 中 `OPENAI_BASE_URL` / `AI_MODEL` 已更新，密钥不入库。
- **备选模型可配置**：`ai_service.py` 改为优先读取 `AI_FALLBACK_MODELS`（逗号分隔），未配置时才回退旧网关的 DeepSeek 系列；
  `analysis.py` 的 `/status` 增加 MaaS provider 识别。
- **路由同步化（并发相关）**：`agent.py`（start / message / evaluate）、`analysis.py`（models / query）、`texts.py`（verify 三个端点）
  共 8 个端点由 `async def` 改为 `def`。这些处理函数内部全是同步阻塞调用（SQLAlchemy + OpenAI SDK），
  写成 `async def` 会占住事件循环、串行化所有请求；改为同步函数后由 FastAPI 自动放入线程池并发执行。
- **备份工具集**：新增 `tools/`：
  - `backup_local.py` — 本机每日备份，保留 90 份，产物 `backups/local/`
  - `sync_server.py` — 从生产服务器拉取（recent 保留 14 份 / daily 保留 180 天），产物 `backups/server/`
  - `backup_now.sh` — 服务器端一致性快照，由 `sync_server.py` 经 ssh 调用
  - `db_tool.py` — SQLite 备份 / 校验 / 恢复辅助
  全部走 SQLite Online Backup API，并在入库前做 `integrity_check`；`tools/README.md` 写明恢复步骤与注意事项。
- **MaaS 体检脚本**：新增 `maas_check.py`，只读探针 —— 列出可用模型、最小非流式对话、流式支持、限流复核；密钥从环境变量读取。
- **数据**：`backend/data/tcm.db` 条文由 0 增长到 152 条，现有 9 例病案 / 5 会话 / 43 消息 / 50 条学习记录 / 3 个上传文档。
- **提交历史**：重写后移除了历史提交中的本地文档草稿（提交树已无残留），commit hash 全部变更并已强制同步到远端；commit message 未改动。
- **测试**：改动后全套 `183 passed`，未出现回归。
- **新增待办**：`AI_FALLBACK_MODELS` 为空时，`ai_service` 会回退到 DeepSeek 的模型名，
  而 MaaS 平台只有 `example-model` 等模型；主模型失败时会依次尝试不存在的模型，既拖慢响应又掩盖真实错误（见 P2-10）。
- **涉及文件**：`app/routers/agent.py`、`app/routers/analysis.py`、`app/routers/texts.py`、`app/services/ai_service.py`、
  `tools/`（新增）、`maas_check.py`（新增）、`.gitignore`

**A 档修复（同日）**

- **P2-10 备选模型**：`ai_service` 不再在 `AI_FALLBACK_MODELS` 为空时回退到内置的 DeepSeek 模型名，改为只尝试显式列出的模型；`.env` 中备用模型已设为 `deepseek-chat`（MaaS 平台当前只开放 `example-model`，故该备用暂不会触发，平台开放后无需改代码即生效）。
- **P1-9 数据库入库问题**：`backend/data/tcm.db` 已 `git rm --cached` 移出版本控制，`.gitignore` 不再为其保留例外；文件仍在磁盘，数据不受影响，备份交给 `tools/backup_local.py`。首次启动由 Alembic 建空库，需跑 `seed_texts.py` / `seed_cases.py` 才有条文。
- **审计 B6 三项**：
  1. `should_end_session` 此前只用到 `history` 一个参数，现接入进度判断——四阶段全部完成即结束，不再一律等到 50 轮；`level` 保留给按难度分档上限（当前各档统一）。
  2. 初级档提示词里的"主证识别"此前原样传入辨病状态，两个进度永远同值；改为按 `current_stage` 判定。
  3. `SimpleRateLimiter` 改为普通 dict 并每 1000 次请求回收一次长期不活跃的 key，避免 key 只增不减带来的内存缓慢增长。
- **验证**：改动后全套 `183 passed`。
- **涉及文件**：`app/services/ai_service.py`、`app/services/progress.py`、`app/services/agent_service.py`、`app/dependencies.py`、`backend/.env`（未入库）、`.gitignore`、`README.md`、`CHANGELOG.md`

### 2026-10-21 会话记录（晚）

**测试精简与流程隔离**

- **背景**：13 个测试文件、全套 552.91 秒、16 个用例长期 skip、跑测试会改动 `backend/uploads/` 与 `backend/data/tcm.db`。
- **文件合并（13 → 6 + conftest）**：
  - `test_services.py` ← 原 pure_functions / progress / jailbreak / treatment_safety / analysis_output_format
  - `test_api_admin.py` ← 原 cases / texts / documents
  - `test_api_agent.py` ← 原 api_routes 的会话部分 + agent_message_flow
  - `test_api_misc.py` ← 原 analysis + 页面 / 公开统计 / 错误处理 / 反馈
  - `test_security.py` ← 原 security_fixes
  - `test_parser.py` ← 原 parser_regression（重写，见下）
- **解析器回归真正生效**：原用例依赖 `backend/uploads/伤寒论原文398条整理.docx`，而该目录被 `.gitignore` 排除，本地与 CI 全部 skip。现改为运行期用 python-docx 生成覆盖各类边界的样本（章标题切换、行首罗马数字、中文数字条号、异体字 `並→并`、重复条号、source_book 推断、短文档回退），**skip 归零**。
- **速度**：`552.91s / 195 passed / 16 skipped` → **`3.78s / 183 passed / 0 skipped`**。
- **隔离**：`conftest.py` 将 `DATA_DIR` 指向进程级临时目录，数据库与上传目录都不再落在仓库；启动期迁移与上传后台解析在测试中打桩。
- **根因修复（552 秒的真正来源）**：`analysis.py` 有三处 `load_dotenv(..., override=True)`，会在请求期把 `.env` 里的真实密钥写回 `os.environ`，使后续测试与请求真实调用 LLM。已删除这三处重复加载与手工 `.env` 解析（配置统一在应用启动时一次加载，`override=False`）；同时给 `/api/analysis/status`、`/api/analysis/models` 加上管理员认证——provider 名称与模型列表属于基础设施信息，不应公开。
- **其他**：`.gitignore` 补 `.codex_tmp/`、`output/`；清理 `backend/uploads/` 下 18 个测试残留文件。
- **用例数取舍**：195 → 183。少掉的是"每个端点各写一条 401 断言"这类重复用例，改为同一次请求内的多断言；语义覆盖未减少。
- **涉及文件**：`backend/tests/` 全部重构、`app/routers/analysis.py`、`.gitignore`、`PROJECT_MEMORY.md`、`README.md`

### 2026-10-21 会话记录（下午）

**第一批 P0 修复落地（安全与正确性 7 项）**

- **P0-6 健康检查**：`main.py` 新增 `/live`（存活，恒 200）与 `/ready`（就绪，DB 异常 503）；`/health` 保留为 `/ready` 的兼容别名，改用 `JSONResponse` 指定状态码。修复前 `return {...}, status` 被 FastAPI 编码成 `[body, 200]`，状态码恒 200，导致部署验收失真。
- **P0-5 答案裁剪**：`schemas.py` 新增 `MedicalCasePublicResponse`（仅 id/title/content/symptoms/difficulty_level）；`routers/cases.py` 的 `GET /`、`GET /{id}` 改用公开视图，新增 `GET /admin/`、`GET /admin/{id}`（`verify_admin`）返回完整字段；`static/index.html` 病案管理改调 admin 端点。
- **P0-7 会话归属**：新增 `services/session_token.py`（无状态 HMAC 派生，不落库、无需迁移）。`start_session` 返回 `session_token`；`/message`、`/evaluate` 通过 `X-Session-Token` 头校验，缺失或错误返回 403；`GET /session/{id}` 加管理员认证。`train.html` 保存并回传令牌。
- **P0-8 上传文件名**：`documents.py` 落盘名改为 `时间戳_UUID8.扩展名`，原始名只用于展示；新增 `ALLOWED_EXTENSIONS` 白名单，非白名单扩展名直接 400。
- **P0-9 存储型 XSS**：`index.html` 训练记录表与会话详情改用白名单 + `escHtml` + `textContent`（原三处直接拼接 `student_id` / `case_title` / 消息内容）；反馈面板补转义 `category`；`FeedbackCreate.category` 改为 `Literal` 枚举收口。
- **P0-10 网络与凭据基线**：`dependencies.get_admin_password()` 取消内置默认口令，未配置 `ADMIN_PASSWORD` 时任何密码都不通过（`documents.py` 两处同步）；CORS 改为默认不放行任何来源、按 `CORS_ORIGINS` 显式配置；`DISABLE_DOCS=1` 可关闭 `/docs`、`/redoc`、`/openapi.json`；`conftest.py` 为测试环境 `setdefault` 管理员密码。
- **P1-7 校验器 logger**：`text_verifier.py` 补 `logger = get_logger(__name__)`；`TextVerifyResponse` 补 `expected_section`、`fixed` 两个被 response_model 静默丢弃的字段。
- **测试**：新增 `tests/test_security_fixes.py`（19 个用例，覆盖上述每一项：探针状态码与返回体形态、公开接口字段裁剪、会话令牌 403、路径穿越、扩展名白名单、logger 降级、反馈枚举）；`test_api_routes.py` 三处用例适配令牌与管理员认证。
- **行为变更提示**：① 未设置 `ADMIN_PASSWORD` 的部署将无法登录管理端（这是刻意的，需在 `.env` 配置）；② 部署后正在进行中的旧会话因缺令牌会 403，需重新开始训练；③ 前端病案管理改用 `/api/cases/admin/`，与后端需同版本发布。
- **涉及文件**：`main.py`、`dependencies.py`、`schemas.py`、`routers/cases.py`、`routers/agent.py`、`routers/documents.py`、`services/text_verifier.py`、`services/session_token.py`（新增）、`static/index.html`、`static/train.html`、`tests/conftest.py`、`tests/test_api_routes.py`、`tests/test_security_fixes.py`（新增）

### 2026-10-21 会话记录

**全项目审计（未改代码，仅记录）**

- **方法**：通读后端 10 个模块 + 7 个 router + 12 个测试文件 + 6 个前端页面 + 部署链路；实跑 `pytest`；用临时 TestClient 探针实测可疑端点（探针脚本已删除）。
- **测试现状**：`176 passed, 16 skipped, 417.34s`（本机带真实 API Key 时的耗时；其中 `test_analysis.py` 会直连真实 LLM）。
- **确认缺陷**（详细条目见下方 `### 2026-10-21 审计新增项`）：
  1. **答案泄漏**：`GET /api/cases/` 未认证即返回 `correct_answer` / `teaching_points` / `diagnosis` / `prescription`（已实测返回原文）；`POST /api/agent/session/{id}/evaluate` 无归属校验且返回 `case_correct_answer`，枚举自增 id 即可逐个取答案。
  2. **`/health` 状态码失效**：`main.py` 用 `return {...}, http_status`，FastAPI 不支持元组返回，实测得到 `200` + `[{"status":"ok",...},200]`。后果：`server_deploy.sh` 的 `curl -fsS /health` 只对 4xx/5xx 失败，数据库异常时部署仍报成功。
  3. **`text_verifier.py` 未定义 `logger`**：`classify_text` 的异常分支会抛 `NameError` 冒到路由变 500，并丢失原始异常。
  4. **上传文件名未净化**：`documents.py` 直接用 `file.filename` 拼路径，可路径穿越写出上传目录。
  5. **管理端存储型 XSS**：`index.html` 会话详情用 `innerHTML` 拼接 `student_id` / `case_title` / 消息内容，学生输入会在教师后台以管理员上下文执行。
  6. **最关键的回归测试空转**：`test_parser_regression.py` 的 16 个 golden 用例依赖 `backend/uploads/*.docx`，而 `uploads/*` 被 `.gitignore` 排除——本地与 CI 均 100% skip，16 skipped 即来自此文件。
  7. **测试环境不隔离**：`test_analysis.py` 在有 Key 时真实调用 LLM（整套 417s）；`backend/uploads/` 残留 17 个 `*_test.txt`；`backend/data/tcm.db` 被 git 跟踪并因跑测试出现 `M`。
- **文档更正**（本次同步修正，原记录与代码不符）：P1-1 / P1-3 / P1-5 实际已完成；P1-2 / P1-4 / P2-1 / P2-2 / P3-2 实际为部分完成或已完成；"当前状态"中测试数 127 → 176。P0-1 虽标"已完成"，但只覆盖了**写**操作，读接口的答案暴露未处理（见 P0-5）。
- **涉及文件**：`PROJECT_MEMORY.md`

### 2026-08-06 会话记录

**Git 推送与服务器部署**

- **背景**：上次 `37cf73d` 提交（fix: repair legacy schema and clean runtime artifacts）未推送到 GitHub，服务器仍运行旧版本。
- **操作过程**：
  1. **Push 到 GitHub**：先取消失效的代理配置（`http://127.0.0.1:10808`），直连成功推送 `69bd172..37cf73d` 到 `origin/main`。
  2. **SSH 连接修复**：服务器 SSH 公钥丢失，重新配置时因公钥复制错误（`2dnq` → `2cnq`，一个字符之差）导致指纹不匹配，修正后连接成功。
  3. **部署执行**：由于 `deploy.sh` 的 `scp` 遇到 host key 验证路径问题（中文用户名），改用手动 `scp` + `ssh` 带 `StrictHostKeyChecking=no` 参数绕过，上传并执行 `server_deploy.sh`。
- **部署结果**：
  - 数据库备份：`/var/backups/jingui/tcm-20260806-153655-868050113.db`
  - 代码同步：`HEAD is now at 37cf73d`
  - 数据库迁移：`bb356c8cc735 → d32e4c7f91ab`，篇章元数据 35 条
  - 数据完整性验证通过（会话 11/消息 201/学习 55/病案 9/条文 762，前后一致）
  - 健康检查通过，服务运行正常
- **涉及文件**：无代码变更（仅运维操作）

**金匮要略第22/23章上传后按篇章浏览不显示**

- **现象**：上传 `22 妇人杂病脉证并治第二十二.docx`（23条）和 `23 杂疗方第二十三.docx`（16条）后，导入审核均显示 published，但 study 页面按篇章浏览看不到这两个章节。
- **根因分析**（三个 Bug）：
  1. **异体字 `並` 无法匹配**：文档标题为"妇人杂病脉证**並**治第二十二"，正则 `_JINGUI_CHAPTER_RE` 中 `[并治]*` 无法匹配异体字 `並`（→`并`），导致 `_is_chapter_header()` 返回 False，全部 23 条 `chapter = None`，按篇章浏览时被过滤。
  2. **`source_book` 误判为伤寒论**：`_detect_source_book()` 中宽泛的 `"伤寒"` 关键词先于金匮关键词检查，金匮文档正文提及"伤寒"（如第22章前4条为热入血室，多涉伤寒），直接命中返回《伤寒论》。
  3. **文件名信息未利用**：文件名本身包含明确的金匮章节特征（"XX病脉证并治第X"），但识别逻辑未优先检查文件名。
- **修复内容**：
  1. `_VARIANT_MAP` 新增 `並→并` 映射；`_is_chapter_header()` 匹配前调用 `_normalize_chapter()` 做异体字归一化。
  2. `_detect_source_book()` 重构优先级：文件名金匮特征 → "金匮/金匮要略"关键词 → 内容章节标题 → 伤寒论章节标题 → "伤寒论"关键词 → 返回空。
  3. 去除宽泛的 `"伤寒"` 关键词匹配，改为精确的 `"伤寒论"`；默认不再返回《伤寒论》。
- **数据修复**：服务器数据库直接 SQL 更新 Batch 20 的 `source_book` 和 `chapter`、Batch 21 的 `source_book`。
- **验证**：全量 160 测试通过无回归；服务器查询确认第22章（23条）、第23章（16条）已正确归属《金匮要略》。
- **提交**：`a3038ff` fix: 修复金匮要略文档误判为伤寒论及异体字章节识别失败
- **涉及文件**：`parser.py`、`PROJECT_MEMORY.md`

### 2026-08-05 会话记录

**修复文档上传解析失败（金匮要略单章无法解析）**

- 现象：上传《金匮要略》单章 DOCX（如 `04 疟病脉证并治第四.docx`），上传成功但后台解析失败（status=failed），提取到 0 条条文。
- 根因分析：三个 Bug 形成"双重夹击"：
  1. **Bug 3（主因）**：`extract_texts_and_cases()` 第 498 行硬编码阈值 `len(articles) >= 10`。`_split_by_sentence_end_number` 正确解析出 8 条，但不满足 `>=10` 条件，结果被丢弃。
  2. **Bug 1（次因）**：旧路径 `_extract_legacy()` 第 525 行正则 `r'[）)](\d+)[）)]'` 前后都是右括号，标准中文格式 `（1）`（左括号+数字+右括号）无法匹配。
  3. **Bug 2（次因）**：`_parse_pdf` 和 `_parse_excel` 不返回 `paragraphs` 字段，导致 PDF/Excel 文件被迫走有 Bug 的旧路径。
- 修复内容：
  1. 阈值 `>=10` → `>=3`：金匮要略单章通常 5-8 条，现可正常通过。
  2. 正则 `[）)]` → `[（(]`：第一个字符类改为左括号，匹配标准中文 `（数字）` 格式。
  3. `_parse_pdf` 和 `_parse_excel` 补充 `paragraphs` 字段，统一走新解析路径。
- 验证：疟病脉证并治第四.docx（8 条）解析成功，质检通过；全量 111 测试通过无回归。
- 涉及文件：`parser.py`、`PROJECT_MEMORY.md`

### 2026-08-04 会话记录

**新增用户反馈功能**

- **需求**：在 AI 对话界面（训练页）加入用户反馈入口，管理端加入反馈管理面板。
- **实现内容**：
  1. **数据模型**：新增 `feedbacks` 表，含 `session_id`（可选关联训练会话）、`category`（功能建议/bug反馈/使用体验/其他）、`content`、`contact`、`status`（pending/resolved/closed）、`admin_note`、时间戳。
  2. **API 端点**：新建 `routers/feedback.py`，4 个端点 — `POST /api/feedback/`（公开提交）、`GET /api/feedback/`（管理端列表，支持按类别/状态筛选）、`PUT /api/feedback/{id}`（更新状态+备注）、`DELETE /api/feedback/{id}`（删除）。
  3. **前端-训练页**：`train.html` 侧栏底部新增"💬 用户反馈"按钮，点击弹出反馈表单（类别选择、内容、联系方式），自动关联当前 sessonId。
  4. **前端-管理端**：`index.html` 新增"用户反馈"标签页，含类别/状态筛选表格，支持"处理"/"关闭"/"删除"操作。
  5. **部署脚本**：`server_deploy.sh` 的 FILES 数组新增 `feedback.py`，确保 Raw 降级同步不遗漏。
- **部署**：Commit `ab49977`，推送 GitHub → 服务器 Git pull + systemd 重启，数据完整性验证通过（14会话/204消息/54学习/9病案/456条文前后一致），服务正常运行。
- **涉及文件**：`models.py`、`schemas.py`、`routers/feedback.py`（新增）、`main.py`、`train.html`、`index.html`、`server_deploy.sh`、`PROJECT_MEMORY.md`

---

### 2026-08-03 会话记录

**条文导入系统全面重构**

- **问题**：原 `parser.py` 以"第X条"为边界，无法处理句末条号 `（9）` 格式和中文数字 `（一）` 格式，且罗马数字 `ⅠⅡⅢ` 被当作正文。
- **重构内容**：
  1. **`parser.py` 全新切分算法**：句末条号收束切分 `_split_by_sentence_end_number()`，缓冲区累积 + 同号合并（支持多段条文），支持阿拉伯数字和中文数字（一~十七），逐行清除罗马数字版式标记。
  2. **raw_content / content 双字段**：`raw_content` 保留原样（含罗马数字、条号标记），`content` 为规范展示正文。`ClassicText` 新增 7 个溯源字段（`raw_content`、`layout_marker`、`source_file`、`source_hash`、`source_offset`、`source_edition`、`import_batch_id`）。
  3. **质量闸门**：新增 `services/import_validator.py`，导入前校验 398 条号完整性，重复号（如 358）进"待人工裁决"清单，不静默跳过。
  4. **暂存→审核→发布流程**：新增 `ImportBatch` / `ImportStaging` 两张表，上传文档不再直接写入 `classic_texts`，而是经暂存区由管理端逐条批准后发布。`routers/import_review.py` 提供 10 个审核 API。
  5. **管理端导入审核面板**：新增 `📦 导入审核` 标签页，支持批次列表、质检报告查看、逐条批准/驳回/编辑/删除、一键发布、手动新增条文。
  6. **`server_deploy.sh` FILES 数组补全**：从 15 个文件扩展到 25 个，覆盖所有路由、服务、静态文件，Git 同步失败降级时不会漏文件。
  7. **金匮要略支持**：中文数字条号解析，`_detect_source_book` 通过篇章标题模式推断来源书，`publish_batch` 去重查询增加 `chapter` 字段避免不同章同号覆盖。
  8. **其他功能**：文档上传列表和审核界面增加删除功能；条文管理表格增加 Excel 式列头点击排序（ID/来源/章节/条号）；管理端移除 AI 分析标签（AI 解读已在 study.html）；修复 look-behind 正则报错；修复 `escHtml` → `escapeHtml` 拼写错误。

- **测试**：新增 `tests/test_parser_regression.py` 16 个 golden sample 测试（覆盖 398 条号、正文清洁度、已知样本、章节归属、重复检测、质检闸门），全量 127/127 通过。

- **涉及文件**：`parser.py`（重写）、`models.py`、`database.py`、`documents.py`（重写）、`import_validator.py`（新增）、`import_review.py`（新增）、`main.py`、`seed_texts.py`、`index.html`、`server_deploy.sh`、`SERVER_DEPLOY_GUIDE.md`、`test_parser_regression.py`（新增）、`backup_db.sh`（新增）、`PROJECT_MEMORY.md`

- **备份与运维**：本机配置了 SSH 密钥（ed25519），新增 `backup_db.sh` 一键备份脚本。日常备份命令：
  ```bash
  # 本地拉取服务器数据库
  scp root@YOUR_SERVER_IP:/var/lib/jingui/tcm.db D:\projects\Jin-Gui\backups\tcm-local.db
  # 或使用脚本（同时拉取上传文件）
  bash backup_db.sh
  ```

---

### 2026-08-01 会话记录

**文档上传失败可诊断与可重试**

- 已上传的文件与文档记录会保留；后台解析异常此前仅标记为 `failed`，没有持久化错误原因，导致无法从管理端排查。
- `documents.error_message` 通过启动时轻量迁移补齐；后台任务失败时保存异常摘要和处理时间，重新处理时清空旧错误。
- 管理端在失败文档旁显示错误详情并提供"重试"按钮；重试只允许失败记录、要求管理员认证、确认原始文件存在，不删除既有条文或重新上传文件。
- 对 2026-08-01 的《伤寒论》DOCX 的当前代码预检可通过；不过现有切分逻辑仅得到 134 段，须先完成 398 条的边界识别与底本校验后再批量重试该类条文文件。

**服务器故障恢复**

- 现象：阿里云 `YOUR_SERVER_IP` 无法访问，ping 通但端口 80/8000 拒绝连接。
- 根因：服务器上 `database.py` 为空文件（代码未同步），导致 `init_db` 导入失败，uvicorn 启动退出（status=1/FAILURE）。
- 修复：运行 `server_deploy.sh` → Git pull 同步最新代码 → 服务恢复正常。
- 数据完好：部署前后记录数一致（会话4/消息30/学习50/病案9/条文152）。

**修复文档上传功能**

- 根因：前端 `index.html` 中 `uploadFile()` 对 FormData 请求始终传入 `headers: {}`（空对象），阻止浏览器自动设置 `Content-Type: multipart/form-data; boundary=...` 和附加 `Authorization` 认证头，导致后端无法解析请求且返回 401。
- 修复：文件 ≤20MB 时不传 `headers` 参数；>20MB 时使用 `new Headers()` 对象仅设置 `X-Upload-Password`，让浏览器自动处理其他头。
- 提交：`97fdbcd` → 推送至 GitHub → 服务器 `server_deploy.sh` 同步。

**条文模块全面梳理**

- 数据结构：`classic_texts` 表的书→篇章→子篇→条文编号四级结构，辅以 `chapter_meta` 表存储标准篇章元数据。
- API 端点：11 个（公开 3 + 认证 8），支持 CRUD、篇章树、分布统计、互联网校验。
- 数据来源：seed_texts.py 批量导入 / 管理端手动录入 / 文档上传自动解析。
- 前端入口：`study.html`（按病证学习 / 按篇章浏览 / 全文搜索 三个视图）+ `index.html`（管理端表格 CRUD）。
- 互联网校验：`TextVerifier` 调用 LLM 逐条判断条文篇章归属和编号是否正确，支持自动修正。
- 当前数据：152 条《伤寒论》条文（10篇章分层），《金匮要略》25篇框架就绪待导入。

---

### 2026-07-31 会话记录

**修复公开页面意外弹出管理密码**

- 问题现象：用户进入公开首页 `/user` 时，浏览器有时会意外弹出管理端密码框；首页的条文和病案统计使用 `limit=1` 请求，显示的是返回数组长度，导致数量始终为 1；大于 20MB 的文件需要 `X-Upload-Password`，但管理端页面没有询问密码，也没有发送该请求头；上传接口返回 401 等错误时，前端可能把失败结果显示为"上传成功"。
- 根因：`/user` 加载时自动请求受保护的 `/api/agent/sessions`；管理 API 与管理端页面共用同一个 `HTTPBasic` challenge；API 返回的 `WWW-Authenticate: Basic` 会触发浏览器原生密码框；前端上传函数只发送 `FormData`，没有实现大文件密码交互，也没有先检查 HTTP 状态。
- 修改内容：
  1. **分离认证行为**：管理端页面 `/` 使用 `verify_admin_page`，保留浏览器 Basic 登录框；管理 API 使用 `verify_admin`，未认证时返回普通 JSON 401，不再发送 Basic challenge。
  2. **新增公开聚合统计**：新增 `GET /api/agent/public-stats`，只返回条文数、病案数、训练次数和平均分，不暴露学生或会话明细；`/user` 改用该接口，消除意外密码弹窗并修复统计数量错误。
  3. **完善上传交互**：保留管理端认证和超过 20MB 后再次验证同一密码的现有规则；前端在文件超过 20MB 时主动询问密码，并通过 `X-Upload-Password` 发送；后端优先使用上传文件的真实大小进行分级判断，避免 multipart 请求体开销影响阈值；前端检查 HTTP 状态并显示后端 `detail`，不再把上传失败误报为成功。
  4. **部署兼容**：将本次涉及的认证、路由、上传和前端文件加入 `server_deploy.sh` 的 GitHub Raw 降级同步清单。
- 验证结果：
  - 管理端 `/` 未认证：401，包含 `WWW-Authenticate: Basic`。
  - 管理 API 未认证：JSON 401，不包含 `WWW-Authenticate`。
  - 公开统计接口：无需认证并正确返回聚合数据。
  - Python 编译、Shell 语法和前端内联 JavaScript 语法检查通过。
  - 自动化测试由 108 项增加至 **111 项，全部通过**。
- 提交：`f7b1a88 fix: 避免公开页面触发管理密码弹窗`

**新增 Showcase 展示页**

- 背景：基于现有 4 个功能型页面，新增一个 Awwwards / FWA / CSSDA 水准的展示型页面，体现项目的设计品质和现代 Web 交互能力。
- 设计理念：**墨韵·金石** — 深炭黑底色 × 金铜点缀 × 朱砂红印章，将传统中医水墨美学转化为数字体验；浏览器即画布，跳出传统网页布局限制，采用破格排版、非对称网格、大面积留白和裁切式文字处理。
- 实现功能：
  1. **Canvas 水墨粒子背景**：60 个有机漂移粒子，模拟墨滴在水中扩散的痕迹效果。
  2. **弹簧物理文字动效**：Hero 标题"病脉证并治"逐字 `cubic-bezier(.1,.8,.3,1)` 入场。
  3. **实验性排版**：破格大字 `clamp(48px, 8vw, 110px)`，覆盖式 layering；Features 区块采用 `1.3fr 0.7fr 1fr` 三列非对称 broken grid；四阶训练阶梯横向卡片流。
  4. **互动细节**：`crosshair` 光标 + 200px 光环 Aura 跟随；磁吸元素收缩光环为 60px；CTA 按钮 hover 时背景滑入反转；滚动驱动 Intersection Observer 渐进揭示。
  5. **图标系统**：全站 Lucide 图标（`scroll-text`、`brain`、`database`、`bot`、`zap`、`sparkles`、`award` 等），零 Emoji。
  6. **数据接入**：实时从 `/api/agent/public-stats` 拉取训练记录和平均评分；其他统计数字采用 easeOutExpo 缓动计数动画。
- 路由：新增 `GET /showcase` → `static/showcase.html`
- 涉及文件：`backend/static/showcase.html`（新增，~930 行）、`backend/app/main.py`（新增 `/showcase` 路由）

---

### 2026-07-30 会话记录

**修复部署覆盖在线数据库**

- 现象：切换到新服务器后，在线训练记录只剩 GitHub 数据库快照中的 4 条历史会话。
- 根因：生产数据库位于 `backend/data/tcm.db`，同时被 Git 跟踪；`server_deploy.sh` 执行 `git reset --hard origin/main` 时会用仓库快照覆盖服务器运行库。
- 修复：
  - 生产数据库迁移到仓库外的 `/var/lib/jingui/tcm.db`。
  - systemd 通过 `DATA_DIR=/var/lib/jingui` 固定使用持久化目录。
  - 部署脚本在代码同步前使用 SQLite Online Backup API 创建一致性备份。
  - 首次运行安全部署脚本时自动把旧位置数据库迁移到持久化目录。
  - 首次迁移时短暂停止服务，避免复制过程中产生未迁移的新记录。
  - 部署完成后比较会话、消息、学习记录、病案和条文数量，发现减少则部署失败并提示恢复。
  - 本地 `deploy.sh` 改为上传并调用统一的服务器端安全部署脚本。
- 备份位置：`/var/backups/jingui/tcm-YYYYMMDD-HHMMSS.db`。
- 文档：重写 `SERVER_DEPLOY_GUIDE.md`，补充迁移、备份、恢复和运维检查流程。
- 安全：从版本化的 `jingui.service` 和 `PROJECT_MEMORY.md` 中移除明文凭据，改为服务器环境配置。
- 首次实际部署中 Uvicorn 启动超过原先固定等待的 2 秒，数据校验已通过但最后一次 `curl` 误报失败；已改为最长约 30 秒重试健康检查。
- Git 同步失败进入 Raw 降级路径时，同时更新仓库中的 `server_deploy.sh`、`jingui.service` 和部署指南，避免服务器保留旧版不安全脚本。
- 二次部署发现 `/api/texts/distribution` 受管理员认证保护，健康检查持续返回 401；服务实际为 active。健康检查已改为无需认证的 `/user` 页面。

---

### 2026-07-27 会话记录

**修复 AI 患者对正确诊断的识别反馈**

- 原问题：AI 面对学生正确诊断时仍然不理解/疑惑，因为提示词禁止任何确认 + 进度状态缺少行为指令
- 根因分析：
  - System Prompt 明确写死"绝对不做：不评价学生说得对不对"——学生说对了 AI 也装不知道
  - `{step1_status}` 等占位符只显示"已完成/未完成"标签，没有任何行为指令挂钩
  - 患者角色不能理解中医术语，无法用专业语言确认
- 改进内容：
  - `prompts_config.py`：
    - SAFETY_GUARD 新增"进度感知与行为变化"段落，为辨病/平脉/析证/定治四个阶段分别定义患者行为——"对，就这感觉"（初步信任）→ "终于有人懂我了"（完全配合）
    - 三份 System Prompt 将"绝对不做"改为"当医生说中你的感觉时：用患者日常语言自然确认身体感受"。确认仅限感受共鸣层面，绝不说"你诊断对了"这类教学评价语
  - `agent_service.py`：
    - `_build_system_prompt()` 末尾调用新方法 `_build_progress_hint()` 生成动态行为指令
    - `_build_progress_hint()` 根据后端识别的 `progress` 四阶段标志位拼接对应指令
- 测试：108 个测试全部通过，无回归
- 涉及文件：`app/services/prompts_config.py`、`app/services/agent_service.py`、`PROJECT_MEMORY.md`

**部署踩坑**

- 服务器 `wget` 无写权限，需加 `sudo`：`sudo wget -O /root/JinGui/... https://raw...`
- 已在 `SERVER_DEPLOY_GUIDE.md` 中标注

---

### 2026-07-25 会话记录

**修复全局异常处理器（422 被吞成 500）**
- `app/main.py` 中 `@app.exception_handler(Exception)` 宽泛捕获所有异常统一返回 500
- 修复：在处理器中增加 `isinstance(exc, RequestValidationError)` → 422 和 `isinstance(exc, HTTPException)` → 原状态码的判断
- 新增测试：`test_422_validation_error_not_500`（验证 Pydantic 必填字段缺失返回 422）和 `test_404_http_exception_not_masked_as_500`（验证路由 404 不被吞成 500）

**修复 conftest SQLite 线程池问题**
- `conftest.py` 中 `engine` 夹具使用默认 `SingletonThreadPool`，TestClient 异步请求与 create_all 在不同线程，导致不同的 `:memory:` 数据库实例
- 修复：改用 `StaticPool` 确保所有连接共享同一内存数据库
- 修改：`conftest.py` 新增 `from sqlalchemy.pool import StaticPool`，engine 创建增加 `poolclass=StaticPool`

**添加 pytest-cov 覆盖率报告**
- 新增 `backend/.coveragerc` 配置文件（source=app, 排除 tests/ 和种子脚本）
- 运行：`python -m pytest tests/ --cov --cov-report=term-missing`
- 当前覆盖率：总体 40%（models 100%, schemas 100%, agent_service 52%, main 72%）

**CI 集成（GitHub Actions）**
- 新增 `.github/workflows/test.yml`
- 触发：push/PR 到 main/master 分支
- 步骤：Checkout → Python 3.11 → 安装依赖 → pytest --cov → 上传 HTML 覆盖率报告

**修复 httpx 版本约束**
- `requirements.txt`：`httpx>=0.27.0` → `httpx>=0.26,<0.28`（防止 0.28+ 不兼容 starlette 0.27）

**P0 紧急修复**

**P0-1：API 路由认证保护**
- 创建 `app/dependencies.py` 共享认证模块（`verify_admin`、`SimpleRateLimiter`）
- 所有写操作端点（POST/PUT/DELETE）添加 `Depends(verify_admin)` 认证依赖
- 覆盖 texts（4个）、cases（4个）、documents（1个）、analysis（1个）、agent（2个）共 13 个端点
- `main.py` 中原有的 `verify_admin` 逻辑迁移至 `dependencies.py`，消除重复

**P0-2：请求频率限制**
- 自实现 `SimpleRateLimiter`（基于内存滑动窗口），无需外部依赖，避免 `slowapi` 在 Windows 的 GBK 编码问题
- 限制策略：agent-message 30次/分，agent-start/evaluate 10次/分，analysis-query 10次/分，upload 5次/时
- 以 `IP + 方法 + 路由（含 ID 聚合）` 为限流 key，429 响应含 `Retry-After` 头

**P0-3：文件上传大小限制 + 分级密码**
- ≤20MB：直接上传（需管理员认证 per P0-1）
- 20MB~200MB：需在请求头附加 `X-Upload-Password` 管理员密码
- >200MB：硬拒绝（HTTP 413）
- 流式分块写入时二次校验，防止 Content-Length 伪造绕过

**测试数量**：106 → 108（新增 2 个 API 错误处理测试）

**涉及文件**：`dependencies.py`（新增）、`main.py`、`texts.py`、`cases.py`、`analysis.py`、`agent.py`、`documents.py`

---

### 2026-07-24 会话记录

**补充核心测试体系**

- 目的：核心代码（越狱检测、文本清理、进度分析、API 路由）零测试覆盖，任何改动都可能引入回归
- 新增依赖：`pytest>=8.0.0`、`pytest-cov>=5.0.0`、`httpx>=0.26,<0.28`
- 新增文件：
  - `backend/tests/__init__.py` — 测试包初始化
  - `backend/tests/conftest.py` — 公共夹具（SQLite 内存引擎、TestClient、样本病案、agent 实例）
  - `backend/tests/test_jailbreak.py` — 越狱检测测试（16 硬越狱变体 + 10 正常输入 + 6 玩笑请求 + 拒绝语生成）
  - `backend/tests/test_pure_functions.py` — 纯函数测试（`_clean_text` 12 例、`_classify_response` 13 例、`_extract_decision_point` 6 例、`_detect_classic_context` 4 例、playful context 4 例、西医数据生成 3 例）
  - `backend/tests/test_progress.py` — 进度分析测试（初级/中级/高级三阶梯 + AI 辅助合并 + 会话自动结束边界 50/49 轮）
  - `backend/tests/test_api_routes.py` — API 层测试（session 创建/异常/404、页面可访问性、全局 404、管理端认证拦截）
- 测试结果：**106 个测试全部通过**（pytest 9.1.1，运行约 4 分钟）
- 测试策略：
  - 单元测试（agent 纯函数）：隔离测试，`agent` 夹具无 AI 客户端
  - 进度测试：`patch` 替换 `_ai_check_progress` 避免真实 AI 调用
  - API 测试：mock `get_agent` 隔离业务逻辑，mock `get_db` 控制数据层
- 踩坑记录：
  - `httpx>=0.28` 与 `starlette==0.27` 不兼容（`Client.__init__ no 'app' kwarg`），锁定 `httpx>=0.26,<0.28`
  - `TestClient` DB 依赖注入在 `@app.on_event("startup")` 的 `init_db()` 会将表建在文件数据库上，内存引擎需在 `client` 夹具中显式 `Base.metadata.create_all(bind=engine)`
  - `patch('app.routers.agent.get_db')` 对 FastAPI 依赖注入无效（依赖在路由注册时已绑定），改用 `app.dependency_overrides`
  - 全局异常处理器 `Exception` 宽泛捕获会把 `RequestValidationError(422)` 吞成 500，已于 2026-07-25 修复

---

### 2026-06-06 会话记录

**情绪分级细化**
- 原问题：AI 患者脾气太急，"医生"问两句就开始不耐烦
- 改进：大幅拉长情绪升级节奏，基础耐心从 2 轮拉到 5 轮，贴吧老哥模式从 9 轮推迟到 20 轮
- 新增"医生提问是否有进展"作为情绪判断条件——医生在逐步推进时永远保持配合
- 贴吧老哥模式精简掉太冲的台词，保留 5 条

**医学常识约束**
- 在 SAFETY_GUARD 新增"医学常识约束"段落
- AI 可以补充次要日常细节（如"这两天睡眠不好"），但不能编造病案中没有的核心症状
- 不能编造不符合医学常识的内容（风寒感冒血象正常、阴虚不会冷得发抖等）
- 学生让去检查时配合说"行那我去查"，不抗拒
- 检查结果用大白话转述

**评价附带原条文**
- `evaluate_session()` 返回值改为 dict，新增 `_get_related_texts()` 方法
- 利用已有 `TextCaseMatcher.find_related_texts()` 按症状/病机/方剂/关键词匹配 top 5 条文
- `SessionEvaluateResponse` 新增 `related_texts` 字段
- 前端评价弹窗新增"📖 相关经典条文"区域，展示出处+原文
- 修改涉及 5 个文件：`prompts_config.py`、`agent_service.py`、`schemas.py`、`agent.py`、`train.html`

---

### 2026-06-05 会话记录

**AI 拟人化完善**
- 越狱检测从一刀切改为两级：`_detect_hard_jailbreak()`（真正越狱拦截）+ `_detect_playful_request()`（玩笑请求标记不拦截）
- 新增6类玩笑请求检测：西医检查、西药、情绪发泄、身份质疑等
- 多样化拒绝语池：3条随机，不再机械重复同一句
- `_generate_western_test_context()`：根据病案症状动态生成血常规/心电图/CT/血压等西医数据
- `_build_playful_context()`：为不同玩笑请求注入场景化指令
- 提示词 SAFETY_GUARD 大改：6种语气风格（+迷糊型+戏精型）、输入内容感知、奇怪请求配合原则

**新增病案**
- 中级：黄疸茵陈蒿汤证 vs 栀子大黄汤证鉴别
- 高级：百合病非典型情志病合并证
- 病案总数 7 → 9，三难度各3例

**部署踩坑记录**
- 服务器无 Git 仓库，更新方式确认为 wget 拉取 GitHub Raw 文件
- 服务器 Python 命令为 `python3`，非 `python`
- 新增病例需手动运行 `python3 seed_cases.py` 写入数据库
- GitHub 出现 Cloudflare Pages 自动部署报错（`wrangler deploy`），不影响阿里云运行，需在 Cloudflare 端关闭
- 创建 `SERVER_DEPLOY_GUIDE.md` 记录标准部署流程
