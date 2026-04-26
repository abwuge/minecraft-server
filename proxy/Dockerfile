FROM azul/zulu-openjdk:25-jre-headless

# Reuse apt downloads across builds (BuildKit cache mounts).
RUN rm -f /etc/apt/apt.conf.d/docker-clean
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      curl jq gettext-base ca-certificates tini \
      python3 python3-tomli

WORKDIR /data

# Resolve the latest Velocity version + build from the PaperMC API at build
# time, so :latest images always carry the newest proxy.
RUN set -eux; \
    version=$(curl -fsSL "https://api.papermc.io/v2/projects/velocity" | jq -r '.versions[-1]'); \
    build=$(curl -fsSL "https://api.papermc.io/v2/projects/velocity/versions/${version}" | jq -r '.builds[-1]'); \
    fname="velocity-${version}-${build}.jar"; \
    curl -fL --retry 3 \
      "https://api.papermc.io/v2/projects/velocity/versions/${version}/builds/${build}/downloads/${fname}" \
      -o /opt/velocity.jar; \
    echo "${version} build ${build}" > /opt/velocity.version

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

COPY proxy/templates /opt/proxy/templates
COPY proxy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 25565
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
