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

function Get-DeviceHash {
    param([string]$Path)
    $output = (Invoke-Adb -Arguments @('-s', $Device, 'shell', 'sha256sum', $Path)) -join "`n"
    if ($output -notmatch '^([0-9a-fA-F]{64})\s') { throw "Invalid device hash: $Path" }
    return $Matches[1].ToLowerInvariant()
}

function Test-DeviceIdle {
    if (-not $env:TOUCHSPRITE_AUTH) { return $false }
    try {
        $state = & (Join-Path $PSScriptRoot 'ts-cli.ps1') -Action status -AdbPath $AdbPath -Device $Device
        return (($state -join "`n") -match '^TouchSprite status: f00 ')
    } catch {
        Write-Warning 'Device idle status unavailable; unfinished device artifacts retained.'
        return $false
    }
}

function Collect-Runs {
    $count = 0
    $removed = 0
    $groups = @{}
    foreach ($kind in @('log', 'res')) {
        $remoteDir = "$deviceRoot/$kind"
        $files = Invoke-Adb -Arguments @('-s', $Device, 'shell', 'ls', '-1', $remoteDir)
        foreach ($entry in $files) {
            $name = "$entry".Trim()
            # Only collect our experiment/daily artifacts, never unrelated account files.
            if ($name -notmatch '^(hello_world|daily)_(\d{8}_\d{6})(?:_[A-Za-z0-9_-]+)?\.(log|png)$') { continue }
            $prefix, $artifactRun, $extension = $Matches[1], $Matches[2], $Matches[3]
            if ($RunId -and $artifactRun -ne $RunId) { continue }
            if (($kind -eq 'log' -and $extension -ne 'log') -or ($kind -eq 'res' -and $extension -ne 'png')) { continue }
            $destination = Join-Path (Join-Path $archiveRoot $artifactRun) $kind
            $groupId = "${prefix}_$artifactRun"
            if (-not $groups.ContainsKey($groupId)) { $groups[$groupId] = @() }
            $groups[$groupId] += [pscustomobject]@{
                Name = $name; Kind = $kind; Remote = "$remoteDir/$name"
                Local = Join-Path $destination $name; Hash = $null
                Prefix = $prefix; Run = $artifactRun
            }
        }
    }
    foreach ($groupId in @($groups.Keys | Sort-Object)) {
        $artifacts = @($groups[$groupId])
        $removedBefore = $removed
        $stable = $true
        foreach ($artifact in $artifacts) {
            $destination = Split-Path -Parent $artifact.Local
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            $pending = Join-Path $destination ('.' + $artifact.Name + '.' + [guid]::NewGuid().ToString('N') + '.pending')
            try {
                $before = Get-DeviceHash -Path $artifact.Remote
                Invoke-Adb -Arguments @('-s', $Device, 'pull', $artifact.Remote, $pending) | Out-Null
                $localHash = (Get-FileHash -LiteralPath $pending -Algorithm SHA256).Hash.ToLowerInvariant()
                $after = Get-DeviceHash -Path $artifact.Remote
                if ($before -ne $after -or $localHash -ne $after) {
                    if ($Watch -and $before -ne $after) {
                        Write-Warning "Artifact still changing; retrying next watch cycle: $($artifact.Remote)"
                        $stable = $false
                        break
                    }
                    throw "Artifact changed or copy hash mismatch; device copy retained: $($artifact.Remote)"
                }
                Move-Item -LiteralPath $pending -Destination $artifact.Local -Force
                $artifact.Hash = $localHash
                $count++
            } finally {
                if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending -Force }
            }
        }
        if (-not $stable) { continue }

        $main = $artifacts | Where-Object { $_.Kind -eq 'log' -and $_.Name -eq "$groupId.log" } | Select-Object -First 1
        $finished = $false
        if ($main) {
            $lastLine = Get-Content -LiteralPath $main.Local | Where-Object { $_.Trim() } | Select-Object -Last 1
            $escapedRun = [regex]::Escape($main.Run)
            $finished = if ($main.Prefix -eq 'daily') {
                $lastLine -cmatch "^\[daily\]\[$escapedRun\]\[finished\] script_(exited_normally|failed)$"
            } else {
                $lastLine -cmatch "^\[hello_world\]\[run=$escapedRun\] script_finished$"
            }
        }
        if (-not $finished -and -not (Test-DeviceIdle)) { continue }

        # A run may finish after enumeration and create additional artifacts.
        $currentNames = @()
        foreach ($kind in @('log', 'res')) {
            $extension = if ($kind -eq 'log') { 'log' } else { 'png' }
            $pattern = '^' + [regex]::Escape($groupId) + '(?:_[A-Za-z0-9_-]+)?\.' + $extension + '$'
            foreach ($entry in @(Invoke-Adb -Arguments @('-s', $Device, 'shell', 'ls', '-1', "$deviceRoot/$kind"))) {
                $name = "$entry".Trim()
                if ($name -cmatch $pattern) { $currentNames += "$kind/$name" }
            }
        }
        $archivedNames = @($artifacts | ForEach-Object { "$($_.Kind)/$($_.Name)" })
        if (Compare-Object -ReferenceObject $archivedNames -DifferenceObject $currentNames) {
            Write-Warning "Run file list changed during collection; device copies retained: $groupId"
            continue
        }

        # Leave the completion evidence until last so interrupted cleanup can resume.
        $cleanup = @($artifacts | Where-Object { $_ -ne $main })
        if ($main) { $cleanup += $main }
        foreach ($artifact in $cleanup) {
            if (-not $finished -and -not (Test-DeviceIdle)) {
                Write-Warning "Device is no longer idle; remaining device copies retained: $groupId"
                break
            }
            if (($main -and (Get-DeviceHash -Path $main.Remote) -ne $main.Hash) -or
                (Get-DeviceHash -Path $artifact.Remote) -ne $artifact.Hash) {
                Write-Warning "Run changed during collection; remaining device copies retained: $groupId"
                break
            }
            if ((Get-FileHash -LiteralPath $artifact.Local -Algorithm SHA256).Hash.ToLowerInvariant() -ne $artifact.Hash) {
                throw "Local archive changed; device copy retained: $($artifact.Remote)"
            }
            Invoke-Adb -Arguments @('-s', $Device, 'shell', 'rm', '--', $artifact.Remote) | Out-Null
            $removed++
        }
        Write-Output "Archived ${groupId}: $($artifacts.Count) file(s), removed $($removed - $removedBefore) device copy/copies."
    }
    Write-Output "Collected $count verified artifact(s) into $archiveRoot; removed $removed device copy/copies; retained $($count - $removed) unfinished or changed artifact(s)."
    if ($count -eq 0 -and -not $Watch) { throw 'No matching artifacts found.' }
}

do {
    Collect-Runs
    if ($Watch) { Start-Sleep -Seconds 5 }
} while ($Watch)
