# Trading Cloud 本地启动指南

本文说明如何不使用 Docker，在宿主机直接启动 Trading Cloud API。

## 1. 环境要求

本机需要安装：

- Python 3.14
- PostgreSQL 17
- MinIO
- MinIO Client（`mc`）
- `uv`

项目不会把 Python 依赖安装到系统 Python，而是由 `uv` 安装到项目的 `.venv`。首次执行 `uv sync` 时，如果本机没有完整缓存，则需要联网下载依赖。

## 2. 创建本地配置

进入项目并复制环境变量模板：

```bash
cd /Users/dengc4r/c4r_blog/github/trading-cloud
cp .env.example .env
```

修改 `.env`：

```dotenv
TRADING_DATABASE_URL=postgresql+psycopg://trading:你的数据库密码@127.0.0.1:5432/trading

# 使用 stock-exchange-reviews 前端联调时使用这个 Origin。
TRADING_FRONTEND_ORIGIN=http://localhost:3000

# 如果只通过 Swagger 测试写接口，可以改成：
# TRADING_FRONTEND_ORIGIN=http://localhost:8000

TRADING_PUBLIC_BASE_URL=http://localhost:8000
TRADING_SESSION_SECURE=false
TRADING_SESSION_COOKIE_DOMAIN=

TRADING_MINIO_ENDPOINT=127.0.0.1:9000
TRADING_MINIO_ACCESS_KEY=trading-minio
TRADING_MINIO_SECRET_KEY=你的MinIO密码
TRADING_MINIO_BUCKET=trading-attachments
TRADING_MINIO_SECURE=false

TRADING_ADMIN_USERNAME=admin
TRADING_ADMIN_PASSWORD_HASH=
```

`TRADING_FRONTEND_ORIGIN` 必须与发起写请求的浏览器 Origin 完全一致，否则登录和其他写接口会返回 `403`。

## 3. 准备 PostgreSQL

确保 PostgreSQL 17 已启动，然后创建用户和数据库：

```bash
psql postgres -c "CREATE ROLE trading LOGIN PASSWORD '你的数据库密码';"
psql postgres -c "CREATE DATABASE trading OWNER trading;"
```

如果用户或数据库已经存在，可以跳过对应命令。`.env` 中 `TRADING_DATABASE_URL` 的用户名、密码和数据库名需要与这里保持一致。

## 4. 准备 MinIO

创建本地数据目录并启动 MinIO：

```bash
cd /Users/dengc4r/c4r_blog/github/trading-cloud

MINIO_ROOT_USER=trading-minio \
MINIO_ROOT_PASSWORD='你的MinIO密码' \
minio server ./minio-data --console-address :9001
```

保持该终端运行，另开一个终端初始化私有桶：

```bash
mc alias set local http://127.0.0.1:9000 trading-minio '你的MinIO密码'
mc mb --ignore-existing local/trading-attachments
mc anonymous set none local/trading-attachments
```

初次只查看 Swagger、存活检查和不涉及附件的接口时，可以暂不启动 MinIO；此时 `/health/ready` 和附件接口不会正常工作。

## 5. 安装 Python 依赖

安装开发及运行依赖：

```bash
cd /Users/dengc4r/c4r_blog/github/trading-cloud
uv sync --dev
```

如果只允许使用本机已有缓存，不允许联网下载：

```bash
uv sync --offline --dev
```

缓存不完整时，离线命令会直接失败，不会转为联网下载。

## 6. 初始化数据库

使用 Alembic 创建业务表并写入默认交易选项：

```bash
uv run alembic upgrade head
```

也可以分别审阅独立 SQL 文件：

- `sql/business_schema.sql`：业务表、认证会话表、约束和索引
- `sql/business_seed.sql`：默认交易选项和默认汇率

生产环境升级应始终使用 Alembic。

## 7. 生成管理员密码

执行：

```bash
uv run python -m app.security '你的登录密码'
```

将输出写入 `.env`：

```dotenv
TRADING_ADMIN_USERNAME=admin
TRADING_ADMIN_PASSWORD_HASH='$argon2id$...'
```

Argon2 hash 包含 `$`，因此必须使用单引号包住完整 hash，避免环境变量展开导致内容损坏。

## 8. 启动 FastAPI

推荐使用 FastAPI 开发模式：

```bash
uv run fastapi dev app/main.py \
  --host 127.0.0.1 \
  --port 8000
```

也可以直接使用 Uvicorn：

```bash
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

启动后访问：

- API：<http://localhost:8000>
- Swagger：<http://localhost:8000/docs>
- 存活检查：<http://localhost:8000/health/live>
- 就绪检查：<http://localhost:8000/health/ready>
- MinIO 控制台：<http://127.0.0.1:9001>

## 9. 登录接口检查

如果 `.env` 中配置的是 `TRADING_FRONTEND_ORIGIN=http://localhost:3000`，可以使用以下命令检查登录：

```bash
curl -i \
  -c /tmp/trading-cloud-cookie.txt \
  -H 'Origin: http://localhost:3000' \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"你的登录密码"}' \
  http://localhost:8000/api/auth/login
```

使用保存的 Cookie 检查会话：

```bash
curl -i \
  -b /tmp/trading-cloud-cookie.txt \
  http://localhost:8000/api/auth/session
```

## 10. 常见问题

### `/health/live` 正常，但 `/health/ready` 返回 503

API 已启动，但 PostgreSQL 或 MinIO 尚未就绪。检查数据库连接、MinIO 地址、账号密码以及 `trading-attachments` 桶是否存在。

### 登录或写接口返回 403

请求的 `Origin` 与 `TRADING_FRONTEND_ORIGIN` 不一致。修改 `.env` 后需要重新启动 FastAPI。

### 浏览器登录成功但不保存 Cookie

本地 HTTP 环境必须设置：

```dotenv
TRADING_SESSION_SECURE=false
```

生产 HTTPS 环境必须恢复为 `true`。

生产环境如果前端与 API 使用同一主域的不同子域，还需要配置共享 Cookie Domain，例如：

```dotenv
TRADING_SESSION_COOKIE_DOMAIN=example.com
```

### `uv sync --offline --dev` 失败

表示本机缓存缺少 Python 3.14、Python 包或对应平台的二进制 wheel。允许联网时执行 `uv sync --dev`；否则需要先准备完整离线缓存。
