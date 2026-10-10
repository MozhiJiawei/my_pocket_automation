param(
    [ValidateSet('deploy', 'run', 'status', 'collect')][string]$Action = 'deploy',
    [string]$AdbPath,
    [string]$Device,
    [ValidateRange(1, 65535)][int]$ServicePort = 50005,
    [string]$SourcePath
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$source = Join-Path $projectRoot 'prototype/login_hello/main.lua'
if ($SourcePath) { $source = [IO.Path]::GetFullPath($SourcePath) }
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'Script source file does not exist.' }
$studioFile = 'C:/Users/37274/Documents/TSStudio/Projects/MY/main.lua'
$remoteFile = '/storage/emulated/0/TouchSprite/lua/main.lua'
if (-not $AdbPath) {
    $AdbPath = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq 'adb.exe' -and $_.ExecutablePath } |
        Select-Object -First 1 -ExpandProperty ExecutablePath
    if (-not $AdbPath) {
        $command = Get-Command adb -ErrorAction SilentlyContinue
        if ($command) { $AdbPath = $command.Source }
    }
    if (-not $AdbPath) { $AdbPath = 'D:/Program Files/Netease/MuMu/nx_main/adb.exe' }
}
if (-not (Test-Path -LiteralPath $AdbPath -PathType Leaf)) { throw 'Supply -AdbPath with the absolute path to adb.exe.' }

function Invoke-Adb {
    param([string[]]$Arguments)
    $result = & $AdbPath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "ADB failed: $($result -join ' ')" }
    return $result
}
if (-not $Device) {
    $devices = @(Invoke-Adb -Arguments @('devices') | ForEach-Object {
        if ("$_" -match '^(\S+)\s+device$') { $Matches[1] }
    })
    if ($devices.Count -ne 1) { throw 'Expected exactly one connected device. Otherwise supply -Device.' }
    $Device = $devices[0]
}
if ($Action -eq 'collect') {
    & (Join-Path $PSScriptRoot 'collect-debug.ps1') -AdbPath $AdbPath -Device $Device
    return
}

function Publish-Script {
    Copy-Item -LiteralPath $source -Destination $studioFile -Force
    $expected = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ((Get-FileHash -LiteralPath $studioFile -Algorithm SHA256).Hash -ne $expected) {
        throw 'TS Studio copy verification failed.'
    }
    Invoke-Adb -Arguments @('-s', $Device, 'push', $source, "$remoteFile.pending") | Out-Null
    $deviceHash = (Invoke-Adb -Arguments @('-s', $Device, 'shell', 'sha256sum', "$remoteFile.pending")) -join ''
    if (($deviceHash -split '\s+')[0] -ne $expected.ToLowerInvariant()) {
        throw 'Device copy verification failed; main.lua was not replaced.'
    }
    Invoke-Adb -Arguments @('-s', $Device, 'shell', 'mv', "$remoteFile.pending", $remoteFile) | Out-Null
    Write-Output "Published and verified: $remoteFile"
}
# Auth is transient and must never be written to the repository or printed.
if (-not $env:TOUCHSPRITE_AUTH) {
    throw 'Deploy/run/status requires TOUCHSPRITE_AUTH for the idle check (official API auth token, not the VIP activation code).'
}
Add-Type -AssemblyName System.Net.Http
$handler = [System.Net.Http.HttpClientHandler]::new()
$handler.UseProxy = $false
$client = [System.Net.Http.HttpClient]::new($handler)
$client.Timeout = [TimeSpan]::FromSeconds(10)
$client.DefaultRequestHeaders.Add('auth', $env:TOUCHSPRITE_AUTH)
$client.DefaultRequestHeaders.ConnectionClose = $true
$forwardPort = $null
try {
    $forwardPort = (Invoke-Adb -Arguments @('-s', $Device, 'forward', 'tcp:0', "tcp:$ServicePort") | Select-Object -Last 1).ToString().Trim()
    if ($forwardPort -notmatch '^\d+$') { throw 'Could not allocate ADB forwarding port.' }
    $baseUrl = "http://127.0.0.1:$forwardPort"
    function Invoke-TouchSprite {
        param([string]$Endpoint, [string]$Body)
        if ($Body) {
            $content = [System.Net.Http.StringContent]::new($Body, [Text.Encoding]::UTF8, 'application/json')
            try { $response = $client.PostAsync("$baseUrl/$Endpoint", $content).GetAwaiter().GetResult() }
            finally { $content.Dispose() }
        } else {
            $response = $client.GetAsync("$baseUrl/$Endpoint").GetAwaiter().GetResult()
        }
        try {
            if (-not $response.IsSuccessStatusCode) {
                throw "TouchSprite $Endpoint returned HTTP $([int]$response.StatusCode). Check API authorization and service."
            }
            return $response.Content.ReadAsStringAsync().GetAwaiter().GetResult().Trim()
        } finally { $response.Dispose() }
    }
    $state = Invoke-TouchSprite -Endpoint 'status'
    if ($Action -eq 'status') { Write-Output "TouchSprite status: $state (f00=idle, f01=running, f02=recording)"; return }
    if ($state -ne 'f00') { throw "Device is not idle ($state); finish the current script/recording first." }
    Publish-Script
    if ($Action -eq 'deploy') { return }
    $body = @{ path = $remoteFile } | ConvertTo-Json -Compress
    if ((Invoke-TouchSprite -Endpoint 'setLuaPath' -Body $body) -ne 'ok') { throw 'setLuaPath did not return ok.' }
    if ((Invoke-TouchSprite -Endpoint 'runLua') -ne 'ok') { throw 'runLua did not return ok.' }
    Write-Output 'Start request accepted. Use collect to retrieve evidence; this is not a business-success assertion.'
} finally {
    if ($forwardPort -match '^\d+$') {
        & $AdbPath -s $Device forward --remove "tcp:$forwardPort" | Out-Null
    }
    $client.Dispose()
    $handler.Dispose()
}
