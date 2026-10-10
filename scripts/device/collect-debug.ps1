param(
    [string]$AdbPath,
    [string]$Device,
    [ValidatePattern('^\d{8}_\d{6}$')][string]$RunId,
    [switch]$Watch
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$archiveRoot = Join-Path $projectRoot 'debug-runs'
$deviceRoot = '/storage/emulated/0/TouchSprite'

if (-not $AdbPath) {
    $AdbPath = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq 'adb.exe' -and $_.ExecutablePath } |
        Select-Object -First 1 -ExpandProperty ExecutablePath
    if (-not $AdbPath) {
        $command = Get-Command adb -ErrorAction SilentlyContinue
        if ($command) { $AdbPath = $command.Source }
    }
    if (-not $AdbPath) { $AdbPath = 'D:\Program Files\Netease\MuMu\nx_main\adb.exe' }
}
if (-not (Test-Path -LiteralPath $AdbPath -PathType Leaf)) {
    throw 'ADB not found. Supply -AdbPath with the absolute path to adb.exe.'
}

function Invoke-Adb {
    param([string[]]$Arguments)
    $output = & $AdbPath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "ADB failed: $($output -join ' ')" }
    return $output
}

if (-not $Device) {
    $devices = @(Invoke-Adb -Arguments @('devices') | ForEach-Object {
        if ("$_" -match '^(\S+)\s+device$') { $Matches[1] }
    })
    if ($devices.Count -ne 1) {
        throw "Expected one connected device, found $($devices.Count). Supply -Device explicitly."
    }
    $Device = $devices[0]
}

function Collect-Runs {
    $count = 0
    foreach ($kind in @('log', 'res')) {
        $remoteDir = "$deviceRoot/$kind"
        $files = Invoke-Adb -Arguments @('-s', $Device, 'shell', 'ls', '-1', $remoteDir)
        foreach ($entry in $files) {
            $name = "$entry".Trim()
            # Only collect our experiment/daily artifacts, never unrelated account files.
            if ($name -notmatch '^(?:hello_world|daily)_(\d{8}_\d{6})(?:_[A-Za-z0-9_-]+)?\.(log|png)$') { continue }
            $artifactRun = $Matches[1]
            if ($RunId -and $artifactRun -ne $RunId) { continue }
            $destination = Join-Path (Join-Path $archiveRoot $artifactRun) $kind
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            Invoke-Adb -Arguments @('-s', $Device, 'pull', "$remoteDir/$name", (Join-Path $destination $name)) | Out-Null
            $count++
        }
    }
    Write-Output "Collected $count artifact(s) into $archiveRoot"
    if ($count -eq 0 -and -not $Watch) { throw 'No matching artifacts found.' }
}

do {
    Collect-Runs
    if ($Watch) { Start-Sleep -Seconds 5 }
} while ($Watch)
