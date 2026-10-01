# Minecraft 群组服管理脚本 (Windows PowerShell)
param(
    [Parameter(Position=0)][string]$Command = 'help',
    [Parameter(Position=1, ValueFromRemainingArguments=$true)][string[]]$Arguments = @()
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$BaseUrl = 'https://raw.githubusercontent.com/abwuge/minecraft-server/main'
function Compose {
    & docker compose @args
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose 执行失败 ($LASTEXITCODE)" }
}
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
function Check-Service($Service) {
    if ($Service -notin @('proxy','main','mirror','create','mcsm-web','mcsm-daemon','gateway')) { throw "未知服务: $Service" }
}
function Runtime {
    Compose run --rm --no-deps -T --entrypoint python3 -v "${PWD}:/mcnet-host" proxy /opt/mcnet/runtime.py @args
}
function Up {
    Compose up -d --wait @args
    Runtime whitelist sync
}
switch ($Command) {
    'help' {
        @'
用法: .\mcnet.ps1 命令 [子命令]
  init / up [服务] / down / restart [服务] / ps [服务] / build [服务]
  logs [服务]                        跟随日志，例如 logs proxy
  console 服务                       控制台；Ctrl+P、Ctrl+Q 退出
  mode online|offline|status          在线默认开白名单，离线默认关
  whitelist list / on / off / sync    统一管理三个子服
  whitelist add|remove java|bedrock "玩家名称" [--xuid XUID]
  update                             下载最新配置和镜像并启动
  clean-data                         删除全部数据（需输入 YES）
服务: proxy、main、mirror、create、mcsm-web、mcsm-daemon
'@
    }
    'init' { Init }
    'up' { Init; foreach($s in $Arguments) { Check-Service $s }; Up @Arguments }
    {$_ -in 'build','restart','ps'} { foreach($s in $Arguments) { Check-Service $s }; Compose $Command @Arguments }
    'down' { Compose down @Arguments }
    'logs' { foreach($s in $Arguments) { Check-Service $s }; Compose logs -f --tail=200 @Arguments }
    'console' {
        if ($Arguments.Count -ne 1) { throw '用法: console 服务' }
        Check-Service $Arguments[0]
        & docker attach "mcnet-$($Arguments[0])"
        if ($LASTEXITCODE -ne 0) { throw '连接控制台失败' }
    }
    'mode' {
        if ($Arguments.Count -ne 1) { throw '用法: mode online|offline|status' }
        Init; Runtime mode @Arguments
        if ($Arguments[0] -ne 'status') { Up }
    }
    'whitelist' { Init; Runtime whitelist @Arguments }
    'update' {
        foreach($f in @('compose.yaml','.env.example')) { Invoke-WebRequest "$BaseUrl/$f" -OutFile $f }
        Invoke-WebRequest "$BaseUrl/mcnet.ps1" -OutFile 'mcnet.ps1.tmp'
        Move-Item -Force 'mcnet.ps1.tmp' 'mcnet.ps1'
        Init; Compose pull; Up
    }
    'clean-data' {
        if ((Read-Host '确认删除全部 data/？输入 YES') -eq 'YES') { Compose down; Remove-Item -Recurse -Force data }
    }
    default { throw "未知命令: $Command；运行 .\mcnet.ps1 help 查看帮助" }
}
