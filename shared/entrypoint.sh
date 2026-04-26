#!/usr/bin/env bash
# Subserver entrypoint.
#
# Layout:
#   /data/                MCDR working directory (volume)
#     config.yml          rendered from /opt/server/mcdr-config.yml.tmpl on first run
#     plugins/            user MCDR plugins
#     logs/               MCDR logs
#     server/             MC working directory (cwd of the java process)
#       server.properties rendered from per-subserver template on first run
#       config/           rendered configs (FabricProxy-Lite, ...)
#       mods/             user-added mods (optional; baked mods load via fabric.addMods)
#       world/            world data
#
# Mods baked into the base image at /opt/server/mods are loaded read-only via
# `-Dfabric.addMods=`, so no copy / sync to the data volume is needed.
set -euo pipefail

DATA=/data
SERVER=$DATA/server
TPL=/opt/server/templates
MCDR_TPL=/opt/server/mcdr-config.yml.tmpl

log() { echo "[entrypoint] $*"; }

mkdir -p "$DATA/plugins" "$DATA/logs" "$SERVER/config" "$SERVER/mods"

# ---------- 1. EULA ----------
echo "eula=true" > "$SERVER/eula.txt"

# ---------- 2. MCDR config (render once, preserve user edits) ----------
if [ ! -f "$DATA/config.yml" ]; then
  log "render MCDR config.yml"
  envsubst < "$MCDR_TPL" > "$DATA/config.yml"
fi

# ---------- 3. Per-subserver templates ----------
# Render only when the target file is missing, so user edits survive restarts.
# Delete the file (or the whole /data) to pick up template changes from a new
# image.
shopt -s nullglob
for tpl in "$TPL"/*.tmpl; do
  base=$(basename "$tpl" .tmpl)
  case "$base" in
    server.properties)     out="$SERVER/server.properties" ;;
    fabricproxy-lite.toml) out="$SERVER/config/FabricProxy-Lite.toml" ;;
    *)                     out="$SERVER/$base" ;;
  esac
  if [ ! -e "$out" ]; then
    log "render $base -> $out"
    envsubst < "$tpl" > "$out"
  fi
done
shopt -u nullglob

# ---------- 4. Fabric launcher symlink ----------
# The launcher jar lives in the read-only base image; symlink it next to the
# world so the java cwd resolution works without copying.
LAUNCHER=$SERVER/fabric-server-launch.jar
[ -e "$LAUNCHER" ] || ln -s /opt/server/fabric-server-launch.jar "$LAUNCHER"

# Reuse the libraries (sponge-mixin, fabric-loader, log4j, ...) prefetched
# into the base image so the server starts fully offline.
[ -e "$SERVER/.fabric"   ] || ln -s /opt/server/.fabric   "$SERVER/.fabric"
[ -e "$SERVER/libraries" ] || ln -s /opt/server/libraries "$SERVER/libraries"
[ -e "$SERVER/versions"  ] || ln -s /opt/server/versions  "$SERVER/versions"

# ---------- 5. Launch via MCDR ----------
cd "$DATA"
# Idempotent: only fills in missing files (e.g. permission.yml on first run),
# never overwrites the rendered config.yml.
mcdreforged init >/dev/null

log "starting MCDR (Xms=$XMS Xmx=$XMX)"
exec mcdreforged start
