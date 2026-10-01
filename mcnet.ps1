# Minecraft 群组服管理脚本 (Windows PowerShell)
param(
    [Parameter(Position=0)][string]$Command = 'help',
    [Parameter(Position=1, ValueFromRemainingArguments=$true)][string[]]$Arguments = @()
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$BaseUrl = 'https://raw.githubusercontent.com/abwuge/minecraft-server/main'
function Init {
    $script:EnvText = if (Test-Path '.env') { [IO.File]::ReadAllText((Join-Path $PWD '.env')) } else { [IO.File]::ReadAllText((Join-Path $PWD '.env.example')) }
    function Read-Value($Key) {
        $m = [regex]::Match($script:EnvText, "(?m)^$Key=(.*)$")
        if ($m.Success) { return $m.Groups[1].Value.Trim() }; return ''
    }
    function Set-Value($Key, $Value) {
        $pattern = "(?m)^$Key=.*$"
        if ([regex]::IsMatch($script:EnvText,$pattern)) {
            $replacement = "$Key=$Value"
            $script:EnvText = [regex]::Replace($script:EnvText,$pattern,$replacement)
        } else { $script:EnvText += "`n$Key=$Value`n" }
    }
    foreach ($item in @(@('VELOCITY_FORWARDING_SECRET','change-me-to-random-hex',24),@('RCON_PASSWORD','change-me-rcon',16))) {
        if ((Read-Value $item[0]) -in @('', $item[1])) {
            $bytes = New-Object byte[] $item[2]
            $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
            Set-Value $item[0] ([BitConverter]::ToString($bytes).Replace('-','').ToLower())
        }
    }
    if (-not (Read-Value 'ONLINE_MODE')) { Set-Value 'ONLINE_MODE' 'true' }
    if (-not (Read-Value 'WHITE_LIST')) { Set-Value 'WHITE_LIST' (Read-Value 'ONLINE_MODE') }
    if (-not (Read-Value 'MCSM_NODE_ADDRESS') -and -not (Read-Value 'MCSM_PUBLIC_URL')) {
        $udp = New-Object Net.Sockets.UdpClient
        try { $udp.Connect('8.8.8.8',80); Set-Value 'MCSM_NODE_ADDRESS' $udp.Client.LocalEndPoint.Address.ToString() }
        finally { $udp.Dispose() }
    }
    [IO.File]::WriteAllText((Join-Path $PWD '.env'),$script:EnvText,(New-Object Text.UTF8Encoding $false))
    Write-Host '[init] 配置已就绪'
}
function Manager {
    Init
    $values = @{}
    Get-Content '.env' | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
    }
    $owner = if ($values['GHCR_OWNER']) { $values['GHCR_OWNER'] } else { 'abwuge' }
    $tag = if ($values['IMAGE_TAG']) { $values['IMAGE_TAG'] } else { 'latest' }
    $image = if ($values['IMAGE_PROXY']) { $values['IMAGE_PROXY'] } else { "ghcr.io/$owner/mc-proxy:$tag" }
    & docker network inspect mcnet 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { & docker network create mcnet | Out-Null }
    if ($args[0] -eq 'update') {
        & docker pull $image
        if ($LASTEXITCODE -ne 0) { throw '管理镜像拉取失败' }
    }
    & docker run --rm --network mcnet --env-file .env --env "MCNET_HOST_TIMEZONE=$([TimeZoneInfo]::Local.Id)" -v "${PWD}:/mcnet-host" -v "${PWD}/data/whitelist:/whitelist" -v /var/run/docker.sock:/var/run/docker.sock --entrypoint python3 $image /mcnet-host/mcnet.py @args
    if ($LASTEXITCODE -ne 0) { throw "mcnet 执行失败 ($LASTEXITCODE)" }
}
function Refresh {
    $revision = (Invoke-RestMethod 'https://api.github.com/repos/abwuge/minecraft-server/commits/main').sha
    $sourceUrl = "https://raw.githubusercontent.com/abwuge/minecraft-server/$revision"
    foreach($f in @('.env.example','mcnet.py','mcnet.ps1')) {
        Invoke-WebRequest "$sourceUrl/$f" -OutFile "$f.tmp"
        Move-Item -Force "$f.tmp" $f
    }
    New-Item -ItemType Directory -Force 'config/gateway' | Out-Null
    Invoke-WebRequest "$sourceUrl/config/gateway/Caddyfile" -OutFile 'config/gateway/Caddyfile'
}
switch ($Command) {
    'help' {
        @'
用法: .\mcnet.ps1 命令 [子命令]
  init / up [服务] / down / restart [服务] / ps
  logs [服务]                        跟随日志，默认 proxy
  console 服务                       控制台；Ctrl+P、Ctrl+Q 退出
  mode online|offline|status
  whitelist list|add|remove|on|off|sync
  update [服务]                      更新脚本和镜像；原安装命令也可更新
  clean-data                         删除全部数据（需输入 YES）
服务: proxy、main、mirror、create、mcsm-web、mcsm-daemon、gateway
'@
    }
    'init' { Init }
    {$_ -in 'up','down','restart','ps','mode','whitelist'} { Manager $Command @Arguments }
    'logs' {
        $service = if ($Arguments.Count) { $Arguments[0] } else { 'proxy' }
        & docker logs -f --tail=200 "mcnet-$service"
    }
    'console' {
        if ($Arguments.Count -ne 1) { throw '用法: console 服务' }
        & docker attach "mcnet-$($Arguments[0])"
    }
    'update' { Refresh; Manager update @Arguments }
    'clean-data' {
        if ((Read-Host '确认删除全部 data/？输入 YES') -eq 'YES') { Manager down; Remove-Item -Recurse -Force data }
    }
    default { throw "未知命令: $Command；运行 .\mcnet.ps1 help 查看帮助" }
}
