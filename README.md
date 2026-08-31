# Trading Cloud

`stock-exchange-reviews` 的独立 FastAPI 后端。生产环境连接外部 PostgreSQL/MinIO，Docker Compose 默认只运行迁移、API 和 Caddy；本地联调可通过 `local-infra` profile 启动内置 PostgreSQL/MinIO。

腾讯云运行 PostgreSQL 和现有 MinIO、阿里云运行 API/Caddy、Vercel 同源转发 API 的生产方案见 [deploy/README.md](deploy/README.md)。

不使用 Docker、直接在宿主机运行 API 的步骤请参阅 [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)。

## Docker 启动

### 1. 准备 Compose

```bash
docker compose version
docker buildx version
```

Compose v2 为必需项；[Buildx](https://github.com/docker/buildx#installing) 为可选增强。Dockerfile 同时兼容 legacy builder，并通过独立的依赖层复用普通 Docker 缓存。

Linux 用户需要加入 `docker` 组后重新登录，或执行 `newgrp docker` 立即刷新权限。注意该用户组拥有 root 级权限。

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker info
```

### 2. 配置环境

```bash
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，重点保持以下配置一致：

- `POSTGRES_PASSWORD` 与 `TRADING_DATABASE_URL` 中的密码相同。
- `MINIO_ROOT_USER` 与 `TRADING_MINIO_ACCESS_KEY` 相同。
- `MINIO_ROOT_PASSWORD` 与 `TRADING_MINIO_SECRET_KEY` 相同。
- 使用外部服务时，将 `TRADING_DATABASE_URL`、`TRADING_MINIO_ENDPOINT`、访问凭据和桶名改为外部配置；MinIO 桶须提前创建。
- 生产环境填写真实域名：`TRADING_API_DOMAIN` 只写主机名，另外两个 URL 使用 HTTPS，并保持 `TRADING_SESSION_SECURE=true`。
- 前端与 API 使用同一主域的不同子域时，将 `TRADING_SESSION_COOKIE_DOMAIN` 设为共享主域；本地开发留空。
- 登录会话默认有效期为 2 小时，可通过 `TRADING_SESSION_HOURS` 配置，范围为 1–720 小时。

使用强密码替换模板值后，静默校验配置：

```bash
docker compose config -q
```

腾讯云 CVM 可在 `.env` 中启用内网优先的 PyPI 镜像，并按[腾讯云文档](https://cloud.tencent.com/document/product/213/8623)配置 Docker Hub 镜像加速：

```dotenv
UV_DEFAULT_INDEX=https://mirrors.cloud.tencent.com/pypi/simple
```

### 3. 生成管理员密码

```bash
docker compose build api
docker compose run --rm --no-deps api python -m app.security 'your-password'
```

将输出写入 `.env`，Argon2 hash 必须使用单引号，避免其中的 `$` 被 Compose 展开：

```dotenv
TRADING_ADMIN_PASSWORD_HASH='$argon2id$...'
```

### 4. 启动服务

生产环境默认连接 `.env` 中配置的外部 PostgreSQL/MinIO，Caddy 仅向公网发布 80/443：

```bash
docker compose pull caddy
docker compose build api
docker compose up -d
docker compose ps
docker compose logs -f migrate api caddy
```

后续发布只需重新执行 `docker compose build api && docker compose up -d`；依赖锁文件未变化时会复用 Docker 层缓存。

会话有效期调整后，首次部署需使用生产 PostgreSQL 执行一次 `DELETE FROM auth_sessions;`，使旧的 7 天会话立即失效。之后新建会话统一按 `TRADING_SESSION_HOURS` 计算。

临时通过服务器 IP 使用 HTTP 时，先将 `.env` 调整为：

```dotenv
TRADING_PUBLIC_BASE_URL=http://SERVER_IP:8000
TRADING_FRONTEND_ORIGINS=http://SERVER_IP:3000
TRADING_SESSION_SECURE=false
TRADING_SESSION_COOKIE_DOMAIN=
```

再使用 HTTP 覆盖配置启动。该配置将 API 发布到 `0.0.0.0:8000` 并禁用 Caddy；腾讯云安全组应仅允许可信客户端 IP 访问 TCP 8000。

```bash
docker compose -f compose.yaml -f compose.http.yaml up -d --build
curl http://SERVER_IP:8000/health/ready
```

HTTP 会明文传输登录凭据和会话，只用于临时联调。HTTPS 前端也不能调用 HTTP API，正式部署应恢复原环境变量并使用基础 Compose 配置。

本地联调使用开发覆盖配置：

```bash
docker compose --profile local-infra -f compose.yaml -f compose.dev.yaml up -d --build
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

本地前端与 API 必须都使用 `localhost`。API 为 `http://localhost:8000`，Swagger 为 `http://localhost:8000/docs`，MinIO 控制台为 `http://127.0.0.1:9001`。

API 镜像以非 root 用户 `10001:10001` 运行。生产环境不会启动内置 PostgreSQL/MinIO；`local-infra` profile 仅供本地联调。

## 数据库

- 生产升级：`docker compose run --rm migrate`
- 独立建表：`psql "postgresql://user:password@host/database" -f sql/business_schema.sql`
- 初始化字典：`psql "postgresql://user:password@host/database" -f sql/business_seed.sql`

Alembic 是生产 schema 升级入口；SQL 文件用于审阅、空库初始化和结构等价验证。

## 源数据迁移

先启动目标 PostgreSQL/MinIO 并执行 Alembic，然后配置 `LEGACY_DATABASE_URL`、`BLOB_READ_WRITE_TOKEN` 和目标 `TRADING_DATABASE_URL`。
以下命令使用当前宿主用户写入绑定目录，避免 Linux 上固定容器 UID 无法创建迁移报告。

```bash
# 通过 Bearer Token 只读检查源库和全部私有 Blob
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" -v "$PWD:/reports" api \
  python -m app.migration.legacy --report /reports/migration-report.dry-run.json

# 只有 schema、目标业务表及 MinIO 桶均为空时直接导入
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" -v "$PWD:/reports" api \
  python -m app.migration.legacy --apply --report /reports/migration-report.apply.json

# Compose 初始迁移已写入默认选项，演练和最终停写切换使用显式覆盖
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" -v "$PWD:/reports" api \
  python -m app.migration.legacy --apply --replace --report /reports/migration-report.final.json
```

`--replace` 不会删除 `auth_sessions`，也不会修改源 Neon 或 Vercel Blob。

## 检查与备份

```bash
uv run ruff check .
uv run mypy app
uv run python -m pytest
TRADING_BACKUP_DIR=/srv/trading-cloud/backups scripts/backup.sh
scripts/verify-backup.sh /srv/trading-cloud/backups/20260823T120000Z
```

备份脚本仅适用于 `local-infra` profile。本机备份默认保留 14 天；外部 PostgreSQL/MinIO 应在对应服务器配置独立备份与异地灾备。
