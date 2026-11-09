# 金匮要略临床思辨训练系统

基于大语言模型的中医经典临床思辨训练平台。通过 AI 驱动的"虚拟患者"多轮交互，训练学生在辨病→平脉→析证→定治四阶段中的中医辨证思维。目前收录《伤寒论》与《金匮要略》全文，支持初级/中级/高级三档难度。

## 功能总览

| 模块 | 说明 |
|---|---|
| **条文管理** | 经典条文（书→篇章→条文三级结构）的增删改查，支持按来源、关键词、校验状态筛选 |
| **病案管理** | 临床教学病案的 CRUD，包含症状、诊断、方剂、难度等级、教学要点与参考答案 |
| **AI 分析** | 输入条文或症状，自动匹配相关病案，生成辨证分析 |
| **智能体训练** | 核心功能——学生扮演医生、AI 扮演人格化患者，完成辨病→平脉→析证→定治四步思辨 |
| **文档管理** | 上传 PDF/Word/Excel/TXT，自动解析并导入经典条文 |
| **导入审核** | 批量导入的条文进入暂存区，管理员人工质检后发布 |
| **互联网校验** | 对比互联网权威来源，校验条文编号与内容准确性 |
| **用户反馈** | 学生可提交功能建议/bug反馈，管理员跟踪处理 |

## 技术栈

- **后端框架**：FastAPI（Python 3.11+）
- **数据库**：SQLite + SQLAlchemy ORM + Alembic 迁移
- **AI 引擎**：兼容 OpenAI 接口协议（支持 DeepSeek / 阿里云 DashScope / 其他兼容服务）
- **文档解析**：pdfplumber / python-docx / openpyxl / pandas
- **前端**：纯 HTML/CSS/JS（`backend/static/`），渐进式多页面设计
- **测试**：pytest + pytest-cov + httpx
- **CI/CD**：GitHub Actions，自动运行测试
- **部署**：Render.com（PaaS）/ Alibaba Cloud ECS + systemd

## 项目结构

```
Jin-Gui/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 应用入口，路由注册，中间件
│   │   ├── models.py            # SQLAlchemy 数据库模型（14 张表）
│   │   ├── schemas.py           # Pydantic 请求/响应模型
│   │   ├── database.py          # 数据库连接与会话管理
│   │   ├── dependencies.py      # 认证、速率限制
│   │   ├── logger.py            # 结构化日志（JSON/可读双模式）
│   │   ├── routers/             # API 路由层
│   │   │   ├── texts.py         # 条文管理
│   │   │   ├── cases.py         # 病案管理
│   │   │   ├── analysis.py      # AI 分析
│   │   │   ├── agent.py         # 智能体训练
│   │   │   ├── documents.py     # 文档上传解析
│   │   │   ├── import_review.py # 导入审核
│   │   │   └── feedback.py      # 用户反馈
│   │   ├── services/            # 业务逻辑层
│   │   │   ├── agent_service.py # 训练智能体引擎
│   │   │   ├── prompts_config.py# AI 提示词配置（可直接编辑）
│   │   │   ├── safety.py        # 安全守卫 / 越狱检测
│   │   │   ├── western_data.py  # 西医检查数据生成
│   │   │   ├── progress.py      # 训练进度追踪
│   │   │   ├── parser.py        # 文档解析与条文提取
│   │   │   └── ai_service.py    # AI API 调用封装
│   │   └── utils/               # 工具函数
│   ├── tests/                   # 6 个测试文件 + conftest（183 个用例，全套约 4 秒，无 skip）
│   ├── static/                  # 前端页面（index/newcase/train/study/showcase/user）
│   ├── data/tcm.db              # SQLite 数据库
│   ├── requirements.txt
│   └── start.sh
├── alembic/                     # 数据库迁移脚本
│   └── versions/
├── .github/workflows/test.yml   # CI 测试流水线
├── render.yaml                  # Render.com 部署配置
├── deploy.sh                    # 一键部署脚本（上传到 ECS）
├── server_deploy.sh             # 服务器端部署脚本（备份→同步→重启→健康检查）
├── jingui.service               # systemd 服务单元文件
└── alembic.ini
```

## 快速开始

### 环境要求

- Python 3.11+
- Git

### 本地开发

```bash
# 1. 克隆仓库
git clone https://github.com/unicornpac/Jin-Gui.git
cd Jin-Gui

# 2. 创建虚拟环境
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env  # 如无示例文件，手动创建 .env 配置以下变量

# 必须配置：
# OPENAI_BASE_URL=https://api.deepseek.com
# OPENAI_API_KEY=your_api_key
# AI_MODEL=deepseek-chat
# ADMIN_PASSWORD=你的管理密码   # 未设置则管理端无法登录（无内置默认口令）

# 5. 启动服务
bash start.sh
# Windows:
cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 6. 导入种子数据（首次必做：数据库不在版本控制中，首次启动会创建空库，不导入则条文页为空）
python backend/seed_texts.py
python backend/seed_cases.py
```

访问 `http://localhost:8000/user` 进入用户端，`http://localhost:8000/docs` 查看 API 文档。

### 运行测试

```bash
cd backend
pytest tests/ -v          # 183 个用例，约 4 秒
pytest tests/ --cov=app   # 含覆盖率报告
```

测试有三条硬约定（见 `tests/conftest.py`）：

- **不碰真实数据**：`DATA_DIR` 指向进程级临时目录，不会写入 `backend/data/tcm.db` 或 `backend/uploads/`。
- **不发外部请求**：AI 环境变量默认置空，用例不会调用真实模型；需要验证“已配置”分支时用例内临时打开。
- **不依赖仓库外文件**：解析器回归测试在运行期即时生成 DOCX 样本。

## API 端点摘要

| 路径 | 方法 | 说明 |
|---|---|---|
| `/live` | GET | 存活探针（进程能响应即 200） |
| `/ready` | GET | 就绪探针（数据库异常返回 503） |
| `/health` | GET | 等价于 `/ready`，保留给既有部署脚本与监控 |
| `/api/texts/` | GET/POST | 条文列表 / 创建 |
| `/api/texts/{id}` | GET/PUT/DELETE | 单条条文操作 |
| `/api/texts/verify` | POST | 互联网校验条文 |
| `/api/cases/` | GET/POST | 病案列表（**公开视图，不含答案**）/ 创建 |
| `/api/cases/admin/` | GET | 病案列表（管理端，含诊断/方剂/教学要点/参考答案，需认证） |
| `/api/cases/admin/{id}` | GET | 单个病案（管理端完整字段） |
| `/api/cases/{id}` | GET/PUT/DELETE | 单个病案操作（GET 为公开视图） |
| `/api/analysis/` | POST | AI 条文分析 |
| `/api/documents/upload` | POST | 上传文档自动解析 |
| `/api/agent/session/start` | POST | 开始训练会话 |
| `/api/agent/session/{id}/message` | POST | 发送消息（多轮交互，需 `X-Session-Token`） |
| `/api/agent/session/{id}/evaluate` | POST | 结束并评价（需 `X-Session-Token`，响应含参考答案） |
| `/api/agent/public-stats` | GET | 公开统计数据 |
| `/api/agent/session-summary` | GET | 训练记录汇总（总数/进行中/已完成/平均分，需认证） |
| `/api/feedback/` | GET/POST | 反馈列表 / 提交 |
| `/api/import/` | GET | 导入批次管理 |

> 完整 API 文档启动后访问 `/docs`（Swagger UI）或 `/redoc`。

**分页约定**：所有列表接口接受 `skip` / `limit`，并通过响应头返回总数——
`X-Total-Count`（满足筛选条件的总条数）、`X-Skip`、`X-Limit`。响应体保持为数组，
前端用 `resp.headers.get('X-Total-Count')` 取总数即可实现翻页。

## 智能体训练流程

学生进入训练页面（`/train`），选择一个难度等级后，系统自动匹配临床病案并生成 AI "虚拟患者"。

**四阶段思辨**：

1. **辨病** — 通过问诊识别疾病类型（太阳/阳明/少阴病等）
2. **平脉** — 推断脉象特征与病机
3. **析证** — 深入分析证候的核心病机与演变规律
4. **定治** — 确定治疗原则与选方用药

AI 患者的回答风格会随机切换（正常/话痨/焦虑/硬汉/迷糊/戏精），模拟真实临床场景。训练结束后，系统自动生成评价报告，展示参考答案和相关经典条文。

## 部署

> **当前状态**：原公网实例（阿里云 `YOUR_SERVER_IP`）已到期下线，系统现在**仅在本地运行**。
> 以下部署说明保留给将来重新部署时参考；届时需重新确认服务器 `.env` 中的 `ADMIN_PASSWORD` 等变量，
> 并改用 `/ready` 作为健康检查端点。

### Render.com（PaaS 一键部署）

参见仓库中的 `render.yaml`，支持一键部署到 Render，自动挂载持久磁盘、配置环境变量。

### Linux 服务器（Alibaba Cloud ECS）

```bash
# 一键部署（在本机执行）
bash deploy.sh

# 或者手动在服务器上执行
sudo bash /root/Jin-Gui/server_deploy.sh
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `OPENAI_BASE_URL` | AI API 接口地址 | `https://api.deepseek.com` |
| `OPENAI_API_KEY` | AI API 密钥 | 必填 |
| `AI_MODEL` | 模型名称 | `deepseek-chat` |
| `ALT_MODELS` | 备用模型列表（逗号分隔） | 空 |
| `DATA_DIR` | 数据库存放目录 | `backend/data/` |
| `ADMIN_PASSWORD` | 管理员密码（**必须设置**；无内置默认值，未设置时管理端一律拒绝登录） | 无 |
| `SESSION_SECRET` | 训练会话归属令牌的 HMAC 密钥（留空则复用 `ADMIN_PASSWORD`） | 空 |
| `CORS_ORIGINS` | 允许的跨域来源，逗号分隔（默认不放行任何跨域；前后端同源部署无需配置） | 空 |
| `DISABLE_DOCS` | 设为 `1` 关闭 `/docs`、`/redoc`、`/openapi.json` | 空 |
| `LOG_FORMAT` | 日志格式（`json` 为 JSON 格式） | 可读格式 |

## License

仅供教学与学习使用。
