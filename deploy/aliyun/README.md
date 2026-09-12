# 阿里云 API 部署

本目录在阿里云上部署 **FastAPI API + Caddy 反向代理**。数据库（PostgreSQL）和对象存储（MinIO）都在腾讯云，本目录不部署它们。阿里云通过公网连接腾讯云的 PostgreSQL（`:5432`）和 MinIO（`:9000`）。

```text
浏览器 -> 前端服务器:8090 -> hahadeng.cn/api/* -> 阿里云 Caddy:443 -> FastAPI:8000
                                                                    |
                                                        公网连腾讯 PostgreSQL / MinIO
```

## 服务依赖

`compose.yaml` 已正确编排三层依赖：

```text
migrate (alembic upgrade head)  -- 成功退出后启动 -->
api (fastapi run, 健康检查 /health/ready)  -- healthy 后启动 -->
caddy (80/443, 反向代理 api:8000)
```

关键设计：

- `migrate` 用 `restart: "no"` + `depends_on: service_completed_successfully`，保证迁移一次性成功，失败则 `api` 不启动。
- `api` 通过 `/health/ready` 健康检查后，`caddy` 才接管流量。
- `caddy` 启动后向 Let's Encrypt 申请 `hahadeng.cn` 证书并自动续期。

## 部署步骤

以下命令在**阿里云服务器**上执行。所有 `docker compose` 命令都必须在 `deploy/aliyun/` 目录下运行，因为 `build.context: ../..` 和 `./Caddyfile` 都依赖这个工作目录。

### 0. 前置：加 swap（2 GiB 阿里云必做）

首次构建 Python 镜像极易 OOM。先加 2 GB swap：

```bash
swapon --show   # 确认无现有 swap
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 1. 准备 `.env`

```bash
cd deploy/aliyun
cp .env.example .env
chmod 600 .env
```

**必须填写的项（不要用占位符直接启动）：**

| 变量 | 说明 |
|---|---|
| `TRADING_DATABASE_URL` | 把 `TENCENT_PUBLIC_IP` 换成腾讯公网 IP；`URL_ENCODED_POSTGRES_PASSWORD` 换成腾讯侧 `.env` 里的密码，**密码中的特殊字符必须百分号编码** |
| `TRADING_MINIO_ENDPOINT` | `腾讯公网IP:9000` |
| `TRADING_MINIO_ACCESS_KEY` / `TRADING_MINIO_SECRET_KEY` | 现有 MinIO **最小权限应用账号**（不是 root） |
| `TRADING_ADMIN_PASSWORD_HASH` | **先留空**，启动前用第 2 步命令生成 |
| `TRADING_API_DOMAIN` | 默认 `hahadeng.cn`（Caddy 用它申请证书） |

### 2. 生成管理员密码 hash

必须在 `docker compose up` 之前完成，因为 `api` 启动时需要 `TRADING_ADMIN_PASSWORD_HASH`：

```bash
docker compose build api
docker compose run --rm --no-deps api python -m app.security '你的管理员明文密码'
# 输出形如：$argon2id$...
```

把输出**完整粘贴**到 `.env` 的 `TRADING_ADMIN_PASSWORD_HASH=` 后面。

> ⚠️ 如果 hash 含 `$`，在 `.env` 里**用单引号包裹整行**，避免 Compose 把 `$` 当变量展开：
>
> ```dotenv
> TRADING_ADMIN_PASSWORD_HASH='$argon2id$v=19$m=...'
> ```

### 3. 校验 + 构建 + 启动

```bash
docker compose config -q          # 校验配置和变量替换
docker compose build api          # 构建 trading-cloud-api:production 镜像
docker compose up -d --build      # 启动 migrate -> api -> caddy
docker compose ps
docker compose logs migrate api caddy
```

`--build` 会触发 `context: ../..`（仓库根目录）的构建，所以**必须在 `deploy/aliyun/` 目录下执行**。

### 4. 验证

```bash
curl --fail https://hahadeng.cn/health/ready   # 通过 Caddy + 公网域名
docker compose logs -f api                      # 看启动日志
```

## 注意事项

### 镜像名与 `pull_policy: never`

三个服务都用 `image: trading-cloud-api:production` + `pull_policy: never`，意思是**只认本地构建的镜像，绝不拉远程**。所以：

- 首次部署必须 `docker compose build api` 先把镜像构建出来。
- 每次代码更新，需要重新 `build` 才会生效。

### `build.context: ../..` 的上下文

`build.context` 指向 `deploy/aliyun` 的上两级 = **仓库根目录**。这是对的（因为 Dockerfile 里要 `COPY pyproject.toml uv.lock ./` 和 `COPY app ./app`）。

但要注意：**必须在 `deploy/aliyun/` 目录下执行 `docker compose` 命令**，Compose 才能正确解析 `./Caddyfile` 等相对路径。如果在仓库根目录执行，会找不到这些文件。

### Caddy 的域名和证书

`Caddyfile` 第一行 `{$TRADING_API_DOMAIN}` 会从环境变量读取域名。Caddy 启动后会：

- 向 Let's Encrypt 申请 `hahadeng.cn` 的证书。
- 自动续期。

**前提**：`hahadeng.cn` 的 DNS A 记录必须指向阿里云服务器公网 IP，且阿里云安全组放行 TCP 80 和 443。

### 内存分配（2 GiB 阿里云）

| 服务 | mem_limit | cpus |
|---|---|---|
| `migrate` | 1250m | 1.5 |
| `api` | 1250m | 1.5 |
| `caddy` | 256m | 0.5 |

三者峰值合计约 1.5 GB，加上宿主机开销，2 GiB 内存 + 2 GB swap 基本够用。`migrate` 和 `api` 同时跑时可能接近上限，swap 是关键缓冲。

## 运维命令

```bash
docker compose ps
docker compose logs -f api caddy
docker compose restart api
docker compose up -d --build      # 代码更新后重建并重启
```

## 完整部署顺序（前后端分服务器）

从零部署整个系统时，顺序是：

1. **腾讯云**：部署 PostgreSQL（`deploy/tencent/`），确认 `:5432` 可连通。
2. **阿里云**：部署 API（本目录），连接腾讯 PostgreSQL + MinIO。
3. **前端服务器**：使用前端仓库 `deploy/tencent/compose.frontend.yaml` 构建 Vue 静态站点，由 Nginx 将 `/api/*` 转发到 `https://hahadeng.cn/api/*`。

Vercel 配置仍可保留，作为切换失败时的回滚入口；切换到前端服务器后，生产流量不再经过 Vercel Edge Function。

阿里云的 `migrate` 服务会在 `api` 启动前自动跑 `alembic upgrade head`，所以数据库 schema 迁移是自动的——前提是腾讯 PostgreSQL 已就绪且网络可达。
