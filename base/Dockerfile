# Base image for Minecraft subservers.
# Self-resolving: at build time, scripts/resolve-packages.py picks the newest MC
# version compatible with packages.toml, then fetches the matching Fabric loader,
# installer, server launcher, and all mod jars. No version pinning files needed.

FROM azul/zulu-openjdk:25-jre-headless

ARG MCDR_VERSION=2.14.7

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Reuse apt downloads across builds (BuildKit cache mounts). Drop the
# auto-clean hook that wipes the cache after each install.
RUN rm -f /etc/apt/apt.conf.d/docker-clean
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        curl jq gettext-base ca-certificates tini \
        python3 python3-pip python3-venv python3-tomli

# Install MCDReforged into /opt/mcdr venv (isolated from system python)
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv /opt/mcdr \
 && /opt/mcdr/bin/pip install --upgrade pip \
 && /opt/mcdr/bin/pip install "mcdreforged==${MCDR_VERSION}"
ENV PATH=/opt/mcdr/bin:$PATH

# Resolve everything: MC version, Fabric loader+installer, mod set.
# All driven by packages.toml; no manual version locking.
COPY scripts/resolve-packages.py /opt/server/resolve-packages.py
COPY packages.toml                /opt/server/packages.toml
RUN --mount=type=cache,target=/opt/server/download-cache \
    set -eux; \
    mkdir -p /opt/server/mods /opt/server/download-cache; \
    /usr/bin/python3 /opt/server/resolve-packages.py \
        --kind mods \
        --registry /opt/server/packages.toml \
        --download /opt/server/mods \
        > /opt/server/mods.resolved.json; \
    MC=$(jq -r .mc_version                /opt/server/mods.resolved.json); \
    LOADER=$(jq -r .fabric_loader_version /opt/server/mods.resolved.json); \
    INSTALLER=$(jq -r .fabric_installer_version /opt/server/mods.resolved.json); \
    echo "MC=${MC} loader=${LOADER} installer=${INSTALLER}"; \
    curl -fL --retry 3 \
      --create-dirs \
      --output /opt/server/download-cache/fabric-server-launch.jar \
      "https://meta.fabricmc.net/v2/versions/loader/${MC}/${LOADER}/${INSTALLER}/server/jar"; \
    cp /opt/server/download-cache/fabric-server-launch.jar /opt/server/fabric-server-launch.jar; \
    printf '%s-%s-%s\n' "$MC" "$LOADER" "$INSTALLER" > /opt/server/.fabric-version; \
    # Prefetch fabric libraries (libraries/, .fabric/) into /opt/server so
    # runtime never needs to download them. The bundled launcher unpacks deps
    # on first run, then exits because eula.txt is missing.
    # Mods are temporarily moved aside: with them in cwd, krypton/lithium spawn
    # non-daemon threads in onInitializeServer that keep the JVM alive forever
    # after Main.main returns from the EULA check.
    mv /opt/server/mods /opt/server/mods.staged; \
    cd /opt/server \
      && java -jar fabric-server-launch.jar nogui </dev/null; \
    mv /opt/server/mods.staged /opt/server/mods; \
    test -d /opt/server/.fabric && test -d /opt/server/libraries; \
    rm -f /opt/server/eula.txt /opt/server/server.properties; \
    rm -rf /opt/server/logs; \
    echo "fabric libraries prefetched into /opt/server/{libraries,.fabric}"

# MCDR config template (rendered into /data/config.yml on first start)
COPY base/mcdr/config.yml.tmpl /opt/server/mcdr-config.yml.tmpl

# Surface the resolved versions as image labels for traceability.
LABEL org.opencontainers.image.source="https://github.com/OWNER/minecraft-server" \
      org.opencontainers.image.description="Minecraft Fabric + MCDR base image" \
      mcdr.version="${MCDR_VERSION}"

WORKDIR /data
EXPOSE 25565 25575
ENTRYPOINT ["/usr/bin/tini", "--"]
