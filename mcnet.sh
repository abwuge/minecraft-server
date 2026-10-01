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

_image() {
  python3 - <<'PYIMAGE'
from pathlib import Path
values = dict(line.split('=', 1) for line in Path('.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
print(values.get('IMAGE_PROXY') or f"ghcr.io/{values.get('GHCR_OWNER') or 'abwuge'}/mc-proxy:{values.get('IMAGE_TAG') or 'latest'}")
PYIMAGE
}
_manager() {
  _init
  docker network inspect mcnet >/dev/null 2>&1 || docker network create mcnet >/dev/null
  if [ "$1" = update ]; then docker pull "$(_image)"; fi
  docker run --rm --network mcnet --env-file .env \
    -v "$PWD:/mcnet-host" -v "$PWD/data/whitelist:/whitelist" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    --entrypoint python3 "$(_image)" /mcnet-host/mcnet.py "$@"
}
_refresh() {
  local revision source_url
  revision=$(curl -fsSL https://api.github.com/repos/abwuge/minecraft-server/commits/main | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')
  source_url="https://raw.githubusercontent.com/abwuge/minecraft-server/$revision"
  for f in .env.example mcnet.py mcnet.sh; do
    curl -fsSL "$source_url/$f" -o "$f.tmp"
    mv "$f.tmp" "$f"
  done
  mkdir -p config/gateway
  curl -fsSL "$source_url/config/gateway/Caddyfile" -o config/gateway/Caddyfile
  chmod +x mcnet.sh
}
case "$CMD" in
  help)
    cat <<'EOF'
用法: ./mcnet.sh 命令 [子命令]
  init                     初始化 .env
  up [服务]                应用配置并通过 MCSManager 启动容器
  down                     停止全部服务，保留数据
  restart [服务]           重启服务
  ps                       查看容器和面板状态
  logs [服务]              跟随日志，默认 proxy
  console 服务             进入控制台；Ctrl+P、Ctrl+Q 退出
  mode online|offline|status
  whitelist list|add|remove|on|off|sync
  update [服务]            下载脚本和镜像并更新；原安装命令也可更新
  clean-data               删除全部游戏与面板数据（需输入 YES）
服务: proxy、main、mirror、create、mcsm-web、mcsm-daemon、gateway
EOF
    ;;
  init) _init ;;
  up|down|restart|ps|mode|whitelist) _manager "$CMD" "$@" ;;
  update) _refresh; _manager update "$@" ;;
  logs) docker logs -f --tail=200 "mcnet-${1:-proxy}" ;;
  console)
    [ "$#" -eq 1 ] || { echo '用法: console 服务' >&2; exit 1; }
    docker attach "mcnet-$1" ;;
  clean-data)
    read -r -p '确认删除全部 data/？输入 YES: ' ans
    [ "$ans" = YES ] || exit 1
    _manager down; rm -rf data/ ;;
  *) echo "[error] 未知命令: $CMD；运行 ./mcnet.sh help 查看帮助" >&2; exit 1 ;;
esac
