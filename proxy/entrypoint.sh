#!/usr/bin/env bash
set -euo pipefail
DATA_DIR=/data
TPL_DIR=/opt/proxy/templates

cd "$DATA_DIR"

# Symlink baked plugins into the runtime plugins/ folder so Velocity loads
# them from the read-only image layer (zero copy, survives volume reset).
# User-supplied jars dropped directly into /data/plugins/ are kept as-is.
mkdir -p "$DATA_DIR/plugins"
shopt -s nullglob
for jar in /opt/proxy/plugins/*.jar; do
  base=$(basename "$jar")
  link="$DATA_DIR/plugins/$base"
  [ -e "$link" ] || ln -s "$jar" "$link"
done
shopt -u nullglob

# 渲染 velocity.toml (仅首次; 文件存在则保留用户修改)
if [ ! -f "$DATA_DIR/velocity.toml" ]; then
  envsubst < "$TPL_DIR/velocity.toml.tmpl" > "$DATA_DIR/velocity.toml"
fi

# 写 forwarding.secret 文件 (Velocity 默认从此文件读)
echo -n "${VELOCITY_FORWARDING_SECRET}" > "$DATA_DIR/forwarding.secret"
chmod 600 "$DATA_DIR/forwarding.secret"

exec java -Xms${XMS:-512M} -Xmx${XMX:-1G} \
  -XX:+UseG1GC -XX:G1HeapRegionSize=4M -XX:+UnlockExperimentalVMOptions \
  -XX:+ParallelRefProcEnabled -XX:+AlwaysPreTouch \
  -jar /opt/velocity.jar
