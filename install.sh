#!/usr/bin/env bash
# 安装或更新 MCSManager 管理的 Minecraft 群组服。
set -euo pipefail
BASE_URL="https://raw.githubusercontent.com/abwuge/minecraft-server/main"
INSTALL_DIR="${1:-.}"
for tool in docker curl python3; do
  command -v "$tool" >/dev/null || { echo "[error] 未找到 $tool" >&2; exit 1; }
done
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
revision=$(curl -fsSL https://api.github.com/repos/abwuge/minecraft-server/commits/main | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')
BASE_URL="https://raw.githubusercontent.com/abwuge/minecraft-server/$revision"
for file in .env.example mcnet.sh mcnet.py; do
  curl -fsSL "$BASE_URL/$file" -o "$file.tmp"
  mv "$file.tmp" "$file"
done
mkdir -p config/gateway
curl -fsSL "$BASE_URL/config/gateway/Caddyfile" -o config/gateway/Caddyfile
chmod +x mcnet.sh
./mcnet.sh update
printf '[install] 已就绪: %s\n' "$PWD"
