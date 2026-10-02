# 部署文档

本文档描述当前项目的本地运行、测试、生产运行和 Docker 部署要点，以代码中的实际配置为准。

## 环境要求

- Python 3.11+
- PostgreSQL 12+
- uv

如果使用 Docker：

- Docker
- docker-compose

## 环境变量

项目启动时会读取 `.env`。其中以下变量最关键：

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `DATABASE_HOST` | 是 | 数据库主机 |
| `DATABASE_PORT` | 是 | 数据库端口 |
| `DATABASE_USER` | 是 | 数据库用户名 |
| `DATABASE_PASSWORD` | 是 | 数据库密码 |
| `DATABASE_NAME` | 是 | 数据库名 |
| `APP_NAME` | 否 | 应用名，默认 `DitanBackend` |
| `APP_VERSION` | 否 | 运行时版本，默认 `3.0.0` |
| `APP_HOST` | 否 | 默认 `0.0.0.0` |
| `APP_PORT` | 否 | 默认 `8000` |
| `APP_DEBUG` | 否 | 默认 `False` |
| `LOG_LEVEL` | 否 | 默认 `INFO` |
| `LOG_FILE` | 否 | 默认 `logs/app.log` |
| `AI_API_KEY` | 是 | OpenAI Compatible API 密钥 |
| `AI_BASE_URL` | 是 | OpenAI Compatible API 地址 |
| `AI_MODEL_NAME` | 否 | 默认 `deepseek-chat` |
| `JWT_SECRET_KEY` | 强烈建议 | JWT 密钥；代码有默认值，但生产必须覆盖 |
| `JWT_ALGORITHM` | 否 | 默认 `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | 否 | 默认 `1440` |
| `APKIO_AUTH_ENABLED` | 否 | 是否接受 Apkio Org 用户 JWT，默认 `False` |
| `APKIO_JWT_SECRET_KEY` | 开启 Apkio 时必填 | Apkio `APP_SECRET_KEY`，用于本地验签 |
| `APKIO_JWT_ALGORITHM` | 否 | 默认 `HS256` |
| `APKIO_ORG_TOKEN_AUDIENCE` | 否 | 默认 `org` |
| `APKIO_REQUIRED_PERMISSION` | 否 | 默认 `ditan.access` |
| `APKIO_AUTO_CREATE_DOCTOR` | 否 | 默认 `True`；首次 Apkio 访问时自动创建本地医生业务实体 |

推荐从示例文件开始：

```bash
cp .env.example .env
```

## 本地部署

### 1. 安装依赖

```bash
uv sync
uv sync --extra dev
```

### 2. 创建数据库

```sql
CREATE DATABASE ditan_db;
```

### 3. 初始化表结构

应用启动前必须升级 Alembic；启动时仅核对 schema 版本：

```bash
uv run --frozen alembic upgrade head
```

### 4. 启动服务

开发模式：

```bash
uv run python scripts/run_dev.py
```

普通运行：

```bash
uv run python main.py
```

启动后访问：

- `http://localhost:8000/`
- `http://localhost:8000/health`
- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

## 测试

运行所有测试：

```bash
uv run pytest
```

详细输出：

```bash
uv run pytest -v
```

使用封装脚本：

```bash
uv run python scripts/run_tests.py
```

说明：

- 当前测试使用 SQLite in-memory，而不是 PostgreSQL
- 测试环境会在 `tests/conftest.py` 中覆写数据库依赖和部分环境变量

## 生产运行

推荐使用 `uvicorn` 直接启动：

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

生产环境建议：

- 设置 `APP_DEBUG=False`
- 覆盖 `JWT_SECRET_KEY`
- 使用可访问的 PostgreSQL 实例
- 为 `AI_API_KEY`、`AI_BASE_URL` 配置真实值
- 在反向代理后运行

## Docker 部署

仓库中包含两套 Compose：

- `docker-compose.yml`
  生产风格部署，默认拉取远端应用镜像
- `docker-compose.dev.yml`
  开发叠加配置，本地构建镜像并挂载源码

本地开发：

```bash
./scripts/docker_build.sh dev
```

生产风格：

```bash
./scripts/docker_build.sh up
```

详见根目录 [README.Docker.md](../README.Docker.md)。

## 日志

默认日志文件：

```text
logs/app.log
```

代码中的 `LoggerSetup` 会在启动时自动创建父目录，因此本地运行不需要手动创建 `logs/`。

## 数据库初始化与迁移

空库和已有库均先运行 `uv run --frozen alembic upgrade head`。应用启动只检查 Alembic head，版本不符则拒绝启动。

部署前核对数据库版本并备份。003 从真实的 `002_add_apkio_doctor_bindings` 接续，保留未知归属数据在 `__legacy__`。
没有 Alembic 版本记录的旧库需单独核对实际 schema 后处理，不得直接猜测版本或删除数据重建。

上传默认 `MEDICAL_UPLOAD_AUTH_REQUIRED=True`，另需设置 `APKIO_BASE_URL=https://<apkio-host>/api`。
该上传验票不需要新 JWT 密钥。非本地必须使用 HTTPS；本地 loopback HTTP 需显式允许。
现有医生 Apkio JWT 配置保持原用途。详见[组织上传交接](DITAN_ORG_MEDICAL_UPLOAD_HANDOVER.md)。

## 常见问题

### 启动时报缺少环境变量

`Settings` 会在启动阶段读取 `.env`，如果缺少 `DATABASE_*`、`AI_API_KEY`、`AI_BASE_URL` 等关键字段，应用会在导入阶段失败。先检查 `.env` 是否完整。

### 健康检查正常，但 AI 接口失败

这通常表示应用已经启动，但 `AI_API_KEY`、`AI_BASE_URL` 或上游模型服务不可用。先检查日志，再核对模型服务配置。

### 返回 401

当前受保护接口必须带：

```http
Authorization: Bearer <access_token>
```

默认 token 通过 `/api/v1/doctor/login` 获取。开启 `APKIO_AUTH_ENABLED=True` 后，也可以使用 Apkio `/api/auth/login` 返回的 Org 用户 `accessToken`；该账号必须具备 `APKIO_REQUIRED_PERMISSION` 权限。`APKIO_AUTO_CREATE_DOCTOR=True` 时，未绑定的 Apkio 用户会在首次访问时自动创建本地医生业务实体；关闭该选项后，需要先通过 `scripts/bind_apkio_doctors.py` 绑定到本地医生。

### 需要重置 Docker 数据库

Linux/macOS：

```bash
./scripts/manage_db.sh reset
```

Windows：

```powershell
.\scripts\manage_db.ps1 reset
```
