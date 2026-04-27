# mcnet.ps1 — Minecraft 群组服管理脚本 (Windows PowerShell)
# 用法: .\mcnet.ps1 <command>
param(
    [Parameter(Position = 0)]
    [string]$Command = "help"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO      = "abwuge/minecraft-server"
$BRANCH    = "main"
$BASE_URL  = "https://raw.githubusercontent.com/$REPO/$BRANCH"
$COMPOSE   = "docker compose"

# ---------- 内部工具 ----------

function Read-EnvVar([string]$Name) {
    if (-not (Test-Path ".env")) { return $null }
    $line = Get-Content ".env" | Where-Object { $_ -match "^${Name}=" } | Select-Object -First 1
    if ($line) { return $line.Substring($Name.Length + 1) }
    return $null
}

function New-RandomHex([int]$Bytes) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] $Bytes
    $rng.GetBytes($buf)
    return ([System.BitConverter]::ToString($buf)).Replace('-', '').ToLower()
}

function Invoke-Init {
    if (-not (Test-Path ".env")) {
        Write-Host "[init] .env 不存在, 正在生成..."
        $fwd  = New-RandomHex 24
        $rcon = New-RandomHex 16
        (Get-Content ".env.example") `
            -replace 'VELOCITY_FORWARDING_SECRET=change-me-to-random-hex', "VELOCITY_FORWARDING_SECRET=$fwd" `
            -replace 'RCON_PASSWORD=change-me-rcon', "RCON_PASSWORD=$rcon" |
            Set-Content ".env" -Encoding UTF8
        Write-Host "[init] .env 已生成 (密钥已随机生成)"
    } else {
        Write-Host "[init] .env 已存在, 跳过"
    }
}

function Invoke-Console([string]$Service) {
    $pw = Read-EnvVar "RCON_PASSWORD"
    if (-not $pw) {
        Write-Error "[error] 未找到 RCON_PASSWORD，请先运行 .\mcnet.ps1 init"
        exit 1
    }
    & docker compose exec -e "RCON_PASSWORD=$pw" $Service sh -c `
        'command -v mcrcon >/dev/null 2>&1 || apt-get install -y mcrcon >/dev/null; mcrcon -H 127.0.0.1 -P 25575 -p "$RCON_PASSWORD" -t'
}

function Invoke-Download([string]$File) {
    Invoke-WebRequest "$BASE_URL/$File" -OutFile $File
}

# ---------- 命令分发 ----------

switch ($Command) {
    "help" {
        @"
用法: .\mcnet.ps1 <command>

命令:
  init              生成 .env 并随机生成密钥 (up 时自动执行)
  build             构建所有镜像 (开发用)
  up                启动群组服
  down              停止并移除容器 (数据保留)
  restart           重启所有服务
  ps                查看容器状态
  logs              跟随所有日志
  logs-proxy        跟随 proxy 日志
  logs-main         跟随 main 日志
  logs-mirror       跟随 mirror 日志
  logs-create       跟随 create 日志
  console-main      进入 main RCON 控制台
  console-mirror    进入 mirror RCON 控制台
  console-create    进入 create RCON 控制台
  update            下载最新配置与镜像并滚动重启
  clean-data        危险: 删除所有 data\ 目录 (世界将丢失!)
"@
    }
    "init"  { Invoke-Init }
    "build" { Invoke-Expression "$COMPOSE build" }

    "up" {
        Invoke-Init
        Invoke-Expression "$COMPOSE up -d"
    }

    "down"    { Invoke-Expression "$COMPOSE down" }
    "restart" { Invoke-Expression "$COMPOSE restart" }
    "ps"      { Invoke-Expression "$COMPOSE ps" }
    "logs"    { Invoke-Expression "$COMPOSE logs -f --tail=200" }

    "logs-proxy"  { Invoke-Expression "$COMPOSE logs -f --tail=200 proxy" }
    "logs-main"   { Invoke-Expression "$COMPOSE logs -f --tail=200 main" }
    "logs-mirror" { Invoke-Expression "$COMPOSE logs -f --tail=200 mirror" }
    "logs-create" { Invoke-Expression "$COMPOSE logs -f --tail=200 create" }

    "console-main"   { Invoke-Console "main" }
    "console-mirror" { Invoke-Console "mirror" }
    "console-create" { Invoke-Console "create" }

    "update" {
        Write-Host "[update] 下载最新配置..."
        Invoke-Download "compose.yaml"
        Invoke-Download ".env.example"
        # 更新脚本自身
        Invoke-Download "mcnet.ps1"
        Write-Host "[update] 拉取最新镜像..."
        Invoke-Expression "$COMPOSE pull"
        Invoke-Expression "$COMPOSE up -d"
        Write-Host "[update] 更新完成，请用新脚本继续操作"
    }

    "clean-data" {
        $ans = Read-Host "确认删除所有 data\ 目录? 输入 YES"
        if ($ans -ne "YES") { Write-Host "已取消"; exit 0 }
        Remove-Item -Recurse -Force "data" -ErrorAction SilentlyContinue
        Write-Host "[clean-data] 已删除 data\"
    }

    default {
        Write-Error "[error] 未知命令: $Command`n运行 '.\mcnet.ps1 help' 查看帮助"
        exit 1
    }
}
