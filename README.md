# Trading Cloud

`stock-exchange-reviews` 的独立 FastAPI 后端。生产环境连接外部 PostgreSQL/MinIO，Docker Compose 默认只运行迁移、API 和 Caddy；本地联调可通过 `local-infra` profile 启动内置 PostgreSQL/MinIO。

腾讯云运行 PostgreSQL 和现有 MinIO、阿里云运行 API/Caddy、Vercel 同源转发 API 的生产方案见 [deploy/README.md](deploy/README.md)。

不使用 Docker、直接在宿主机运行 API 的步骤请参阅 [LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md)。

## 本地启动

以下方式在宿主机直接运行 FastAPI，PostgreSQL 和 MinIO 也需要在本机启动。完整配置说明见 [LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md)。

### 1. 环境要求

- Python 3.14
- PostgreSQL 17
- MinIO 和 MinIO Client（`mc`）
- `uv`

### 2. 配置本地环境

```bash
cd /path/to/trading-cloud
cp .env.example .env
```

修改 `.env` 中的本地连接配置：

```dotenv
TRADING_DATABASE_URL=postgresql+psycopg://trading:你的数据库密码@127.0.0.1:5432/trading
TRADING_FRONTEND_ORIGINS=http://localhost:3000
TRADING_PUBLIC_BASE_URL=http://localhost:8000
TRADING_SESSION_SECURE=false
TRADING_SESSION_COOKIE_DOMAIN=
TRADING_MINIO_ENDPOINT=127.0.0.1:9000
TRADING_MINIO_ACCESS_KEY=trading-minio
TRADING_MINIO_SECRET_KEY=你的MinIO密码
TRADING_MINIO_BUCKET=trading-attachments
TRADING_MINIO_SECURE=false
```

`TRADING_ADMIN_USERNAME` 保持为管理员用户名。登录接口还需要配置
`TRADING_ADMIN_PASSWORD_HASH` 和 `TRADING_LOGIN_PRIVATE_KEY_B64`；管理员密码在安装依赖后生成，登录私钥可以提前生成：

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out /tmp/trading-login-private.pem
chmod 600 /tmp/trading-login-private.pem
openssl pkcs8 -topk8 -nocrypt \
  -in /tmp/trading-login-private.pem \
  -outform DER \
  -out /tmp/trading-login-private.der
chmod 600 /tmp/trading-login-private.der
base64 < /tmp/trading-login-private.der | tr -d '\n'
echo
```

将 `base64` 命令输出的整段内容（不要复制终端提示符）写入 `.env`：

```dotenv
TRADING_LOGIN_PRIVATE_KEY_B64=生成的Base64内容
```

这是 PKCS#8 DER 二进制的 Base64，不是带有 `-----BEGIN PRIVATE KEY-----` 和
`-----END PRIVATE KEY-----` 的 PEM 文本。值必须保持在同一行，不能包含空格、换行或
终端提示符 `%`。临时文件使用完后可以删除：

```bash
rm -f /tmp/trading-login-private.pem /tmp/trading-login-private.der
```

写入后可在不输出私钥的情况下验证格式和位数：

```bash
line=$(sed -n 's/^TRADING_LOGIN_PRIVATE_KEY_B64=//p' .env)
printf '%s' "$line" \
  | openssl base64 -d -A \
  | openssl pkcs8 -inform DER -nocrypt -out /dev/null

printf '%s' "$line" \
  | openssl base64 -d -A \
  | openssl pkey -inform DER -text -noout 2>/dev/null \
  | grep -E 'Private-Key|Private key'
```

第一条命令应成功退出，第二条命令应显示至少 `3072 bit`。如果看到
`登录加密密钥配置无效`，优先检查是否误复制了 PEM 标记、换行或末尾 `%`。

前端登录时从 `/api/auth/encryption-key` 获取公钥，使用
`RSA-OAEP-256+A256GCM` 加密信封提交密码；接口不接受明文 `password`。私钥只能保存在
后端环境变量中，不能提交到仓库、前端环境变量或构建产物。生产环境仍必须使用 HTTPS。

### 3. 启动 PostgreSQL 和 MinIO

```bash
psql postgres -c "CREATE ROLE trading LOGIN PASSWORD '你的数据库密码';"
psql postgres -c "CREATE DATABASE trading OWNER trading;"

mkdir -p minio-data
MINIO_ROOT_USER=trading-minio \
MINIO_ROOT_PASSWORD='你的MinIO密码' \
minio server ./minio-data --console-address :9001
```

保持 MinIO 终端运行，另开终端创建附件桶：

```bash
mc alias set local http://127.0.0.1:9000 trading-minio '你的MinIO密码'
mc mb --ignore-existing local/trading-attachments
mc anonymous set none local/trading-attachments
```

如果 PostgreSQL 用户或数据库已经存在，可以跳过对应的创建命令。

### 4. 安装依赖、迁移数据库并启动 API

```bash
uv sync --dev
uv run python -m app.security '你的登录密码'
uv run alembic upgrade head
```

将密码命令输出的 Argon2 hash 写入 `TRADING_ADMIN_PASSWORD_HASH`，然后启动 API：

```bash
uv run fastapi dev app/main.py --host 127.0.0.1 --port 8000
```

启动后访问：

- API：<http://localhost:8000>
- Swagger：<http://localhost:8000/docs>
- 存活检查：<http://localhost:8000/health/live>
- 就绪检查：<http://localhost:8000/health/ready>
- MinIO 控制台：<http://127.0.0.1:9001>

如果希望使用 Docker 同时启动本地 PostgreSQL、MinIO 和 API，请执行：

```bash
docker compose --profile local-infra -f compose.yaml -f compose.dev.yaml up -d --build
```

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

### 4. 生成登录加密私钥

登录接口只接受前端使用公钥加密后的密码。以下命令生成一次 3072 位 RSA 私钥，并将
PKCS#8 DER 内容转换为 Base64：

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out /tmp/trading-login-private.pem
chmod 600 /tmp/trading-login-private.pem
openssl pkcs8 -topk8 -nocrypt \
  -in /tmp/trading-login-private.pem \
  -outform DER \
  -out /tmp/trading-login-private.der
chmod 600 /tmp/trading-login-private.der
base64 < /tmp/trading-login-private.der | tr -d '\n'
echo
```

将输出的整段 Base64 内容写入阿里云服务器的 `deploy/aliyun/.env`：

```dotenv
TRADING_LOGIN_PRIVATE_KEY_B64=生成的Base64内容
```

不要复制终端提示符 `%`，不要添加 PEM 标记，也不要换行。写入后删除临时私钥文件：

```bash
rm -f /tmp/trading-login-private.pem /tmp/trading-login-private.der
chmod 600 .env
```

在 `deploy/aliyun/` 目录中验证 `.env` 中的值，不会输出私钥：

```bash
line=$(sed -n 's/^TRADING_LOGIN_PRIVATE_KEY_B64=//p' .env)
printf '%s' "$line" \
  | openssl base64 -d -A \
  | openssl pkcs8 -inform DER -nocrypt -out /dev/null

printf '%s' "$line" \
  | openssl base64 -d -A \
  | openssl pkey -inform DER -text -noout 2>/dev/null \
  | grep -E 'Private-Key|Private key'
```

第一条命令应成功退出，第二条命令应显示至少 `3072 bit`。确认配置有效后再执行
`docker compose config -q` 和服务启动命令。修改私钥后必须重新创建 API 容器，不能只修改
文件而不重启进程。

轮换私钥后重启 API；前端每次登录都会重新获取公钥。后端发布完成并确认 `/api/auth/encryption-key` 可用后，再发布前端。

### 5. 启动服务

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

HTTP 仍会明文传输会话 Cookie，且公钥获取容易被中间人替换，只用于临时联调。HTTPS 前端也不能调用 HTTP API，正式部署必须恢复原环境变量并使用基础 Compose 配置。

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

## 新浪行情代码配置

行情配置中的 symbol 是新浪行情接口使用的代码，不是本项目自定义的名称。新增或修改行情前，可以直接请求接口验证代码是否有效：

```text
https://hq.sinajs.cn/list=hkHSTECH,hf_XAU,hf_OIL
```

返回内容中的变量名就是对应的有效代码，例如 `hq_str_hkHSTECH`、`hq_str_hf_XAU` 和 `hq_str_hf_OIL`。如果某个变量返回空字符串，通常表示代码无效、已停用或当前接口不提供该品种。

常见代码前缀如下：

- `hk`：港股或港股指数，例如 `hkHSTECH`、`hkHSI`
- `hf_`：国际期货或现货，例如 `hf_XAU`、`hf_OIL`
- `sh` / `sz`：沪深 A 股或指数，例如 `sh000001`、`sz399001`
- `gb_`：表示美股/美国市场行情，例如 `gb_ixic`

新浪没有稳定公开、完整的代码列表页，实际使用时应以接口返回结果为准。

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
