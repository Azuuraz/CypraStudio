param(
    [switch]$ProjectOnly,
    [switch]$BestEffort,
    [switch]$RunnersOnly,
    [int]$KeepPid = 0,
    [int]$CurrentPort = 0,
    [switch]$Quiet
)

# Default behavior is the user's standalone "kill localhost" utility: no
# confirmation UI, no prompts, and no dependency on MatrixStudio state.  The
# application itself passes -ProjectOnly so its shutdown endpoint can finish
# saving state before the local web host exits.
$SystemProcessNames = [System.Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
@(
    'System','Registry','smss','csrss','wininit','services','lsass','svchost',
    'dwm','fontdrvhost','winlogon','spoolsv','SearchIndexer','MsMpEng',
    'SecurityHealthService','WmiPrvSE','dllhost','conhost','RuntimeBroker',
    'ApplicationFrameHost','sihost','taskhostw','explorer'
) | ForEach-Object { [void]$SystemProcessNames.Add($_) }

function Get-LoopbackListeners {
    $rows = New-Object System.Collections.ArrayList
    $seen = [System.Collections.Generic.HashSet[int]]::new()
    try {
        $connections = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -in @('127.0.0.1','::1') })
    } catch { $connections = @() }

    foreach ($conn in $connections) {
        $processId = [int]$conn.OwningProcess
        if ($processId -le 4 -or $processId -eq $PID -or $seen.Contains($processId)) { continue }
        $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if (-not $proc -or $SystemProcessNames.Contains($proc.ProcessName)) { continue }
        [void]$seen.Add($processId)
        $ports = @($connections | Where-Object { [int]$_.OwningProcess -eq $processId } |
            Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
        [void]$rows.Add([PSCustomObject]@{
            PID=$processId
            Name=$proc.ProcessName
            Ports=($ports -join ', ')
        })
    }
    foreach ($row in $rows) { Write-Output $row }
}

function Invoke-ImmediateLocalhostKill {
    $killed = [System.Collections.Generic.HashSet[int]]::new()
    $failed = New-Object System.Collections.ArrayList
    # A short bounded rescan catches children/respawns created while the first
    # process tree is being torn down without turning this into a background job.
    for ($pass = 0; $pass -lt 4; $pass++) {
        $targets = @(Get-LoopbackListeners)
        if ($targets.Count -eq 0) { break }
        foreach ($target in $targets) {
            $pidValue = [int]$target.PID
            try {
                & taskkill.exe /PID $pidValue /T /F *> $null
                if ($LASTEXITCODE -eq 0 -or -not (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
                    [void]$killed.Add($pidValue)
                } else {
                    [void]$failed.Add("$($target.Name) PID $pidValue")
                }
            } catch {
                if (Get-Process -Id $pidValue -ErrorAction SilentlyContinue) {
                    [void]$failed.Add("$($target.Name) PID $pidValue")
                }
            }
        }
        Start-Sleep -Milliseconds 180
    }

    $survivors = @(Get-LoopbackListeners)
    if (-not $Quiet) {
        Write-Output ("Kill Localhost: killed={0}; survivors={1}" -f $killed.Count, $survivors.Count)
        foreach ($target in $survivors) {
            Write-Output ("  survivor: {0} PID {1} ports {2}" -f $target.Name, $target.PID, $target.Ports)
        }
    }
    if ($survivors.Count -gt 0) { exit 2 }
    exit 0
}

if (-not $ProjectOnly) {
    Invoke-ImmediateLocalhostKill
}

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$DataDir = Join-Path $Root 'data'
$markerPath = Join-Path $DataDir 'ollama.runtime.json'
$registryPath = Join-Path $Root 'OllamaModels\.matrixstudio.runtimes.json'
$launchLog = Join-Path $DataDir 'launch.log'
$expectedStore = [IO.Path]::GetFullPath((Join-Path $Root 'OllamaModels'))
$expectedStoreNeedle = ($expectedStore.TrimEnd('\') + '\').ToLowerInvariant()

function FullPath-OrNull([string]$Value) {
    if (-not $Value) { return $null }
    try { return [IO.Path]::GetFullPath($Value) } catch { return $null }
}

function Same-Path([string]$A, [string]$B) {
    $pa = FullPath-OrNull $A
    $pb = FullPath-OrNull $B
    return ($pa -and $pb -and $pa -ieq $pb)
}

function Get-OllamaExeCandidates {
    $paths = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    try {
        $cmd = Get-Command ollama -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { [void]$paths.Add([IO.Path]::GetFullPath($cmd.Source)) }
    } catch {}
    if ($env:LOCALAPPDATA) {
        $p = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        if (Test-Path -LiteralPath $p) { [void]$paths.Add([IO.Path]::GetFullPath($p)) }
    }
    if ($env:ProgramFiles) {
        $p = Join-Path $env:ProgramFiles 'Ollama\ollama.exe'
        if (Test-Path -LiteralPath $p) { [void]$paths.Add([IO.Path]::GetFullPath($p)) }
    }
    Write-Output -NoEnumerate $paths
}

$exeCandidates = Get-OllamaExeCandidates
$records = New-Object System.Collections.ArrayList

function Add-Record($Record) {
    if ($null -eq $Record) { return }
    try {
        if (-not (Same-Path ([string]$Record.store) $expectedStore)) { return }
        $pidValue = [int]$Record.pid
        $portValue = [int]$Record.port
        if ($pidValue -le 0 -or $portValue -le 0) { return }
        $exe = FullPath-OrNull ([string]$Record.exe)
        if ($exe) { [void]$exeCandidates.Add($exe) }
        [void]$records.Add([PSCustomObject]@{
            pid=$pidValue
            port=$portValue
            exe=$exe
            store=$expectedStore
            started=[string]$Record.started
            source='tracked'
        })
    } catch {}
}

foreach ($path in @($markerPath, $registryPath)) {
    if (-not (Test-Path -LiteralPath $path)) { continue }
    try {
        $loaded = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        if ($loaded -is [System.Array]) { foreach ($item in $loaded) { Add-Record $item } }
        elseif ($null -ne $loaded) { Add-Record $loaded }
    } catch {
        if (-not $BestEffort) { Write-Warning "Ignoring malformed runtime record: $path" }
    }
}

$verifiedServePids = [System.Collections.Generic.HashSet[int]]::new()
foreach ($r in $records) {
    try {
        $pidValue = [int]$r.pid
        if ($pidValue -le 0 -or -not $r.exe) { continue }
        $proc = Get-Process -Id $pidValue -ErrorAction Stop
        $procPath = FullPath-OrNull $proc.Path
        if (-not $procPath -or $procPath -ine $r.exe) { continue }
        if ($r.started -and $proc.StartTime.ToUniversalTime().Ticks.ToString() -ne [string]$r.started) { continue }
        [void]$verifiedServePids.Add($pidValue)
    } catch {}
}

function Get-ProjectDaemonProcesses([int[]]$Ports) {
    $result = New-Object System.Collections.ArrayList
    $seen = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($port in @($Ports)) {
        if ($port -le 0 -or $port -gt 65535) { continue }
        try {
            $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
                Where-Object { $_.LocalAddress -in @('127.0.0.1','::1') })
            foreach ($listener in $listeners) {
                $pidValue = [int]$listener.OwningProcess
                if ($pidValue -le 0 -or $seen.Contains($pidValue)) { continue }
                $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
                if (-not $proc) { continue }
                $procPath = $null
                try { $procPath = [IO.Path]::GetFullPath($proc.Path) } catch {}
                if (-not $procPath -or -not $exeCandidates.Contains($procPath)) { continue }
                $isServe = $true
                try {
                    $cim = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $pidValue) -ErrorAction SilentlyContinue
                    $cmdline = ([string]$cim.CommandLine).ToLowerInvariant()
                    if ($cmdline) { $isServe = $cmdline -match '(^|\s|\")serve(\s|$|\")' }
                } catch {}
                if (-not $isServe) { continue }
                [void]$seen.Add($pidValue)
                [void]$result.Add([PSCustomObject]@{ ProcessId=$pidValue; Port=$port; Path=$procPath })
            }
        } catch {}
    }
    foreach ($item in $result) { Write-Output $item }
}

function Get-ProjectRunnerProcesses {
    $result = New-Object System.Collections.ArrayList
    try {
        foreach ($p in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
            $name = ([string]$p.Name).ToLowerInvariant()
            $isRunner = ($name -eq 'llama-server.exe') -or ($name -eq 'ollama_llama_server.exe') -or ($name -like 'ollama_llama_server*.exe')
            if (-not $isRunner) { continue }
            $cmdline = ([string]$p.CommandLine).Replace('/','\').ToLowerInvariant()
            $parentId = [int]$p.ParentProcessId
            $ownedByStore = $cmdline -and $cmdline.Contains($expectedStoreNeedle)
            $ownedByTrackedParent = $parentId -gt 0 -and $verifiedServePids.Contains($parentId)
            if ($ownedByStore -or $ownedByTrackedParent) { [void]$result.Add($p) }
        }
    } catch {}
    foreach ($item in $result) { Write-Output $item }
}

$candidatePids = [System.Collections.Generic.HashSet[int]]::new()
$historicalPorts = [System.Collections.Generic.HashSet[int]]::new()
foreach ($r in $records) { [void]$historicalPorts.Add([int]$r.port) }
if ($CurrentPort -gt 0 -and $CurrentPort -le 65535) { [void]$historicalPorts.Add($CurrentPort) }

# Migration cleanup for builds before the runtime registry existed. Each launch
# log belongs to this exact project root, so historical private ports are useful
# for recovering serve processes whose one-slot marker was overwritten.
if (Test-Path -LiteralPath $launchLog) {
    try {
        foreach ($line in Get-Content -LiteralPath $launchLog -ErrorAction Stop) {
            if (($line -match 'private runtime started @ 127\.0\.0\.1:(\d+)') -or ($line -match 'Ollama runtime (?:started|reused) pid=\d+ port=(\d+)')) {
                $p = [int]$Matches[1]
                if ($p -gt 0 -and $p -le 65535) { [void]$historicalPorts.Add($p) }
            }
        }
    } catch {}
}

if (-not $RunnersOnly) {
    # First trust only strongly verified tracked records: exact store, executable,
    # process start time, and (when present) the recorded loopback listener.
    foreach ($r in $records) {
        if ($KeepPid -gt 0 -and [int]$r.pid -eq $KeepPid) { continue }
        $proc = Get-Process -Id ([int]$r.pid) -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        $procPath = $null
        try { $procPath = [IO.Path]::GetFullPath($proc.Path) } catch {}
        if (-not $procPath -or -not $r.exe -or $procPath -ine $r.exe) { continue }
        if ($r.started) {
            try {
                if ($proc.StartTime.ToUniversalTime().Ticks.ToString() -ne [string]$r.started) { continue }
            } catch { continue }
        }
        try {
            $listener = Get-NetTCPConnection -State Listen -LocalPort ([int]$r.port) -ErrorAction SilentlyContinue |
                Where-Object { $_.OwningProcess -eq $proc.Id -and $_.LocalAddress -in @('127.0.0.1','::1') }
            if ($listener -or $r.started) { [void]$candidatePids.Add([int]$proc.Id) }
        } catch {
            if ($r.started) { [void]$candidatePids.Add([int]$proc.Id) }
        }
    }

    # Recover old serve processes by the private ports recorded in this project's
    # own launch log. Require an Ollama executable and a live Ollama API response.
    foreach ($port in $historicalPorts) {
        try {
            $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
                Where-Object { $_.LocalAddress -in @('127.0.0.1','::1') })
            foreach ($listener in $listeners) {
                $pidValue = [int]$listener.OwningProcess
                if ($KeepPid -gt 0 -and $pidValue -eq $KeepPid) { continue }
                $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
                if (-not $proc) { continue }
                $procPath = $null
                try { $procPath = [IO.Path]::GetFullPath($proc.Path) } catch {}
                if (-not $procPath -or -not $exeCandidates.Contains($procPath)) { continue }
                try {
                    Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/version" -TimeoutSec 1 | Out-Null
                    [void]$candidatePids.Add($pidValue)
                } catch {}
            }
        } catch {}
    }

}

# Current Ollama builds use llama-server.exe / ollama_llama_server.exe for
# model runners. Older cleanup only scanned ollama.exe, so detached runners
# survived both keep-alive expiry and Kill Host. Attribute a runner only when
# its command line points at this project's private model store or its parent
# is a tracked MatrixStudio serve process.
foreach ($p in @(Get-ProjectRunnerProcesses)) {
    $pidValue = [int]$p.ProcessId
    $parentId = [int]$p.ParentProcessId
    if ($KeepPid -gt 0 -and (($pidValue -eq $KeepPid) -or ($parentId -eq $KeepPid))) { continue }
    [void]$candidatePids.Add($pidValue)
}

$targets = @($candidatePids) | Sort-Object
foreach ($pidValue in $targets) {
    if (-not (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) { continue }
    try {
        # /T is deliberate: Stop-Process only killed the serve parent and could
        # leave Ollama runner children alive, which caused RAM/process buildup.
        & taskkill.exe /PID $pidValue /T /F *> $null
    } catch {}
}

$deadline = (Get-Date).AddSeconds(8)
do {
    $stillAlive = @($targets | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    if ($stillAlive.Count -eq 0) { break }
    Start-Sleep -Milliseconds 200
} while ((Get-Date) -lt $deadline)

# A daemon can be recreated under a new PID while shutdown is in flight (for
# example by a reconnect race). Original-PID verification would miss it. Keep
# rescanning MatrixStudio's known private ports for a short bounded window and
# terminate any freshly-created Ollama `serve` process on those ports.
$lateDaemonTargets = [System.Collections.Generic.HashSet[int]]::new()
if (-not $RunnersOnly) {
    $lateDeadline = (Get-Date).AddSeconds(4)
    do {
        foreach ($daemon in @(Get-ProjectDaemonProcesses -Ports @($historicalPorts))) {
            $pidValue = [int]$daemon.ProcessId
            if ($KeepPid -gt 0 -and $pidValue -eq $KeepPid) { continue }
            [void]$lateDaemonTargets.Add($pidValue)
            try { & taskkill.exe /PID $pidValue /T /F *> $null } catch {}
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $lateDeadline)
}

# Final survivor sweep for any store-owned Ollama runner that was not in the
# original candidate set (for example a child spawned during shutdown).
$survivors = New-Object System.Collections.ArrayList
try {
    foreach ($p in @(Get-ProjectRunnerProcesses)) {
        $parentId = [int]$p.ParentProcessId
        if ($KeepPid -gt 0 -and (([int]$p.ProcessId -eq $KeepPid) -or ($parentId -eq $KeepPid))) { continue }
        [void]$survivors.Add([int]$p.ProcessId)
    }
} catch {}
foreach ($pidValue in $targets) {
    if (Get-Process -Id $pidValue -ErrorAction SilentlyContinue) { [void]$survivors.Add([int]$pidValue) }
}
if (-not $RunnersOnly) {
    foreach ($daemon in @(Get-ProjectDaemonProcesses -Ports @($historicalPorts))) {
        if ($KeepPid -gt 0 -and [int]$daemon.ProcessId -eq $KeepPid) { continue }
        [void]$survivors.Add([int]$daemon.ProcessId)
    }
}
$survivors = @($survivors | Sort-Object -Unique)
if ($survivors.Count -gt 0 -and -not $BestEffort) {
    throw ('Project Ollama daemon survived shutdown (or runner remained): ' + ($survivors -join ', '))
}

if ($survivors.Count -eq 0 -and -not $RunnersOnly) {
    if ($KeepPid -gt 0) {
        $kept = @($records | Where-Object { [int]$_.pid -eq $KeepPid } | Select-Object -First 1)
        if ($kept.Count -gt 0) {
            $kept[0] | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $markerPath -Encoding UTF8
            @($kept[0]) | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $registryPath -Encoding UTF8
        }
    } else {
        Remove-Item -LiteralPath $markerPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $registryPath -Force -ErrorAction SilentlyContinue
    }
}

$mode = if ($RunnersOnly) { 'runners-only' } else { 'full' }
Write-Output ("MatrixStudio Ollama cleanup: mode={0}; targets={1}; late-daemons={2}; survivors={3}; kept={4}" -f $mode, $targets.Count, $lateDaemonTargets.Count, $survivors.Count, $KeepPid)
if ($survivors.Count -gt 0) { exit 2 }
exit 0
