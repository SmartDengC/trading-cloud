# 双云生产部署

生产拓扑固定为：

```text
se.vdcc.cn (Vercel)
  /api/* -> https://hahadeng.cn/api/*
                 |
                 v
       阿里云 Caddy + FastAPI (10.66.66.2)
                 |
              WireGuard
                 |
                 v
       腾讯云 PostgreSQL + MinIO (10.66.66.1)
```

腾讯云不承载公网 Web 域名。PostgreSQL 和 MinIO 只绑定 WireGuard 地址，不要在腾讯云安全组中开放 TCP 5432、9000 或 9001。

## 1. 主机准备

两台服务器均需安装 Docker Engine 和 Docker Compose v2。Docker 请按云服务器发行版使用官方安装方式；以下命令以 Debian/Ubuntu 为例安装 WireGuard 依赖：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl wireguard
docker compose version
```

中国大陆服务器如果无法拉取 Docker Hub 基础镜像，应先配置云厂商提供的 Docker 镜像加速。MinIO 源码依赖默认使用 `https://proxy.golang.org`；如该地址不可达，可在腾讯云 `.env` 中把 `MINIO_GOPROXY` 改为可信的 Go module proxy。

两台 2/4 GiB 主机都应至少配置 2 GiB swap。执行前先用 `swapon --show` 和 `free -h` 检查，避免重复创建：

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

MinIO 社区版已经转为源码分发。本部署从官方最后的安全版本 `RELEASE.2025-10-15T17-29-55Z` 构建，不依赖第三方运行镜像。单机单盘 MinIO 不提供节点或磁盘冗余，不能把本机数据卷当作备份。

## 2. 建立 WireGuard

分别在两台服务器生成密钥：

```bash
sudo install -d -m 700 /etc/wireguard
sudo sh -c 'umask 077; wg genkey | tee /etc/wireguard/privatekey | wg pubkey > /etc/wireguard/publickey'
sudo cat /etc/wireguard/publickey
```

用 `deploy/wireguard/tencent-wg0.conf.example` 和 `deploy/wireguard/aliyun-wg0.conf.example` 生成各自的 `/etc/wireguard/wg0.conf`，替换其中的私钥、公钥和腾讯云公网 IP。私钥及最终配置不得写入仓库，配置文件必须保持 `600` 权限：

```bash
sudo chmod 600 /etc/wireguard/wg0.conf
sudo systemctl enable --now wg-quick@wg0
sudo wg show
```

安全组规则：

- 腾讯云入站只允许阿里云公网 IP 访问 UDP 51820；SSH 只允许管理 IP。
- 阿里云向公网开放 TCP 80/443；如需 HTTP/3 再开放 UDP 443；SSH 只允许管理 IP。
- 两端都不要向公网开放 TCP 5432、8000、9000、9001。

Docker 发布端口时需要 `wg0` 已存在。建议两台服务器都添加 Docker 的 systemd 顺序约束：

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo cp deploy/systemd/docker-wireguard.conf /etc/systemd/system/docker.service.d/wireguard.conf
sudo systemctl daemon-reload
sudo systemctl restart docker
```

验证隧道：

```bash
# 腾讯云执行
ping -c 3 10.66.66.2

# 阿里云执行
ping -c 3 10.66.66.1
```

## 3. 腾讯云数据服务

在腾讯云服务器检出本仓库后执行：

```bash
cd deploy/tencent
cp .env.example .env
chmod 600 .env
```

为 PostgreSQL、MinIO root 和 MinIO 应用用户生成三个不同的随机密码，例如：

```bash
openssl rand -base64 36
```

编辑 `.env` 后校验并启动：

```bash
docker compose config -q
docker compose build minio
docker compose up -d
docker compose ps
docker compose logs minio-init
```

`minio-init` 正常完成后状态为 `Exited (0)`。如需轮换 `MINIO_APP_PASSWORD`，先删除旧应用用户再重新运行初始化任务；仅修改 `.env` 不会覆盖已存在用户的密码。

确认服务只绑定隧道地址：

```bash
ss -lnt | grep -E '10\.66\.66\.1:(5432|9000)'
```

## 4. 阿里云 API

确保 `hahadeng.cn` 的 A/AAAA 记录只指向阿里云服务器，并已完成对应的阿里云接入备案。然后执行：

```bash
cd deploy/aliyun
cp .env.example .env
chmod 600 .env
```

配置要求：

- `TRADING_DATABASE_URL` 中的密码必须与腾讯云 `POSTGRES_PASSWORD` 相同；URL 特殊字符必须百分号编码。
- `TRADING_MINIO_SECRET_KEY` 必须与腾讯云 `MINIO_APP_PASSWORD` 相同。
- `TRADING_ADMIN_PASSWORD_HASH` 使用单引号包住完整 Argon2 hash，避免 `$` 被 Compose 展开。

生成管理员密码 hash：

```bash
docker compose build api
docker compose run --rm --no-deps api python -m app.security 'replace-with-admin-password'
```

校验、启动并查看迁移结果：

```bash
docker compose config -q
docker compose up -d --build
docker compose ps
docker compose logs migrate api caddy
curl --fail https://hahadeng.cn/health/ready
```

API 容器没有宿主机端口映射。公网只能通过 Caddy 的 80/443 进入。

## 5. Vercel

前端生产配置使用空的 `VITE_GLOB_API_URL`，浏览器只请求 `https://se.vdcc.cn/api/*`。仓库根目录 `vercel.json` 再将请求代理到 `https://hahadeng.cn/api/*`。

如果 Vercel Project Settings 中设置了 `VITE_GLOB_API_URL`，Production 值也必须设为空字符串，或直接删除该变量，让仓库内的 `.env.production` 生效。发布后检查：

```bash
curl -I https://se.vdcc.cn/api/auth/session
```

未登录时返回 401 是预期结果。响应不得包含 Vercel 公共缓存命中，登录后的 Cookie 应为 `se.vdcc.cn` 的 HttpOnly、Secure、SameSite=Lax host-only Cookie。

## 6. 手工备份与校验

以下备份保存在腾讯云本机，只适合误操作恢复，不属于异地灾备：

```bash
cd deploy/tencent
set -a
. ./.env
set +a
backup_dir="/srv/trading-backups/$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -m 700 -o "$(id -u)" -g "$(id -g)" "$backup_dir/minio"

docker compose exec -T postgres pg_dump \
  -U "${POSTGRES_USER:-trading}" \
  -d "${POSTGRES_DB:-trading}" \
  --format=custom > "$backup_dir/postgres.dump"

docker compose run --rm --no-deps \
  -v "$backup_dir/minio:/backup" \
  minio-init \
  'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mirror --overwrite "local/$TRADING_MINIO_BUCKET" /backup'

(cd "$backup_dir" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
(cd "$backup_dir" && sha256sum -c SHA256SUMS)
docker compose exec -T postgres pg_restore --list < "$backup_dir/postgres.dump" >/dev/null
```

上线前至少执行一次备份校验。后续应把 `/srv/trading-backups` 定期复制到另一台服务器或独立对象存储；同机数据卷和同机备份会同时受到磁盘故障影响。

## 7. 验收清单

1. 阿里云能连接 `10.66.66.1:5432` 和 `10.66.66.1:9000`，公网不能连接这些端口。
2. 腾讯云 `postgres`、`minio` 健康，`minio-init` 退出码为 0。
3. 阿里云 `migrate` 退出码为 0，`api`、`caddy` 健康。
4. `https://hahadeng.cn/health/ready` 返回 `{"status":"ready"}`。
5. 在 `https://se.vdcc.cn` 完成登录、CRUD、附件上传/查看/删除和 Excel 导出。
6. 两台服务器重启后 WireGuard、Docker 和全部服务自动恢复。
