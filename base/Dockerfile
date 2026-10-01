FROM azul/zulu-openjdk:25-jre-headless AS system

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN rm -f /etc/apt/apt.conf.d/docker-clean
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        curl jq gettext-base ca-certificates tini \
        python3 python3-pip python3-venv python3-tomli

# Resolve package metadata separately from the runtime layers.
FROM system AS packages
ARG PACKAGE_REFRESH=manual
COPY scripts/resolve-packages.py /build/resolve-packages.py
COPY packages.toml /build/packages.toml
RUN set -eux; \
    mkdir -p /resolved/mods /resolved/mcdr-plugins; \
    python3 /build/resolve-packages.py --kind mods --registry /build/packages.toml \
        --download /resolved/mods > /resolved/mods.resolved.json; \
    python3 /build/resolve-packages.py --kind mcdr_plugins --registry /build/packages.toml \
        --download /resolved/mcdr-plugins > /resolved/mcdr-plugins.resolved.json; \
    jq '{mc_version, fabric_loader_version, fabric_installer_version}' \
        /resolved/mods.resolved.json > /resolved/fabric.json
RUN python3 - <<'PY'
from pathlib import Path
import zipfile
requirements = set()
for plugin in Path('/resolved/mcdr-plugins').iterdir():
    with zipfile.ZipFile(plugin) as archive:
        if 'requirements.txt' in archive.namelist():
            requirements.update(archive.read('requirements.txt').decode().splitlines())
Path('/resolved/requirements.txt').write_text('\n'.join(sorted(requirements)) + '\n')
PY
RUN find /resolved -exec touch -h -d @0 {} +

# Only Minecraft, Fabric loader or installer changes rebuild this layer.
FROM system AS fabric
COPY --link --from=packages /resolved/fabric.json /build/fabric.json
RUN set -eux; \
    MC=$(jq -r .mc_version /build/fabric.json); \
    LOADER=$(jq -r .fabric_loader_version /build/fabric.json); \
    INSTALLER=$(jq -r .fabric_installer_version /build/fabric.json); \
    mkdir -p /fabric; \
    curl -fL --retry 3 --output /fabric/fabric-server-launch.jar \
        "https://meta.fabricmc.net/v2/versions/loader/${MC}/${LOADER}/${INSTALLER}/server/jar"; \
    printf '%s-%s-%s\n' "$MC" "$LOADER" "$INSTALLER" > /fabric/.fabric-version; \
    cd /fabric && java -jar fabric-server-launch.jar nogui </dev/null; \
    test -d .fabric && test -d libraries; \
    rm -f eula.txt server.properties; \
    rm -rf logs; \
    find /fabric -exec touch -h -d @0 {} +

# Mod changes do not reinstall MCDR or its Python dependencies.
FROM system AS mcdr
ARG MCDR_VERSION=2.16.0
COPY --link --from=packages /resolved/requirements.txt /build/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv /opt/mcdr \
 && /opt/mcdr/bin/pip install --no-compile --upgrade pip \
 && /opt/mcdr/bin/pip install --no-compile "mcdreforged==${MCDR_VERSION}" -r /build/requirements.txt \
 && find /opt/mcdr -type d -name __pycache__ -prune -exec rm -rf {} + \
 && find /opt/mcdr -exec touch -h -d @0 {} +

FROM mcdr AS validated-plugins
COPY --link --from=packages /resolved/mcdr-plugins /opt/server/mcdr-plugins
COPY base/install-mcdr-plugins.py /build/install-mcdr-plugins.py
RUN /opt/mcdr/bin/python /build/install-mcdr-plugins.py /opt/server/mcdr-plugins

FROM system
ARG MCDR_VERSION=2.16.0
ENV PATH=/opt/mcdr/bin:$PATH

# Independent copy layers preserve their digests when another component changes.
COPY --link --from=mcdr /opt/mcdr /opt/mcdr
COPY --link --from=fabric /fabric/ /opt/server/
COPY --link --from=packages /resolved/mods /opt/server/mods
COPY --link --from=validated-plugins /opt/server/mcdr-plugins /opt/server/mcdr-plugins
COPY --link --from=packages /resolved/mods.resolved.json /resolved/mcdr-plugins.resolved.json /opt/server/
COPY --link scripts/resolve-packages.py /opt/server/resolve-packages.py
COPY --link packages.toml /opt/server/packages.toml
COPY --link base/install-mcdr-plugins.py /opt/server/install-mcdr-plugins.py
COPY --link base/mcdr/config.yml.tmpl /opt/server/mcdr-config.yml.tmpl

LABEL org.opencontainers.image.source="https://github.com/OWNER/minecraft-server" \
      org.opencontainers.image.description="Minecraft Fabric + MCDR base image" \
      mcdr.version="${MCDR_VERSION}"

WORKDIR /data
EXPOSE 25565 25575
ENTRYPOINT ["/usr/bin/tini", "--"]
