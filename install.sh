#!/usr/bin/env bash
# install.sh — Minecraft 群组服一键安装脚本 (Linux / macOS / WSL2)
#
# 用法:
#   curl -fsSL https://raw.githubusercontent.com/abwuge/minecraft-server/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/abwuge/minecraft-server/main/install.sh | bash -s -- ./my-server
set -euo pipefail

REPO="abwuge/minecraft-server"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
INSTALL_DIR="${1:-.}"

# ---------- 样式 ----------
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

info()  { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[!]${RESET} $*"; }
error() { echo -e "${RED}[✗]${RESET} $*" >&2; exit 1; }
step()  { echo -e "\n${BOLD}$*${RESET}"; }

echo -e "${BOLD}"
cat <<'BANNER'
  __  __  _____   _   _   ___  _____
 |  \/  |/ ____| | \ | | |_ _||_   _|
 | \  / | |      |  \| |  | |   | |
 | |\/| | |      | . ` |  | |   | |
 | |  | | |____  | |\  | _| |_  | |
 |_|  |_|\_____| |_| \_||_____| |_|

  Minecraft 群组服 — 一键安装
BANNER
echo -e "${RESET}"

# ---------- 环境检查 ----------
step "1/4 检查运行环境..."

command -v docker >/dev/null 2>&1    || error "未找到 docker，请先安装 Docker: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || error "未找到 docker compose plugin，请升级 Docker Desktop 或安装 Compose V2"
command -v curl >/dev/null 2>&1      || error "未找到 curl，请先安装"
command -v python3 >/dev/null 2>&1   || error "未找到 python3，请先安装 Python 3.6+"

info "Docker:         $(docker --version)"
info "Docker Compose: $(docker compose version)"

# ---------- 创建目录 ----------
step "2/4 准备安装目录..."

if [ "$INSTALL_DIR" != "." ]; then
  mkdir -p "$INSTALL_DIR"
  info "安装目录: $(realpath "$INSTALL_DIR")"
fi
cd "$INSTALL_DIR"

# ---------- 下载文件 ----------
step "3/4 下载配置文件..."

curl -fsSL "${BASE_URL}/compose.yaml"  -o compose.yaml  && info "compose.yaml"
curl -fsSL "${BASE_URL}/.env.example"  -o .env.example  && info ".env.example"
curl -fsSL "${BASE_URL}/mcnet.sh"      -o mcnet.sh      && info "mcnet.sh"
chmod +x mcnet.sh

# ---------- 初始化 ----------
step "4/4 初始化配置与镜像..."
./mcnet.sh init

echo ""
info "拉取 Docker 镜像 (首次可能需要几分钟)..."
docker compose pull

# ---------- 完成 ----------
echo ""
echo -e "${BOLD}${GREEN}=========================================${RESET}"
echo -e "${BOLD}${GREEN}  安装完成!${RESET}"
echo -e "${GREEN}  目录: $(pwd)${RESET}"
echo -e "${GREEN}  启动: ./mcnet.sh up${RESET}"
echo -e "${GREEN}  帮助: ./mcnet.sh help${RESET}"
echo -e "${BOLD}${GREEN}=========================================${RESET}"
