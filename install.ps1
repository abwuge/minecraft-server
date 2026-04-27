# install.ps1 — Minecraft 群组服一键安装脚本 (Windows PowerShell)
#
# 用法 (在 PowerShell 中运行):
#   irm https://raw.githubusercontent.com/abwuge/minecraft-server/main/install.ps1 | iex
#   .\install.ps1 -InstallDir C:\mcnet
param(
    [string]$InstallDir = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO     = "abwuge/minecraft-server"
$BRANCH   = "main"
$BASE_URL = "https://raw.githubusercontent.com/$REPO/$BRANCH"

function Write-Step([string]$Msg) { Write-Host "`n$Msg" -ForegroundColor White }
function Write-Ok([string]$Msg)   { Write-Host "[✓] $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "[!] $Msg" -ForegroundColor Yellow }
function Write-Fail([string]$Msg) { Write-Host "[✗] $Msg" -ForegroundColor Red; exit 1 }

Write-Host @"

  __  __  _____   _   _   ___  _____
 |  \/  |/ ____| | \ | | |_ _||_   _|
 | \  / | |      |  \| |  | |   | |
 | |\/| | |      | . `` |  | |   | |
 | |  | | |____  | |\  | _| |_  | |
 |_|  |_|\_____| |_| \_||_____| |_|

  Minecraft 群组服 — 一键安装

"@ -ForegroundColor Cyan

# ---------- 环境检查 ----------
Write-Step "1/4 检查运行环境..."

if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
    Write-Fail "未找到 docker，请先安装 Docker Desktop: https://docs.docker.com/desktop/windows/"
}
try { docker compose version | Out-Null } catch {
    Write-Fail "未找到 docker compose plugin，请升级 Docker Desktop"
}

Write-Ok "Docker:         $(docker --version)"
Write-Ok "Docker Compose: $(docker compose version)"

# ---------- 创建目录 ----------
Write-Step "2/4 准备安装目录..."

if ($InstallDir -ne ".") {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Write-Ok "安装目录: $(Resolve-Path $InstallDir)"
}
Set-Location $InstallDir

# ---------- 下载文件 ----------
Write-Step "3/4 下载配置文件..."

Invoke-WebRequest "$BASE_URL/compose.yaml"  -OutFile "compose.yaml"  ; Write-Ok "compose.yaml"
Invoke-WebRequest "$BASE_URL/.env.example"  -OutFile ".env.example"  ; Write-Ok ".env.example"
Invoke-WebRequest "$BASE_URL/mcnet.ps1"     -OutFile "mcnet.ps1"     ; Write-Ok "mcnet.ps1"

# ---------- 初始化 ----------
Write-Step "4/4 初始化配置与镜像..."
.\mcnet.ps1 init

Write-Host ""
Write-Ok "拉取 Docker 镜像 (首次可能需要几分钟)..."
docker compose pull

# ---------- 完成 ----------
Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  安装完成!"                              -ForegroundColor Green
Write-Host "  目录: $(Get-Location)"                  -ForegroundColor Green
Write-Host "  启动: .\mcnet.ps1 up"                   -ForegroundColor Green
Write-Host "  帮助: .\mcnet.ps1 help"                 -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
