#!/usr/bin/env bash
# Minecraft 群组服管理脚本 (Linux / macOS / WSL2)
set -euo pipefail
cd "$(dirname "$0")"
BASE_URL="https://raw.githubusercontent.com/abwuge/minecraft-server/main"
CMD="${1:-help}"
[ "$#" -eq 0 ] || shift

_init() {
  python3 - <<'PY'
from pathlib import Path
import re, secrets, socket
p = Path('.env')
s = p.read_text() if p.exists() else Path('.env.example').read_text()
def get(key):
    m = re.search(r'(?m)^' + key + r'=(.*)$', s)
    return m.group(1).strip() if m else ''
def put(key, value):
    global s
    pattern = r'(?m)^' + key + r'=.*$'
    if re.search(pattern, s):
        s = re.sub(pattern, lambda _: key + '=' + value, s)
    else:
        s = s.rstrip() + '\n' + key + '=' + value + '\n'
for key, placeholder, length in [('VELOCITY_FORWARDING_SECRET', 'change-me-to-random-hex', 24), ('RCON_PASSWORD', 'change-me-rcon', 16)]:
    if get(key) in ('', placeholder): put(key, secrets.token_hex(length))
if not get('ONLINE_MODE'): put('ONLINE_MODE', 'true')
if not get('WHITE_LIST'): put('WHITE_LIST', get('ONLINE_MODE'))
if not get('MCSM_NODE_ADDRESS') and not get('MCSM_PUBLIC_URL'):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(('8.8.8.8', 80))
            address = sock.getsockname()[0]
        except OSError:
            address = '127.0.0.1'
    put('MCSM_NODE_ADDRESS', address)
p.write_text(s)
p.chmod(0o600)
print('[init] 配置已就绪')
PY
}

_service() {
  case "$1" in proxy|main|mirror|create|mcsm-web|mcsm-daemon|gateway) ;;
    *) echo "[error] 未知服务: $1" >&2; exit 1;; esac
}
_runtime() {
  docker compose run --rm --no-deps -T --entrypoint python3 \
    -v "$PWD:/mcnet-host" proxy /opt/mcnet/runtime.py "$@"
}
_up() {
  docker compose up -d --wait "$@"
  _runtime whitelist sync
}

case "$CMD" in
  help)
    cat <<'EOF'
用法: ./mcnet.sh 命令 [子命令]
  init                     初始化 .env
  up [服务]                启动并同步白名单
  down                     停止并移除容器，保留数据
  restart [服务]           重启服务
  ps [服务]                查看状态
  logs [服务]              跟随日志，如 logs proxy
  console 服务             进入控制台；Ctrl+P、Ctrl+Q 退出
  mode online|offline      切换认证并重启游戏服务；在线默认开白名单，离线默认关
  mode status              查看认证模式
  whitelist list           查看统一白名单
  whitelist add java 名称   添加 Java 玩家
  whitelist add bedrock "Gamertag" [--xuid XUID]
  whitelist remove java|bedrock 名称
  whitelist on|off|sync     开启、关闭或同步三个子服的白名单
  build [服务]             本地构建镜像
  update                   下载配置及最新镜像并启动
  clean-data               删除全部游戏与面板数据（需输入 YES）
服务: proxy、main、mirror、create、mcsm-web、mcsm-daemon
EOF
    ;;
  init) _init ;;
  up) _init; for s in "$@"; do _service "$s"; done; _up "$@" ;;
  build|restart|ps) for s in "$@"; do _service "$s"; done; docker compose "$CMD" "$@" ;;
  down) docker compose down "$@" ;;
  logs) for s in "$@"; do _service "$s"; done; docker compose logs -f --tail=200 "$@" ;;
  console)
    [ "$#" -eq 1 ] || { echo '用法: console 服务' >&2; exit 1; }
    _service "$1"; docker attach "mcnet-$1" ;;
  mode)
    [ "$#" -eq 1 ] || { echo '用法: mode online|offline|status' >&2; exit 1; }
    _init; _runtime mode "$1"
    if [ "$1" != status ]; then _up; fi ;;
  whitelist) _init; _runtime whitelist "$@" ;;
  update)
    for f in compose.yaml .env.example; do curl -fsSL "$BASE_URL/$f" -o "$f"; done
    curl -fsSL "$BASE_URL/mcnet.sh" -o mcnet.sh.tmp
    chmod +x mcnet.sh.tmp; mv mcnet.sh.tmp mcnet.sh
    _init; docker compose pull; _up ;;
  clean-data)
    read -r -p '确认删除全部 data/？输入 YES: ' ans
    [ "$ans" = YES ] || exit 1
    docker compose down; rm -rf data/ ;;
  *) echo "[error] 未知命令: $CMD；运行 ./mcnet.sh help 查看帮助" >&2; exit 1 ;;
esac
