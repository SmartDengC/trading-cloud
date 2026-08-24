# Trading Cloud

`stock-exchange-reviews` 的独立 FastAPI 后端。PostgreSQL、MinIO 与 API 部署在同一 Docker Compose 网络中，公网仅暴露 Caddy HTTPS。

不使用 Docker、直接在宿主机运行 API 的步骤请参阅 [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)。

## 本地启动

本地启动只需要 Docker Compose，不需要在宿主机安装 Python 或下载 Python 依赖。

```bash
cp .env.example .env
```

先修改 `.env`，至少完成以下配置：

- 将 `POSTGRES_PASSWORD` 改成强密码，并同步修改 `TRADING_DATABASE_URL` 中的密码。
- 将 `MINIO_ROOT_PASSWORD` 改成强密码，并同步修改 `TRADING_MINIO_SECRET_KEY`。
- 本地开发使用 `TRADING_FRONTEND_ORIGIN=http://localhost:3000`、`TRADING_PUBLIC_BASE_URL=http://127.0.0.1:8000`、`TRADING_SESSION_SECURE=false`。

构建 API 镜像，并在镜像内生成管理员 Argon2 密码哈希：

```bash
docker compose -f compose.yaml -f compose.dev.yaml build api
docker compose -f compose.yaml -f compose.dev.yaml run --rm --no-deps api \
  python -m app.security 'your-password'
```

将输出写入 `.env` 的 `TRADING_ADMIN_PASSWORD_HASH`。Argon2 hash 含有 `$`，必须用单引号包住，例如 `TRADING_ADMIN_PASSWORD_HASH='$argon2id$...'`，然后启动全部本地服务：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
docker compose -f compose.yaml -f compose.dev.yaml ps
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

本地 API 为 `http://127.0.0.1:8000`，Swagger 为 `http://127.0.0.1:8000/docs`，MinIO 控制台为 `http://127.0.0.1:9001`。查看日志和停止服务：

```bash
docker compose -f compose.yaml -f compose.dev.yaml logs -f migrate api
docker compose -f compose.yaml -f compose.dev.yaml down
```

首次 Docker 构建会在镜像构建环境中拉取基础镜像和锁定依赖，不会向宿主机 Python 环境安装包。

## 生产启动

将 API 域名解析到服务器，配置 `.env` 中真实的 HTTPS 域名、前端 Origin、强密码，并保持 `TRADING_SESSION_SECURE=true`。生产环境不要叠加 `compose.dev.yaml`：

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f migrate api caddy
```

PostgreSQL 和 MinIO 在生产 Compose 中不发布宿主端口，Caddy 是唯一公网入口并自动申请 HTTPS 证书。

## 数据库

- 生产升级：`docker compose run --rm migrate`
- 独立建表：`psql "postgresql://user:password@host/database" -f sql/business_schema.sql`
- 初始化字典：`psql "postgresql://user:password@host/database" -f sql/business_seed.sql`

Alembic 是生产 schema 升级入口；SQL 文件用于审阅、空库初始化和结构等价验证。

## 源数据迁移

先启动目标 PostgreSQL/MinIO 并执行 Alembic，然后配置 `LEGACY_DATABASE_URL`、`BLOB_READ_WRITE_TOKEN` 和目标 `TRADING_DATABASE_URL`。

```bash
# 通过 Bearer Token 只读检查源库和全部私有 Blob
docker compose run --rm --no-deps -v "$PWD:/reports" api \
  python -m app.migration.legacy --report /reports/migration-report.dry-run.json

# 只有 schema、目标业务表及 MinIO 桶均为空时直接导入
docker compose run --rm --no-deps -v "$PWD:/reports" api \
  python -m app.migration.legacy --apply --report /reports/migration-report.apply.json

# Compose 初始迁移已写入默认选项，演练和最终停写切换使用显式覆盖
docker compose run --rm --no-deps -v "$PWD:/reports" api \
  python -m app.migration.legacy --apply --replace --report /reports/migration-report.final.json
```

`--replace` 不会删除 `auth_sessions`，也不会修改源 Neon 或 Vercel Blob。

## 检查与备份

```bash
uv run ruff check .
uv run mypy app
uv run pytest
TRADING_BACKUP_DIR=/srv/trading-cloud/backups scripts/backup.sh
scripts/verify-backup.sh /srv/trading-cloud/backups/20260823T120000Z
```

本机备份默认保留 14 天。它防止应用级误操作，但不能替代异地灾备。
