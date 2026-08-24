# Trading Cloud

`stock-exchange-reviews` 的独立 FastAPI 后端。PostgreSQL、MinIO 与 API 部署在同一 Docker Compose 网络中，公网仅暴露 Caddy HTTPS。

不使用 Docker、直接在宿主机运行 API 的步骤请参阅 [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)。

## Docker 启动

### 1. 准备 Compose

```bash
docker compose version
```

若提示 `compose is not a docker command`，先安装 [Docker Compose v2 插件](https://docs.docker.com/compose/install/linux/)。Ubuntu 20.04 默认软件源通常不提供该插件，可按官方文档手动安装。

### 2. 配置环境

```bash
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，重点保持以下配置一致：

- `POSTGRES_PASSWORD` 与 `TRADING_DATABASE_URL` 中的密码相同。
- `MINIO_ROOT_USER` 与 `TRADING_MINIO_ACCESS_KEY` 相同。
- `MINIO_ROOT_PASSWORD` 与 `TRADING_MINIO_SECRET_KEY` 相同。
- 生产环境填写真实域名：`TRADING_API_DOMAIN` 只写主机名，另外两个 URL 使用 HTTPS，并保持 `TRADING_SESSION_SECURE=true`。
- 前端与 API 使用同一主域的不同子域时，将 `TRADING_SESSION_COOKIE_DOMAIN` 设为共享主域；本地开发留空。

使用强密码替换模板值后，静默校验配置：

```bash
docker compose config -q
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

生产环境使用 Caddy 自动配置 HTTPS，仅向公网发布 80/443：

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f migrate api caddy
```

本地联调使用开发覆盖配置：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

本地前端与 API 必须都使用 `localhost`。API 为 `http://localhost:8000`，Swagger 为 `http://localhost:8000/docs`，MinIO 控制台为 `http://127.0.0.1:9001`。

API 镜像以非 root 用户 `10001:10001` 运行；生产 Compose 不发布 PostgreSQL 和 MinIO 的宿主端口。

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

本机备份默认保留 14 天。它防止应用级误操作，但不能替代异地灾备。
