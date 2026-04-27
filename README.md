# Minecraft 生电群组服 (Velocity + Fabric)

Velocity 代理 + 两个 Fabric/Carpet 子服(`survival` 主生电世界 + `creative` 超平坦试验场)，docker compose 编排，配置即代码。

## 当前进度

- [x] 仓库骨架与 docker compose
- [x] Velocity 代理容器 (3.5.0-SNAPSHOT, MC 26 支持)
- [x] survival / creative 子服容器，基于自建 base 镜像
- [x] **自建 base 镜像** (`ghcr.io/<owner>/mc-base`)，含 Azul Zulu JDK 25 + MCDR + Fabric launcher
- [x] **GitHub Actions CI**：base / proxy / survival / creative 自动多架构构建并推送 GHCR
- [x] **packages.toml** 自动解析（Modrinth + GitHub Release + GeyserMC）
- [x] FabricProxy-Lite + Carpet + LuckPerms
- [x] Velocity modern forwarding
- [x] ChatHub 跨服聊天桥
- [x] Geyser + Floodgate (Bedrock 支持)
- [ ] restic 备份

## 镜像架构

```
ghcr.io/<owner>/mc-base:<sha>            # Azul Zulu JDK 25 + MCDR + Fabric launcher (核心层)
   ├── ghcr.io/<owner>/mc-survival:<sha> # FROM mc-base + survival 模板
   └── ghcr.io/<owner>/mc-creative:<sha> # FROM mc-base + creative 模板
ghcr.io/<owner>/mc-proxy:<sha>           # 独立, FROM azul/zulu-openjdk:25-jre-headless + Velocity
```

版本由 `packages.toml` 自动解析（Modrinth + GitHub Release + GeyserMC），构建时确定并打 `:sha-<sha>` 标签。改版本 = 改 packages.toml + PR。

## CI 工作流

| Workflow | 触发 | 作用 |
|---|---|---|
| `base-image.yml` | `base/**` 或 `packages.toml` 变更 / 每周一 / 手动 | 构建 base 镜像，多架构推 GHCR |
| `build-images.yml` | `proxy/`/`shared/`/`servers/`/`packages.toml` 变更 / base build 完成后 / 手动 | 矩阵构建 proxy/survival/creative |

GHCR 镜像默认 public（与仓库可见性一致）。如果你的 repo 是 private，首次推送后到 https://github.com/users/&lt;owner&gt;/packages/container/&lt;name&gt;/settings 把可见性改 public，否则服务器需要 `docker login ghcr.io`。

## 快速开始

```bash
cp .env.example .env
# 用以下命令生成随机密钥并填进 .env
openssl rand -hex 24   # -> VELOCITY_FORWARDING_SECRET
openssl rand -hex 16   # -> RCON_PASSWORD

make build
make up
make logs        # 等待几行 "Done (...)!"
```

连接 `<你的IP>:25565`（Java）或 `<你的IP>:19132`（Bedrock），会落到 `survival`。在游戏里 `/server creative` 切换到 creative。

打开 `http://<你的IP>:23333` 进入 MCSManager 面板，首次访问会引导创建管理员账号。在面板中添加已有的 Docker 实例（`mcnet-survival`、`mcnet-creative`、`mcnet-proxy`）即可在线输入指令、查看日志、管理文件。

## 目录结构

```
minecraft-server/
├── compose.yaml
├── Makefile
├── packages.toml           # Mod/plugin 注册表（单源）
├── scripts/
│   └── resolve-packages.py # 版本解析脚本
├── proxy/                  Velocity 代理镜像
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── templates/velocity.toml.tmpl
├── shared/                 子服共用
│   ├── Dockerfile.server
│   └── entrypoint.sh
├── base/                   Base 镜像（JDK + MCDR + Fabric）
│   ├── Dockerfile
│   └── mcdr/config.yml.tmpl
└── servers/
    ├── survival/
    │   └── templates/{server.properties,fabricproxy-lite.toml}.tmpl
    └── creative/
        └── templates/{server.properties,fabricproxy-lite.toml}.tmpl
```

## 常用命令

```bash
make help              # 列出所有 make 目标
make ps                # 容器状态
make logs-survival     # 跟 survival 日志
make console-survival  # RCON 交互(首次会自动 apt 装 mcrcon, 慢)
make upgrade           # docker compose pull && up -d
```

## 数据持久化

世界、配置、白名单、ops 全部在 docker named volume：
- `mcnet_proxy-data`
- `mcnet_survival-data`
- `mcnet_creative-data`

迁移到新机器：
```bash
make down
docker run --rm -v mcnet_survival-data:/d -v $PWD:/b alpine tar caf /b/survival.tar.zst -C /d .
# 拷到新机后反向 untar 到同名 volume
```

## 安全

- `.env` 不入 git
- 子服 25565/25575 不对宿主暴露，仅在 docker 内网
- Bedrock 端口 19132/udp 暴露到宿主

## 已安装的 Mod/Plugin

**子服 (Fabric):**
- fabric-api, fabric-carpet, carpet-tis-addition, gugle-carpet-addition
- fabricproxy-lite (modern forwarding)
- luckperms, vanilla-permissions
- lithium, krypton (性能优化)
- servux, syncmatica, skinrestorer (可选)

**代理 (Velocity):**
- chathub (跨服聊天)
- geyser + floodgate (Bedrock 支持)
- viaversion (跨版本客户端)
