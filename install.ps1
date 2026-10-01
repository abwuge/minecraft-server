# 安装或更新 MCSManager 管理的 Minecraft 群组服。
param([string]$InstallDir = '.')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$BaseUrl = 'https://raw.githubusercontent.com/abwuge/minecraft-server/main'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw '请先安装 Docker Desktop' }
New-Item -ItemType Directory -Force $InstallDir | Out-Null
Set-Location $InstallDir
foreach ($file in @('.env.example','mcnet.ps1','mcnet.py')) {
    Invoke-WebRequest "$BaseUrl/$file" -OutFile "$file.tmp"
    Move-Item -Force "$file.tmp" $file
}
New-Item -ItemType Directory -Force 'config/gateway' | Out-Null
Invoke-WebRequest "$BaseUrl/config/gateway/Caddyfile" -OutFile 'config/gateway/Caddyfile'
.\mcnet.ps1 update
Write-Host "[install] 已就绪: $PWD"
