#!/usr/bin/env bash
# mcnet.sh — Minecraft 群组服管理脚本 (Linux / macOS / WSL2)
set -euo pipefail

REPO="abwuge/minecraft-server"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
COMPOSE="docker compose"
CMD="${1:-help}"

# ---------- 内部工具 ----------

_read_env() {
  grep "^${1}=" .env 2>/dev/null | cut -d= -f2-
}

_init() {
  if [ ! -f .env ]; then
    echo "[init] .env 不存在, 正在生成..."
    FWD=$(python3 -c 'import secrets; print(secrets.token_hex(24), end="")')
    RCON=$(python3 -c 'import secrets; print(secrets.token_hex(16), end="")')
    sed \
      -e "s|VELOCITY_FORWARDING_SECRET=change-me-to-random-hex|VELOCITY_FORWARDING_SECRET=${FWD}|" \
      -e "s|RCON_PASSWORD=change-me-rcon|RCON_PASSWORD=${RCON}|" \
      .env.example > .env
    echo "[init] .env 已生成 (密钥已随机生成)"
  else
    echo "[init] .env 已存在, 跳过"
  fi
}

_console() {
  local SERVICE="$1"
  local PW
  PW=$(_read_env RCON_PASSWORD)
  if [ -z "$PW" ]; then
    echo "[error] 未找到 RCON_PASSWORD，请先运行 ./mcnet.sh init" >&2
    exit 1
  fi
  $COMPOSE exec -e "RCON_PASSWORD=${PW}" "$SERVICE" sh -c \
    'command -v mcrcon >/dev/null 2>&1 || apt-get install -y mcrcon >/dev/null; \
     mcrcon -H 127.0.0.1 -P 25575 -p "$RCON_PASSWORD" -t'
}

_download() {
  local FILE="$1"
  curl -fsSL "${BASE_URL}/${FILE}" -o "${FILE}"
}

# ---------- 命令分发 ----------

case "$CMD" in
  help)
    cat <<'EOF'
用法: ./mcnet.sh <command>

命令:
  init              生成 .env 并随机生成密钥 (up 时自动执行)
  build             构建所有镜像 (开发用)
  up                启动群组服
  down              停止并移除容器 (数据保留)
  restart           重启所有服务
  ps                查看容器状态
  logs              跟随所有日志
  logs-proxy        跟随 proxy 日志
  logs-main         跟随 main 日志
  logs-mirror       跟随 mirror 日志
  logs-create       跟随 create 日志
  console-main      进入 main RCON 控制台
  console-mirror    进入 mirror RCON 控制台
  console-create    进入 create RCON 控制台
  update            下载最新配置与镜像并滚动重启
  clean-data        危险: 删除所有 data/ 目录 (世界将丢失!)
EOF
    ;;

  init)   _init ;;
  build)  $COMPOSE build ;;

  up)
    _init
    $COMPOSE up -d
    ;;

  down)    $COMPOSE down ;;
  restart) $COMPOSE restart ;;
  ps)      $COMPOSE ps ;;
  logs)    $COMPOSE logs -f --tail=200 ;;

  logs-proxy)  $COMPOSE logs -f --tail=200 proxy ;;
  logs-main)   $COMPOSE logs -f --tail=200 main ;;
  logs-mirror) $COMPOSE logs -f --tail=200 mirror ;;
  logs-create) $COMPOSE logs -f --tail=200 create ;;

  console-main)   _console main ;;
  console-mirror) _console mirror ;;
  console-create) _console create ;;

  update)
    echo "[update] 下载最新配置..."
    _download compose.yaml
    _download .env.example
    # 更新脚本自身 (写入临时文件再替换, 避免覆盖正在运行的脚本)
    curl -fsSL "${BASE_URL}/mcnet.sh" -o mcnet.sh.tmp
    chmod +x mcnet.sh.tmp
    mv mcnet.sh.tmp mcnet.sh
    echo "[update] 拉取最新镜像..."
    $COMPOSE pull
    $COMPOSE up -d
    echo "[update] 更新完成, 请用新脚本继续操作"
    ;;

  clean-data)
    read -r -p "确认删除所有 data/ 目录? 输入 YES: " ans
    [ "$ans" = "YES" ] || exit 1
    rm -rf data/
    echo "[clean-data] 已删除 data/"
    ;;

  *)
    echo "[error] 未知命令: $CMD" >&2
    echo "运行 './mcnet.sh help' 查看帮助" >&2
    exit 1
    ;;
esac
