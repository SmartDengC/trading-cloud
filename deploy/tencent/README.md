# 腾讯云 PostgreSQL 部署

本目录只部署 Trading Cloud 的 PostgreSQL。腾讯云上已有的 MinIO 容器继续独立运行，本 Compose 不创建、不初始化、不重启 MinIO，也不管理其数据卷。

## 服务边界

```text
腾讯云宿主机
├─ postgres :5432       由本目录 compose.yaml 管理
├─ minio    :9000       已有容器，本仓库不管理
└─ console  :9001       已有容器，本仓库不管理
```

当前 5432、9000、9001 都通过腾讯公网 IP 提供访问，不使用 WireGuard 或 TLS。

## 启动 PostgreSQL

```bash
cd deploy/tencent
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，为 `POSTGRES_PASSWORD` 设置长随机密码：

```bash
openssl rand -base64 36
docker compose config -q
docker compose up -d
docker compose ps
```

Compose 使用命名卷 `trading-data_postgres-data` 持久化数据库。不要执行 `docker compose down -v`，也不要给任何 Compose 命令增加 `--remove-orphans`，以免误删数据库卷或被识别为 orphan 的现有 MinIO 容器。

## PostgreSQL 配置

| 参数 | 值 |
|---|---|
| 镜像 | `postgres:17.11-alpine` |
| 公网端口 | `0.0.0.0:5432` |
| 主机认证 | SCRAM-SHA-256 |
| 最大连接数 | 40 |
| 内存限制 | 1 GiB |
| CPU 限制 | 1.5 |
| shared buffers | 256 MiB |

腾讯安全组按当前选择允许 `0.0.0.0/0` 访问 TCP 5432。该规则允许任何公网来源尝试认证，应使用唯一强密码，并在后续启用 WireGuard 或 TLS 时立即收紧。

## 检查现有 MinIO

启动 PostgreSQL 前后都可以执行以下只读检查，确认本操作没有替换现有 MinIO：

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
ss -lntp | grep -E ':(9000|9001)\b'
curl --fail http://127.0.0.1:9000/minio/health/live
```

现有 MinIO 必须满足：

- 宿主机已映射 9000 和 9001。
- 已有私有 `trading-attachments` bucket。
- 已有供 FastAPI 使用的最小权限应用账号。
- API 不使用 MinIO root 凭据。

## 阿里云连接配置

阿里云 `deploy/aliyun/.env` 使用腾讯公网 IP：

```dotenv
TRADING_DATABASE_URL=postgresql+psycopg://trading:URL_ENCODED_POSTGRES_PASSWORD@TENCENT_PUBLIC_IP:5432/trading?sslmode=disable
TRADING_MINIO_ENDPOINT=TENCENT_PUBLIC_IP:9000
TRADING_MINIO_ACCESS_KEY=EXISTING_MINIO_APP_USER
TRADING_MINIO_SECRET_KEY=EXISTING_MINIO_APP_PASSWORD
TRADING_MINIO_BUCKET=trading-attachments
TRADING_MINIO_SECURE=false
```

## 运维命令

```bash
docker compose ps
docker compose logs -f postgres
docker compose restart postgres
docker compose up -d postgres
docker compose stop postgres
```

这些命令只作用于本 Compose 创建的 PostgreSQL。不要使用 `docker compose down --remove-orphans`；如果现有 MinIO 曾由同名 `trading-data` Compose 项目创建，该参数可能删除它。
