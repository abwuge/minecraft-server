# Minecraft 生电群组服

由 MCSManager 原生 Docker 实例管理 Velocity 代理和三个 Fabric／Carpet 子服，同时支持 Java 版与基岩版接入。Minecraft、Mod 和插件在构建镜像时解析、下载；世界和运行配置保存在部署目录的 `data/` 下。

| 服务 | 容器 | 用途 |
|---|---|---|
| `proxy` | `mcnet-proxy` | Velocity、Geyser、Floodgate、ViaVersion、ViaBackwards 和跨服聊天 |
| `main` | `mcnet-main` | 主生电世界，生存模式 |
| `mirror` | `mcnet-mirror` | 镜像服，镜像任务通过 MirrorMcsmcdR 配置 |
| `create` | `mcnet-create` | 创造模式的超平坦试验场 |
| `mcsm-web` / `mcsm-daemon` | `mcnet-mcsm-web` / `mcnet-mcsm-daemon` | MCSManager 管理面板和守护进程 |
| `gateway` | `mcnet-gateway` | 默认 Caddy 网关，统一提供面板 80/443 |

玩家从代理进入 `main`，在游戏中用 `/server mirror`、`/server create` 切换子服，用 `/server main` 返回。代理通过 Velocity modern forwarding 与 FabricProxy-Lite 传递玩家信息；三个子服的游戏端口和 RCON 端口只在 Docker 网络内使用。

## 部署

镜像支持 `linux/amd64` 和 `linux/arm64`，包含 Java 25 运行时。主机需要 Docker；Windows 使用 Docker Desktop 的 Linux 容器模式。安装方法见 [Docker 官方文档](https://docs.docker.com/engine/install/)。

默认 JVM 最大堆内存合计为 13 GiB：主服 6 GiB、镜像服 3 GiB、创造服 3 GiB、代理 1 GiB。请为 JVM 额外内存、系统和管理面板预留空间，并按机器容量调整。

### Linux、macOS 或 WSL2

安装脚本还需要 Bash、curl 和 Python 3。

```bash
curl -fsSL https://raw.githubusercontent.com/abwuge/minecraft-server/main/install.sh | bash -s -- ./mcnet
cd mcnet
# 根据需要编辑自动生成的 .env
./mcnet.sh up
./mcnet.sh ps
./mcnet.sh logs main
```

安装脚本下载管理脚本和 Caddy 配置，生成带随机密钥的 `.env`，拉取镜像并启动服务。启动后，三个子服通过健康检查，代理才会启动；日志中出现 `Done (...)!` 表示 Minecraft 已完成启动。跟随日志时按 `Ctrl+C` 退出查看。

只启动游戏服务时使用：

```bash
./mcnet.sh up main mirror create proxy
```

### Windows PowerShell

```powershell
New-Item -ItemType Directory -Force mcnet | Out-Null
Set-Location mcnet
Invoke-WebRequest https://raw.githubusercontent.com/abwuge/minecraft-server/main/install.ps1 -OutFile install.ps1
.\install.ps1
# 根据需要编辑自动生成的 .env
.\mcnet.ps1 up
.\mcnet.ps1 ps
```

若 PowerShell 执行策略阻止运行脚本，可在当前会话执行 `Set-ExecutionPolicy -Scope Process Bypass`，再运行安装命令。管理命令与 Bash 版一致，例如 `.\mcnet.ps1 logs main`、`.\mcnet.ps1 update`。

## 玩家接入

| 入口 | 默认地址 | 环境变量 |
|---|---|---|
| Java 版 | `服务器地址:25565`，TCP | `PROXY_PORT` |
| 基岩版 | `服务器地址:19132`，UDP | `BEDROCK_PORT` |
| MCSManager 网页与守护进程 | `http://服务器地址` 或公网 HTTPS 域名 | `MCSM_PUBLIC_URL` |

外网接入需要在防火墙和路由器上放行相应协议。基岩版使用 UDP；仅放行 TCP 19132 无法连接。

### 白名单与控制台

三个子服共用 `data/whitelist/whitelist.json`，启动时合并已有白名单。统一接口会更新玩家身份并通过 RCON 让三个子服立即重载：

```bash
./mcnet.sh whitelist list
./mcnet.sh whitelist add java PlayerName
./mcnet.sh whitelist add bedrock "Xbox Gamertag"
./mcnet.sh whitelist remove bedrock "Xbox Gamertag"
./mcnet.sh whitelist on
./mcnet.sh whitelist off
./mcnet.sh whitelist sync
```

基岩版按 Xbox XUID 查询身份；已绑定 Java 的玩家使用绑定的 Java UUID，未绑定玩家使用 Floodgate UUID。查询服务不可用时，可在添加命令后提供 `--xuid XUID`；绑定状态仍需要查询 GeyserMC。已有白名单和玩家身份记录会保留。

使用 `./mcnet.sh console main` 进入主服控制台，支持 Minecraft 和 MCDR 的 `!!` 命令。退出时依次按 `Ctrl+P`、`Ctrl+Q`。`console proxy`、`console mirror` 和 `console create` 同样可用。

### 在线、离线与基岩版认证

默认在线模式：Java 验证正版账号，白名单开启。离线模式关闭 Java 正版验证，默认关闭白名单。基岩版在两种模式下均使用 Xbox/Floodgate 认证，默认无需绑定 Java 账号。Geyser 认证方式、Floodgate 绑定要求和密钥路径由镜像启动流程自动设置。

```bash
./mcnet.sh mode status
./mcnet.sh mode online
./mcnet.sh mode offline
```

切换会重启游戏服务，并按该模式的默认值设置白名单；随后可用 `whitelist on/off` 单独调整。Java 的在线与离线 UUID 不同，切换认证可能让玩家读取另一份背包和进度。统一白名单保留两种身份的对应关系。

`BEDROCK_PORT` 调整宿主机映射端口；Geyser 在容器内监听 19132。Floodgate 配置和 `key.pem` 保存在 `data/proxy/plugins/floodgate/`。ViaVersion 与 ViaBackwards 处理代理与后端之间的版本转换；Geyser 支持的客户端版本以[官方支持列表](https://geysermc.org/wiki/geyser/supported-versions/)为准。

## 配置与数据

所有路径均相对于部署目录。

```text
mcnet/
├── mcnet.py
├── .env
├── mcnet.sh / mcnet.ps1
└── data/
    ├── proxy/
    │   ├── velocity.toml
    │   └── plugins/                 # 代理插件及其运行配置
    ├── main/                       # mirror、create 使用相同结构
    │   ├── config.yml              # MCDR 启动命令和配置
    │   ├── config/                 # MCDR 插件配置
    │   ├── plugins/                # MCDR 插件链接或用户添加的插件
    │   └── server/
    │       ├── server.properties
    │       ├── config/             # Fabric Mod 配置
    │       ├── mods/               # 用户额外添加的 Mod
    │       └── world/              # 世界目录，由 level-name 决定
    └── mcsm/                       # 面板数据、守护进程数据和日志
```

数据使用宿主机目录挂载。更新或移除容器会保留 `data/`；`clean-data` 命令会删除整个目录，包括世界和面板数据。

### `.env` 的主要设置

| 设置 | 用途 |
|---|---|
| `GHCR_OWNER` | 镜像所属账号，默认 `abwuge` |
| `IMAGE_TAG` | 游戏镜像标签，默认 `latest` |
| `TZ` | 全部容器的时区，默认 `Asia/Shanghai`（UTC+8）；修改后执行 `mcnet up` |
| `IMAGE_PROXY` / `IMAGE_MAIN` / `IMAGE_MIRROR` / `IMAGE_CREATE` | 覆盖某个服务的完整镜像地址 |
| `VELOCITY_FORWARDING_SECRET` | 代理与子服共用的转发密钥 |
| `RCON_PASSWORD` | 子服 RCON 密码 |
| `ONLINE_MODE` / `WHITE_LIST` | Java 认证与统一白名单开关 |
| `MCSM_PUBLIC_URL` | 面板与守护进程共用的公网 HTTP(S) 地址 |
| `MAIN_XMS` / `MAIN_XMX` 等 | 首次生成子服 MCDR 配置时使用的 JVM 内存 |
| `PROXY_PORT` / `BEDROCK_PORT` | 玩家入口的宿主机端口 |
| `PROXY_XMS` / `PROXY_XMX` | 代理的 JVM 内存 |
| `MOTD_PROXY` | 首次生成 Velocity 配置时使用的 MiniMessage 文本 |

`.env` 不入库。`init` 只在文件不存在时生成随机密钥；已有 `.env` 会保留。

### 修改已有服务

`velocity.toml`、子服 `server.properties`、FabricProxy-Lite 配置和 MCDR `config.yml` 都在首次启动时由模板生成。后续在运行目录修改其它游戏设置；认证、白名单和密钥由环境变量统一控制。

- 子服内存：修改 `data/<子服>/config.yml` 中 `start_command` 的 `-Xms`、`-Xmx`，再重启该子服。`.env` 中的值用于新生成的配置。
- 游戏设置：修改 `data/<子服>/server/server.properties`，再重启该子服。
- 代理 MOTD 和路由：修改 `data/proxy/velocity.toml`，再重启代理。
- 代理内存：修改 `.env` 中的 `PROXY_XMS`、`PROXY_XMX`，再执行 `./mcnet.sh up proxy`。
- 宿主机端口或镜像地址：修改 `.env`，再执行 `./mcnet.sh up` 应用配置。

认证模式、白名单开关、转发密钥和 RCON 密码在每次启动时从环境变量应用。轮换密钥或密码后执行 `./mcnet.sh up`，让所有游戏服务使用一致的设置。

## 日常管理与更新

在部署目录执行：

```bash
./mcnet.sh help
./mcnet.sh ps
./mcnet.sh logs proxy
./mcnet.sh logs main
./mcnet.sh restart
./mcnet.sh down
```

`restart` 通过原生实例重启服务；`up` 应用配置并启动服务。镜像更新会重建对应容器，期间玩家连接会中断。

### 更新安装文件和全部服务镜像

```bash
./mcnet.sh update
```

该命令更新管理脚本、Caddy 配置和镜像，再通过 MCSManager 更新实例。重新执行原安装命令也会更新现有安装；`.env`、管理员、实例 ID 和 `data/` 保留。旧 Compose 安装会迁移为原生实例，并移除旧的 `compose.yaml`。

### 只更新游戏镜像

```bash
./mcnet.sh update main mirror create proxy
```

GitHub Actions 负责构建、发布镜像，服务器执行上述命令后才会部署新版本。公开 GHCR 镜像可匿名拉取；自己的私有镜像需要先 `docker login ghcr.io`。仓库与镜像的可见性分别配置，参见 [GitHub Packages 权限说明](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)。

`latest` 跟随最新发布。`sha-<Git提交SHA>` 表示对应代码构建的镜像，同一提交再次解析上游版本时仍可能更新该标签。需要固定某次构建时，用 `IMAGE_MAIN` 等变量指定 `ghcr.io/abwuge/mc-main@sha256:镜像摘要`。

### 查看实际版本

```bash
docker exec mcnet-main cat /opt/server/mods.resolved.json
docker exec mcnet-proxy cat /opt/proxy/plugins.resolved.json
docker exec mcnet-proxy cat /opt/velocity.version
```

解析结果记录 Minecraft、Fabric 和各 Mod／插件的版本。结合启动日志确认实际加载情况；用户手动放入的插件可能覆盖镜像内的同名文件。

## Mod、插件与版本选择

[packages.toml](packages.toml) 是包注册表，[resolve-packages.py](scripts/resolve-packages.py) 在构建时选择版本。

| 类型 | 内容 |
|---|---|
| 生电与基础 Mod | Fabric API、Carpet、Carpet TIS Addition、GugleCarpetAddition |
| 性能 Mod | Lithium、Krypton |
| 转发与权限 Mod | FabricProxy-Lite、LuckPerms、Vanilla Permissions |
| 可选 Mod | Servux、Syncmatica、SkinRestorer |
| Velocity 插件 | ChatHub、Geyser、Floodgate、ViaVersion、ViaBackwards |
| MCDR 插件 | PrimeBackup、MirrorMcsmcdR |

Minecraft 版本取所有必需 Mod 支持的正式游戏版本交集，再选其中最新的一版。Modrinth Fabric Mod 接受正式版和 Beta；因此 Minecraft 的正式版本也可以搭配 Beta Mod。可选 Mod 不限制版本交集，优先使用目标版本构建，缺失时尝试旧版回退或跳过。

代理插件独立解析版本：Modrinth 优先正式版，没有正式版时使用 Beta；Floodgate 来自 GeyserMC 下载 API。GitHub Release 来源使用正式发布，MCDR 插件可以通过 `tag` 固定版本。当前 MirrorMcsmcdR 固定为 `v1.4.1`，以避开 `v1.7.0` 的导入错误。

MCDR 插件声明的 Python 依赖会安装到镜像中，构建时还会检查插件能否导入。PrimeBackup 是否执行备份由 `data/<子服>/config/prime_backup/config.json` 控制；MirrorMcsmcdR 的镜像任务也需要单独配置。

内置 Fabric Mod 从 `/opt/server/mods` 加载。额外 Mod 放入 `data/<子服>/server/mods/`；代理插件放入 `data/proxy/plugins/`；MCDR 插件放入 `data/<子服>/plugins/`。启动脚本会刷新指向镜像内插件的链接，并保留用户放入的文件。同名手动 JAR 会优先保留，换回内置版本时先移走该文件，再重启服务。

## 镜像分层与下载量

三个子服继承 `mc-base`，只添加各自的模板和公共启动脚本。基础镜像将 Java／系统、Minecraft／Fabric 核心、MCDR／Python 依赖、Mod、MCDR 插件与配置分成独立层；代理的 Velocity 核心、插件和配置也分别打包。

发布使用 zstd 19 级压缩。`COPY --link` 保持组件层独立，固定产物时间戳使内容相同的层保留相同摘要。每次 CI 都重新解析上游包版本，未发生变化的组件继续复用原层。

以下为 2026-10-01 的实测参考，口径是 `linux/amd64` 的四个游戏镜像，压缩层按摘要去重：

| 情况 | 新层规模 |
|---|---|
| 首次完整拉取 | 合计约 373 MiB |
| 相同内容重新构建 | 0 MiB，基础镜像 14 个层摘要全部一致 |
| 只改子服配置 | 一个小层，测试中的文件内容约 1 KiB |
| 只更新 Mod、核心和依赖不变 | Mod 集合层约 12.6 MiB，加少量版本信息 |
| Minecraft／Fabric 核心变化 | 核心层约 121.5 MiB，另下载其他发生变化的层 |

Mod 目前按整个集合分层，单个 Mod 更新也会下载集合层。`docker image ls` 显示解压后的镜像大小；实际传输量取决于压缩后的新层和服务器已有缓存。MCSManager 镜像以官方镜像为基础，只增加自动配置和实例管理接口；Caddy 使用上游镜像。

## 构建与发布

### GitHub Actions

| 工作流 | 触发条件 | 发布内容 |
|---|---|---|
| [Build base image](.github/workflows/base-image.yml) | `main` 上的 `base/`、包注册表、解析脚本或对应工作流变更；每周一 04:17 UTC（北京时间 12:17）；手动触发 | `mc-base` |
| [Build server images](.github/workflows/build-images.yml) | `main` 上的 `proxy/`、`shared/`、`config/` 或对应工作流变更；基础镜像构建完成；手动触发 | `mc-proxy`、`mc-main`、`mc-mirror`、`mc-create` |

工作流构建 `linux/amd64`、`linux/arm64`，推送 `latest` 和 `sha-<Git提交SHA>` 标签。子服构建等待基础镜像完成；由基础工作流触发时，基础构建成功才会继续。

在 GitHub 的 Actions 页面可手动运行 `Build base image`，完成后自动触发游戏镜像构建。公开仓库长期没有活动时，GitHub 可能停用定时工作流；检查 Actions 状态并重新启用，规则见 [GitHub 官方说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)。

### 本地开发构建

从完整仓库构建，先生成基础镜像，再构建子服和代理。下例使用默认的 `GHCR_OWNER=abwuge`；修改所属账号时，基础镜像标签应与 `.env` 一致。

```bash
git clone https://github.com/abwuge/minecraft-server.git
cd minecraft-server
./mcnet.sh init
refresh="$(date +%s)"
docker build -f base/Dockerfile --build-arg PACKAGE_REFRESH="$refresh" \
  -t ghcr.io/abwuge/mc-base:latest .
for role in main mirror create; do
  docker build -f shared/Dockerfile.server --build-arg BASE_IMAGE=ghcr.io/abwuge/mc-base:latest \
    --build-arg SERVER_NAME="$role" -t "ghcr.io/abwuge/mc-$role:latest" .
done
docker build -f proxy/Dockerfile --build-arg PACKAGE_REFRESH="$refresh" -t ghcr.io/abwuge/mc-proxy:latest .
docker build -f mcsm/Dockerfile.daemon -t ghcr.io/abwuge/mc-mcsm-daemon:latest .
docker build -f mcsm/Dockerfile.web -t ghcr.io/abwuge/mc-mcsm-web:latest .
./mcnet.sh up
```

`PACKAGE_REFRESH` 用于重新解析上游版本。CI 使用每次运行的 ID；`SOURCE_DATE_EPOCH` 固定为 `0`，用于保持导出层的时间戳稳定。

## 管理面板与网关

MCSManager 官方提供 Web 和 Daemon 两个服务。本项目基于官方镜像自动配置节点、四个 Minecraft Java 版 Docker 实例及首次安装管理员。可在 `.env` 设置 `MCSM_ADMIN_USER` 和 `MCSM_ADMIN_PASSWORD`；密码留空时随机生成。首次凭据保存在 `data/mcsm/web/data/mcnet-credentials.json`，已有管理员保持原样。

Caddy 默认启用，在宿主机 80/443 提供统一入口：`/daemon/*` 转发到内部 24444，其余请求转发到内部 23333，WebSocket 自动透传。设置 `MCSM_PUBLIC_URL=https://你的域名` 后执行 `./mcnet.sh up`，面板使用该域名的 WSS 节点地址。Caddy 自动申请域名证书；HTTP 入口同时保留，供上层端口转发和 CDN 回源使用。首次证书签发需要公网能将 ACME 验证请求送达 Caddy。

四个游戏服务由 MCSManager 直接创建和管理。面板的启动、停止、重启及强制结束操作对应实际游戏容器，资源统计来自 Docker。停止后容器可以删除，世界和配置仍保存在宿主机 `data/`；下次启动使用同一实例 ID 和数据目录重新创建容器。守护进程重启后，按原生实例标签接管仍在运行的游戏容器。

文件管理器继续使用 `data/main`、`data/mirror`、`data/create`、`data/proxy`。安装和更新由 `mcnet` 统一进行，不再同时由 Compose 重建游戏容器。

## 仓库结构

```text
.github/workflows/          # 多架构构建与发布
base/                      # 分阶段基础镜像、MCDR 模板、插件导入检查
proxy/                     # Velocity 镜像与启动脚本
shared/                    # 三个子服共用的镜像与启动脚本
config/main/               # 主服首次启动模板
config/mirror/             # 镜像服首次启动模板
config/create/             # 创造服首次启动模板
config/proxy/              # Velocity 首次启动模板
config/gateway/            # Caddy 配置
scripts/resolve-packages.py # 包版本解析与下载
packages.toml              # Mod／插件注册表
mcnet.py                   # 原生 Docker 实例安装、迁移与更新
.env.example               # 部署参数示例
install.sh / install.ps1   # 安装脚本
mcnet.sh / mcnet.ps1       # 管理脚本
```
