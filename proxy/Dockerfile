FROM azul/zulu-openjdk:25-jre-headless

# Reuse apt downloads across builds (BuildKit cache mounts).
RUN rm -f /etc/apt/apt.conf.d/docker-clean
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      curl jq gettext-base ca-certificates tini \
      python3 python3-tomli

WORKDIR /data

# Resolve the latest Velocity version + build from the PaperMC v3 ("fill") API
# at build time, so :latest images always carry the newest proxy. The v2 API
# is frozen and missing newer release lines (e.g. 3.5.0-SNAPSHOT).
# Done in python rather than curl/jq because the API ships gzipped / brotli
# responses and basic curl doesn't always decode them in the build sandbox.
RUN python3 - <<'PY'
import json, sys, urllib.request, gzip, io
UA = "minecraft-server-base/1.0 (+self-hosted build)"
def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data)

meta = get("https://fill.papermc.io/v3/projects/velocity")
group = max(meta["versions"].keys(), key=lambda v: tuple(int(p) for p in v.split(".")))
version = meta["versions"][group][0]               # newest in that line, snapshots first
builds = get(f"https://fill.papermc.io/v3/projects/velocity/versions/{version}/builds")
b = builds[0]
dl = b["downloads"]["server:default"]
print(f"resolved {version} build {b['id']} -> {dl['name']}", file=sys.stderr)
with urllib.request.urlopen(urllib.request.Request(dl["url"], headers={"User-Agent": UA}), timeout=180) as r, \
     open("/opt/velocity.jar", "wb") as f:
    while True:
        chunk = r.read(1 << 16)
        if not chunk: break
        f.write(chunk)
with open("/opt/velocity.version", "w") as f:
    f.write(f"{version} build {b['id']} ({dl['name']})\n")
PY

# Resolve and bake the latest Velocity plugins listed in packages.toml.
COPY scripts/resolve-packages.py /opt/proxy/resolve-packages.py
COPY packages.toml                /opt/proxy/packages.toml
RUN set -eux; \
    mkdir -p /opt/proxy/plugins; \
    /usr/bin/python3 /opt/proxy/resolve-packages.py \
        --kind plugins \
        --registry /opt/proxy/packages.toml \
        --download /opt/proxy/plugins \
        > /opt/proxy/plugins.resolved.json

COPY config/proxy /opt/proxy/templates
COPY proxy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 25565
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
