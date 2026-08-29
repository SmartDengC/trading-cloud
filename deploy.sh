#!/bin/bash
# -*- coding: utf-8 -*-

# 部署脚本：拉取最新代码并重启 Docker 容器
# 使用方式：./deploy.sh

set -e  # 遇到任何错误立即退出

# ---------- 配置区域 ----------
BASE_DIR="/home/dengcong/github/trading-cloud"
DEPLOY_DIR="${BASE_DIR}/deploy/aliyun"
GIT_BRANCH="main"  # 可修改为你的分支名

# ---------- 颜色输出（便于观察） ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ---------- 1. 检查并切换至项目根目录 ----------
log_info "切换到项目根目录: $BASE_DIR"
if [ ! -d "$BASE_DIR" ]; then
    log_error "目录 $BASE_DIR 不存在，请检查路径！"
    exit 1
fi
cd "$BASE_DIR" || { log_error "无法进入目录 $BASE_DIR"; exit 1; }

# ---------- 2. 拉取最新代码 ----------
log_info "执行 git fetch --all ..."
git fetch --all || { log_error "git fetch 失败"; exit 1; }

log_info "执行 git pull origin $GIT_BRANCH ..."
git pull origin "$GIT_BRANCH" || { log_error "git pull 失败"; exit 1; }

log_info "代码拉取完成，当前最新 commit："
git log -1 --oneline

# ---------- 3. 切换至部署目录 ----------
log_info "切换到部署目录: $DEPLOY_DIR"
if [ ! -d "$DEPLOY_DIR" ]; then
    log_error "部署目录 $DEPLOY_DIR 不存在，请检查！"
    exit 1
fi
cd "$DEPLOY_DIR" || { log_error "无法进入目录 $DEPLOY_DIR"; exit 1; }

# ---------- 4. 执行 Docker Compose 构建并重启 ----------
log_info "执行 docker compose up -d --build ..."
docker compose up -d --build || { log_error "docker compose 执行失败"; exit 1; }

log_info "部署成功！当前运行中的容器："
docker compose ps

exit 0