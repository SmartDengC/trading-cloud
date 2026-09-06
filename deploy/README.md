# 双云公网部署

生产拓扑固定为：

```text
se.vdcc.cn (Vercel)
  /api/* -> HKG Edge Function -> https://hahadeng.cn/api/*
                                     |
                                     v
                           阿里云 Caddy + FastAPI
                              |               |
                              | 公网 HTTP     | 公网 PostgreSQL
                              v               v
                    腾讯云现有 MinIO :9000   腾讯云 PostgreSQL :5432
 腾讯云 MinIO 控制台 :9001
```

腾讯云上的 MinIO 是已有容器，本仓库不创建、不重启、不迁移该容器，也不管理它的数据卷、bucket、用户或策略。腾讯侧 Compose 只负责 PostgreSQL。

## 风险确认

当前方案按明确选择执行：腾讯云安全组把 TCP 5432、9000、9001 对 `0.0.0.0/0` 开放，PostgreSQL 和 MinIO 暂不启用 TLS。这样阿里云和本地都可直接连接，但互联网中的任何地址也可以扫描和尝试登录，且数据库、附件及 MinIO 控制台流量没有传输加密。

上线前必须满足：

- PostgreSQL、MinIO root、MinIO 应用账号使用三个不同的长随机密码。
- FastAPI 只使用现有 MinIO 最小权限应用账号，不使用 root 账号。
- `trading-attachments` bucket 保持私有且已经存在。
- 腾讯公网 IP 固定；不要给腾讯服务器配置业务域名。

## 1. 服务器准备

两台服务器都需要 Docker Engine 和 Docker Compose v2。先检查版本和内存：

```bash
docker compose version
free -h
```

阿里云 2 GiB 主机建议配置至少 2 GiB swap，避免首次构建 Python 镜像时内存不足。执行前先用 `swapon --show` 确认没有现有 swap：

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 2. 检查腾讯云现有 MinIO

在腾讯云服务器确认现有容器和端口映射；不要执行重建或删除命令：

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
ss -lntp | grep -E ':(9000|9001)\b'
curl --fail http://127.0.0.1:9000/minio/health/live
```

预期 9000 和 9001 都已发布到宿主机。另用现有应用账号确认私有 bucket 可读：

```bash
mc alias set trading http://127.0.0.1:9000 EXISTING_MINIO_APP_USER EXISTING_MINIO_APP_PASSWORD
mc ls trading/trading-attachments
```

如果服务器没有安装 `mc`，可跳过这一步并通过 FastAPI 的 `/health/ready` 验证；本部署不会为此拉取或启动新的 MinIO/mc 容器。

## 3. 腾讯云 PostgreSQL

```bash
cd deploy/tencent
cp .env.example .env
chmod 600 .env
openssl rand -base64 36
```

把随机值写入 `POSTGRES_PASSWORD`，然后校验并启动：

```bash
docker compose config -q
docker compose up -d
docker compose ps
docker compose logs postgres
```

腾讯侧不要执行 `docker compose down -v`，也不要使用 `--remove-orphans`；后者可能删除带有同一 Compose 项目标记的现有 MinIO 容器。

确认 PostgreSQL 监听全部 IPv4 地址，同时现有 MinIO 仍保持运行：

```bash
ss -lntp | grep -E ':(5432|9000|9001)\b'
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

腾讯云安全组入站规则按当前选择设置：

| 协议端口 | 来源 | 用途 |
|---|---|---|
| TCP 5432 | `0.0.0.0/0` | PostgreSQL |
| TCP 9000 | `0.0.0.0/0` | 现有 MinIO S3 API |
| TCP 9001 | `0.0.0.0/0` | 现有 MinIO Console |
| TCP 22 | 管理 IP | SSH |

## 4. 阿里云 API

`hahadeng.cn` 继续只解析到阿里云服务器。配置：

```bash
cd deploy/aliyun
cp .env.example .env
chmod 600 .env
```

替换 `.env` 中的 `TENCENT_PUBLIC_IP` 和全部凭据：

```dotenv
TRADING_DATABASE_URL=postgresql+psycopg://trading:URL_ENCODED_POSTGRES_PASSWORD@TENCENT_PUBLIC_IP:5432/trading?sslmode=disable
TRADING_MINIO_ENDPOINT=TENCENT_PUBLIC_IP:9000
TRADING_MINIO_ACCESS_KEY=EXISTING_MINIO_APP_USER
TRADING_MINIO_SECRET_KEY=EXISTING_MINIO_APP_PASSWORD
TRADING_MINIO_BUCKET=trading-attachments
TRADING_MINIO_SECURE=false
```

数据库密码中的特殊字符必须百分号编码。管理员 Argon2 hash 继续使用单引号包裹，避免 `$` 被 Compose 展开。

```bash
docker compose config -q
docker compose build api
docker compose run --rm --no-deps api python -m app.security 'replace-with-admin-password'
# 将输出写入 TRADING_ADMIN_PASSWORD_HASH 后再启动
docker compose up -d --build
docker compose ps
docker compose logs migrate api caddy
curl --fail https://hahadeng.cn/health/ready
```

阿里安全组只需公开 TCP 80/443；如使用 HTTP/3，再公开 UDP 443。FastAPI 的 8000 不映射到宿主机。

## 5. Vercel

前端保持同源配置：浏览器请求 `https://se.vdcc.cn/api/*`，项目内的 HKG Edge Function 再转发到 `https://hahadeng.cn/api/*`。不需要因腾讯侧改走公网而修改前端。

如果 Vercel Project Settings 中存在 `VITE_GLOB_API_URL`，应删除该变量或将 Production 值设为空字符串。

## 6. 本地直连验证

替换腾讯公网 IP 和真实凭据：

```bash
psql 'postgresql://trading:URL_ENCODED_POSTGRES_PASSWORD@TENCENT_PUBLIC_IP:5432/trading?sslmode=disable'
mc alias set trading http://TENCENT_PUBLIC_IP:9000 EXISTING_MINIO_APP_USER EXISTING_MINIO_APP_PASSWORD
mc ls trading/trading-attachments
```

浏览器直接打开 `http://TENCENT_PUBLIC_IP:9001` 可访问 MinIO Console。当前是 HTTP，登录信息和控制台数据没有 TLS 保护。

## 7. 备份与验收

PostgreSQL 手工备份：

```bash
cd deploy/tencent
set -a
. ./.env
set +a
backup_dir="/srv/trading-backups/$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -m 700 -o "$(id -u)" -g "$(id -g)" "$backup_dir"
docker compose exec -T postgres pg_dump \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom > "$backup_dir/postgres.dump"
docker compose exec -T postgres pg_restore --list < "$backup_dir/postgres.dump" >/dev/null
```

现有 MinIO 继续使用它原有的备份流程，本仓库不接管。上线验收：

1. 腾讯 `postgres` 健康，现有 MinIO 容器 ID 和数据卷未变化。
2. 本地能连接公网 5432、9000、9001。
3. 阿里 `migrate` 退出码为 0，`https://hahadeng.cn/health/ready` 返回 ready。
4. `https://se.vdcc.cn` 能完成登录、CRUD、附件上传/读取/删除和 Excel 导出。
5. 腾讯和阿里重启后相关容器自动恢复。

## 8. 后续迁入 WireGuard

未来启用 WireGuard 时再单独实施以下变更：

1. 两台服务器建立私网地址和路由。
2. PostgreSQL 与现有 MinIO 端口改为只绑定 WireGuard 地址。
3. 阿里 `.env` 中数据库和 MinIO endpoint 改为腾讯 WireGuard 地址。
4. 腾讯安全组删除面向 `0.0.0.0/0` 的 5432、9000、9001 规则。

当前仓库不保留半启用的 WireGuard 配置。
