# Docker 部署指南

本仓库同时提供两套 Docker Compose 用法：

- `docker-compose.yml`
  用于生产风格部署，`app` 服务默认从 `IMAGE_REGISTRY/ditan-backend:IMAGE_TAG` 拉取镜像。
- `docker-compose.dev.yml`
  叠加开发配置，本地构建 `Dockerfile`，挂载源码并开启调试友好的运行方式。

## 快速开始

### 本地开发

推荐直接使用开发叠加配置：

```bash
cp .env.example .env
./scripts/docker_build.sh dev
```

Windows:

```powershell
Copy-Item .env.example .env
.\scripts\docker_build.ps1 dev
```

开发模式会：

- 构建本地镜像
- 启动 PostgreSQL
- 将当前仓库挂载到容器内
- 使用 `docker-compose.dev.yml` 覆盖基础配置

### 生产风格部署

如果你已经有可拉取的应用镜像：

```bash
cp .env.example .env
./scripts/docker_build.sh up
```

Windows:

```powershell
Copy-Item .env.example .env
.\scripts\docker_build.ps1 up
```

生产风格部署使用 `docker-compose.yml`，会从镜像仓库拉取：

- `${IMAGE_REGISTRY:-docker.huanyufuture.top}/ditan-backend:${IMAGE_TAG:-latest}`
- `${IMAGE_REGISTRY:-docker.huanyufuture.top}/postgres:17`

如需覆盖镜像仓库或标签，可在 `.env` 或 shell 中设置：

```env
IMAGE_REGISTRY=your-registry.example.com
IMAGE_TAG=3.0.0
```

## 脚本命令

### Linux/macOS

```bash
./scripts/docker_build.sh help
```

### Windows

```powershell
.\scripts\docker_build.ps1 help
```

命令含义：

| 命令 | 说明 |
| --- | --- |
| `init` | 从 `.env.example` 生成 `.env`，并创建 `logs/` |
| `build` | 使用开发叠加配置构建本地 `app` 镜像 |
| `dev` | 启动本地开发栈 |
| `up` / `prod` | 启动生产风格栈 |
| `down` | 停止服务 |
| `restart` | 重启服务 |
| `logs -f` | 跟踪日志 |
| `ps` | 查看服务状态 |
| `clean` | 删除容器、网络和卷 |

## 关键环境变量

`.env.example` 已包含当前项目所需的最小配置。Docker 运行时重点关注：

```env
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USER=postgres
DATABASE_PASSWORD=changeme123
DATABASE_NAME=ditan_db

APP_NAME=DitanBackend
APP_VERSION=3.0.0
APP_PORT=8000
APP_DEBUG=False

AI_API_KEY=YOUR_API_KEY
AI_BASE_URL=YOUR_BASE_URL
AI_MODEL_NAME=deepseek-flash

JWT_SECRET_KEY=YOUR_JWT_SECRET_KEY
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

注意：

- 基础 `docker-compose.yml` 会在容器内把 `DATABASE_HOST` 覆盖为 `db`
- `docker-compose.dev.yml` 会把 `APP_DEBUG` 设为 `True`
- 日志默认写到容器内的 `logs/app.log`，并挂载为宿主机 `./logs`

## 常用命令

```bash
docker-compose ps
docker-compose logs -f app
docker-compose logs -f db
docker-compose down
docker-compose down -v
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

## 访问地址

- 应用首页: `http://localhost:8000/`
- 健康检查: `http://localhost:8000/health`
- Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 故障排查

### 应用容器启动后立即退出

- 先查看 `docker-compose logs app`
- 检查 `.env` 是否填写了 `AI_API_KEY`、`AI_BASE_URL`、`JWT_SECRET_KEY`
- 检查 PostgreSQL 账号密码与 `.env` 是否一致

### 无法连接数据库

- 查看 `docker-compose logs db`
- 确认 `DATABASE_PASSWORD` 与数据库容器启动参数一致
- 确认本机 `5432` 端口未被占用

### 需要本地重新构建

```bash
./scripts/docker_build.sh build
./scripts/docker_build.sh dev
```

Windows:

```powershell
.\scripts\docker_build.ps1 build
.\scripts\docker_build.ps1 dev
```
