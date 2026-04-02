# DitanBackend

DitanBackend 是一个基于 FastAPI 的中医智能诊疗后端，当前提供医生认证、患者与就诊管理、AI 辅助诊断和 AI 聊天会话能力。

## 当前功能

- 医生注册、登录、个人信息查询与更新、修改密码
- 预问诊系统写入患者、就诊记录、预诊记录和三诊分析结果
- 医生按手机号查询患者及历史就诊记录
- AI 诊断同步生成和 SSE 流式生成
- 医生诊断创建、修改、查询，以及就诊确认
- AI 聊天会话创建、查看、发送消息、流式回复、关闭会话
- Swagger UI / ReDoc、JWT 认证、结构化 JSON 日志

## 技术栈

- Python 3.11+
- FastAPI
- SQLAlchemy 2.x Async + asyncpg
- PostgreSQL
- Pydantic 2 + pydantic-settings
- OpenAI Compatible API
- JWT + bcrypt
- pytest + httpx
- uv

## 项目结构

```text
app/
├── api/
│   ├── chat.py
│   ├── deps.py
│   ├── doctor.py
│   ├── patient.py
│   └── router.py
├── core/
│   ├── auth.py
│   ├── config.py
│   ├── database.py
│   ├── exceptions.py
│   └── logging.py
├── models/
│   ├── chat.py
│   ├── doctor.py
│   ├── enums.py
│   └── medical.py
├── repositories/
├── schemas/
│   ├── chat.py
│   ├── common.py
│   ├── doctor.py
│   └── patient.py
└── services/
    ├── chat_service.py
    ├── diagnosis_service.py
    ├── doctor_service.py
    ├── medical_record_service.py
    ├── openai_client.py
    ├── patient_service.py
    ├── prompt_templates.py
    └── tcm_diagnosis_service.py

docs/
├── API.md
├── DATABASE.md
├── DEPLOYMENT.md
└── QUICKSTART.md
```

## 快速开始

### 1. 安装依赖

```bash
uv sync
uv sync --extra dev
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

至少需要确认以下配置：

```env
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USER=postgres
DATABASE_PASSWORD=your_password
DATABASE_NAME=ditan_db

AI_API_KEY=your_api_key
AI_BASE_URL=https://api.deepseek.com
AI_MODEL_NAME=deepseek-chat

JWT_SECRET_KEY=your-secret-key
```

### 3. 创建数据库

```sql
CREATE DATABASE ditan_db;
```

### 4. 初始化表结构

应用启动时会执行 `Base.metadata.create_all()` 自动创建表；如果你想在启动前先初始化，也可以执行：

```bash
uv run python scripts/init_db.py
```

### 5. 启动服务

```bash
uv run python scripts/run_dev.py
```

或：

```bash
uv run python main.py
```

启动后可访问：

- `http://localhost:8000/`
- `http://localhost:8000/health`
- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

## 认证说明

- `/api/v1/doctor/register` 和 `/api/v1/doctor/login` 无需认证
- `/api/v1/patient/query`、`/api/v1/medical-record/{record_id}`、AI 诊断、医生诊断、就诊确认都需要医生 JWT
- `/api/v1/chat/*` 当前无需 JWT

认证请求头格式：

```http
Authorization: Bearer <access_token>
```

## 核心接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/doctor/register` | 医生注册 |
| `POST` | `/api/v1/doctor/login` | 医生登录 |
| `GET` | `/api/v1/doctor/me` | 当前医生信息 |
| `PUT` | `/api/v1/doctor/me` | 更新当前医生信息 |
| `POST` | `/api/v1/doctor/change-password` | 修改密码 |
| `GET` | `/api/v1/patient/query?phone=...` | 按手机号查询患者 |
| `POST` | `/api/v1/medical-record` | 创建就诊记录 |
| `GET` | `/api/v1/medical-record/{record_id}` | 获取完整就诊记录 |
| `POST` | `/api/v1/medical-record/{record_id}/ai-diagnosis` | 同步 AI 诊断 |
| `POST` | `/api/v1/medical-record/{record_id}/ai-diagnosis/stream` | 流式 AI 诊断 |
| `POST` | `/api/v1/medical-record/{record_id}/doctor-diagnosis` | 创建医生诊断 |
| `PUT` | `/api/v1/doctor-diagnosis/{diagnosis_id}` | 更新医生诊断 |
| `GET` | `/api/v1/doctor-diagnosis/{diagnosis_id}` | 医生诊断详情 |
| `POST` | `/api/v1/medical-record/{record_id}/confirm` | 确认就诊完成 |
| `POST` | `/api/v1/chat/conversation` | 创建聊天会话 |
| `GET` | `/api/v1/chat/conversation/{session_id}` | 获取会话详情 |
| `POST` | `/api/v1/chat/chat` | 非流式聊天 |
| `POST` | `/api/v1/chat/chat/stream` | 流式聊天 |
| `DELETE` | `/api/v1/chat/conversation/{session_id}` | 关闭会话 |

## 文档索引

- [API 文档](docs/API.md)
- [快速上手](docs/QUICKSTART.md)
- [部署文档](docs/DEPLOYMENT.md)
- [数据库文档](docs/DATABASE.md)
- [Docker 部署指南](README.Docker.md)

## 测试

```bash
uv run pytest
uv run pytest -v
uv run python scripts/run_tests.py
```

## 说明

- 当前项目版本与默认运行时版本统一为 `3.0.0`
- 日志默认写入 `logs/app.log`，目录会在应用启动时自动创建
- API 详细请求体、响应体和 SSE 事件格式见 [docs/API.md](docs/API.md)
