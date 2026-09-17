$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root

$BuildId = "2.3.22-stt-download-timeout-20260916"
$AppId = "matrixstudio2-local"
$BootCols = 76
$BootRows = 18
$StarterModel = "llama3.2:3b"
$DataDir = Join-Path $Root "data"
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $Root "requirements.txt"
$SetupDir = Join-Path $Root "Setup"
$SetupPython = Join-Path $SetupDir "Python312\python.exe"
$ReadyMarker = Join-Path $DataDir "studio.ready"
$SettingsPath = Join-Path $DataDir "settings.json"
$LaunchLog = Join-Path $DataDir "launch.log"
$AppRuntimeMarker = Join-Path $DataDir "app.runtime.json"
$OllamaRuntimeRegistry = Join-Path $Root "OllamaModels\.matrixstudio.runtimes.json"
$KillHostScript = Join-Path $Root "kill-localhost.ps1"
$SetupLog = Join-Path $DataDir "setup.log"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

try { $Host.UI.RawUI.WindowTitle = "MatrixStudio2.0 // Boot" } catch {}

function Set-BootConsoleSize([int]$Cols = $BootCols, [int]$Rows = $BootRows) {
    try {
        $raw = $Host.UI.RawUI
        $max = $raw.MaxPhysicalWindowSize
        $colsSafe = [Math]::Max(60, [Math]::Min($Cols, [int]$max.Width))
        $rowsSafe = [Math]::Max(12, [Math]::Min($Rows, [int]$max.Height))
        try {
            $buffer = $raw.BufferSize
            if ($buffer.Width -lt $colsSafe) { $buffer.Width = $colsSafe }
            if ($buffer.Height -lt $rowsSafe) { $buffer.Height = $rowsSafe }
            $raw.BufferSize = $buffer
            $window = $raw.WindowSize
            $window.Width = $colsSafe
            $window.Height = $rowsSafe
            $raw.WindowSize = $window
            $buffer = $raw.BufferSize
            $buffer.Width = $colsSafe
            $raw.BufferSize = $buffer
        } catch {}
        try { [Console]::SetWindowSize($colsSafe, $rowsSafe) } catch {}
        # Modern Windows Terminal may ignore classic RawUI window geometry but
        # understands the VT resize request. Unsupported hosts simply ignore it.
        try { $esc = [char]27; Write-Host -NoNewline ("{0}[8;{1};{2}t" -f $esc, $rowsSafe, $colsSafe) } catch {}
    } catch {}
}
Set-BootConsoleSize

function Say([string]$Text, [ConsoleColor]$Color = [ConsoleColor]::Gray) { Write-Host $Text -ForegroundColor $Color }
function Rule { Say ("-" * 72) DarkGray }
function Step([string]$Code, [string]$Text) { Write-Host ("  [{0}] " -f $Code) -NoNewline -ForegroundColor DarkCyan; Write-Host $Text -ForegroundColor Gray }
function Pass([string]$Text) { Write-Host "       OK  " -NoNewline -ForegroundColor Green; Write-Host $Text -ForegroundColor DarkGray }
function Warn([string]$Text) { Write-Host "       !!  " -NoNewline -ForegroundColor Yellow; Write-Host $Text -ForegroundColor Yellow }
function Log-Launch([string]$Text) {
    try { Add-Content -LiteralPath $LaunchLog -Value ((Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "  " + $Text) -Encoding UTF8 } catch {}
}
function Fail([string]$Text) {
    Log-Launch ("FAIL  " + $Text)
    Write-Host "       XX  " -NoNewline -ForegroundColor Red
    Write-Host $Text -ForegroundColor Red
    Write-Host ""
    exit 1
}
function Banner {
    Clear-Host
    Say "" Cyan
    Say "  MATRIXSTUDIO 2.0" Cyan
    Say "  LOCAL AI STUDIO // PRIVATE RUNTIME" Green
    Say ("  " + $BuildId) DarkGray
    Rule
}

function Test-PortFree([int]$Port) {
    $l = $null
    try { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port); $l.Start(); return $true }
    catch { return $false }
    finally { if ($l) { try { $l.Stop() } catch {} } }
}
function Test-ExistingStudio {
    if (-not (Test-Path -LiteralPath $AppRuntimeMarker)) { return $false }
    try {
        $mark = Get-Content $AppRuntimeMarker -Raw | ConvertFrom-Json
        $pidValue = [int]$mark.pid
        $portValue = [int]$mark.port
        if ($pidValue -le 0 -or $portValue -lt 1024 -or $portValue -gt 65535) { throw "invalid marker" }
        $proc = Get-Process -Id $pidValue -ErrorAction Stop
        $health = $null
        for ($i=0; $i -lt 20; $i++) {
            try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$portValue/api/health" -TimeoutSec 1; break } catch { Start-Sleep -Milliseconds 250 }
        }
        if ($null -eq $health -or [string]$health.app_id -ne $AppId) { throw "wrong app" }
        $markerRoot = [string]$mark.root
        if ($markerRoot -and ([IO.Path]::GetFullPath($markerRoot) -ine [IO.Path]::GetFullPath($Root))) { throw "wrong root" }
        try {
            $shell = New-Object -ComObject WScript.Shell
            [void]$shell.AppActivate($pidValue)
        } catch {}
        Pass "desktop already running @ 127.0.0.1:$portValue"
        Log-Launch ("Existing desktop reused pid=" + $pidValue + " port=" + $portValue)
        return $true
    } catch {
        Remove-Item -LiteralPath $AppRuntimeMarker -Force -ErrorAction SilentlyContinue
        return $false
    }
}
function Hash-Root {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($Root).ToLowerInvariant())
        $hash = $sha.ComputeHash($bytes)
        return (($hash[0..7] | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally { $sha.Dispose() }
}
function Test-Python([string]$Exe, [string[]]$Prefix = @()) {
    try {
        $v = & $Exe @Prefix -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $ver = [Version]($v | Select-Object -Last 1)
        if ($ver -lt [Version]"3.11" -or $ver -ge [Version]"3.15") { return $null }
        return [PSCustomObject]@{Exe=$Exe; Prefix=$Prefix; Version=$ver}
    } catch { return $null }
}
function Find-Python {
    if (Test-Path $SetupPython) { $p = Test-Python $SetupPython; if ($p) { return $p } }
    foreach ($c in @(
        [PSCustomObject]@{Exe="py";Prefix=@("-3.14")},
        [PSCustomObject]@{Exe="py";Prefix=@("-3.13")},
        [PSCustomObject]@{Exe="py";Prefix=@("-3.12")},
        [PSCustomObject]@{Exe="py";Prefix=@("-3.11")},
        [PSCustomObject]@{Exe="python";Prefix=@()}
    )) {
        $cmd = Get-Command $c.Exe -ErrorAction SilentlyContinue
        if ($cmd) { $p = Test-Python $cmd.Source $c.Prefix; if ($p) { return $p } }
    }
    return $null
}
function Test-ProjectPython {
    if (-not (Test-Path -LiteralPath $VenvPython)) { return $false }
    try {
        $probe = & $VenvPython -c "import fastapi,uvicorn,requests,pydantic,multipart; print('ok')" 2>$null
        return ($LASTEXITCODE -eq 0 -and ($probe | Select-Object -Last 1) -eq "ok")
    } catch { return $false }
}
function Remove-BrokenVenv {
    if (-not (Test-Path -LiteralPath $VenvDir)) { return }
    if ([IO.Path]::GetFullPath($VenvDir) -ine (Join-Path ([IO.Path]::GetFullPath($Root)) '.venv')) {
        Fail "Refusing to replace a virtual environment outside the project .venv path."
    }
    try {
        Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction Stop
    } catch {
        $stale = Join-Path $Root (".venv.stale-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        try { Move-Item -LiteralPath $VenvDir -Destination $stale -Force -ErrorAction Stop }
        catch { Fail "Existing .venv is broken and could not be replaced. Close Python processes using this project and run START.bat again." }
    }
}
function Invoke-DependencyInstall([string[]]$Packages) {
    # Windows PowerShell 5.1 turns native stderr into errors; pip warnings must
    # not abort installation before its exit status can be inspected.
    $ErrorActionPreference = "Continue"
    $pipArgs = @("-m", "pip", "install", "--disable-pip-version-check", "--retries", "1", "--timeout", "15") + $Packages
    try {
        & $VenvPython @pipArgs *>> $SetupLog
        return ($LASTEXITCODE -eq 0)
    } catch {
        Add-Content -LiteralPath $SetupLog -Value $_.Exception.Message
        return $false
    }
}
function Prepare-Python {
    Step "01" "Python runtime"
    if (Test-ProjectPython) {
        Pass "project runtime ready"
        return
    }

    if (Test-Path -LiteralPath $VenvDir) {
        Warn "project runtime is stale or incomplete; rebuilding .venv"
        Remove-BrokenVenv
    }

    $base = Find-Python
    if (-not $base) { Fail "Python 3.11-3.14 not found. Add Setup\Python312 or install a supported Python." }
    Log-Launch ("Using Python " + $base.Version + " from " + $base.Exe)
    $venvArgs = @($base.Prefix) + @("-m", "venv", $VenvDir)
    try { & $base.Exe @venvArgs | Out-Null } catch { Fail ("Could not create .venv: " + $_.Exception.Message) }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) { Fail "Could not create .venv" }

    $offline = Join-Path $SetupDir "python_packages"
    # This bundle contains an expanded site-packages tree, not pip archives.
    # Probe with the selected interpreter first: native extensions must match it.
    if (Test-Path -LiteralPath (Join-Path $offline "fastapi")) {
        Step "01" "Checking bundled offline packages"
        $compatible = $false
        try {
            & $VenvPython -c "import sys; sys.path.insert(0, sys.argv[1]); import fastapi,uvicorn,requests,pydantic,multipart" $offline *> $SetupLog
            $compatible = ($LASTEXITCODE -eq 0)
        } catch { Add-Content -LiteralPath $SetupLog -Value $_.Exception.Message }
        if ($compatible) {
            try {
                Get-ChildItem -LiteralPath $offline -Force | Copy-Item -Destination (Join-Path $VenvDir "Lib\site-packages") -Recurse -Force
            } catch { Fail ("Could not copy bundled packages: " + $_.Exception.Message) }
            if (Test-ProjectPython) {
                Pass "dependencies loaded from Setup (offline)"
                return
            }
        }
        Warn "bundled packages are incompatible or incomplete; trying package installation"
    }

    $core = @("fastapi>=0.115,<1", "uvicorn>=0.30,<1", "requests>=2.32,<3", "pydantic>=2.8,<3", "python-multipart>=0.0.9,<1")
    # Support wheel caches too, without mistaking expanded packages for wheels.
    $archives = @(Get-ChildItem -LiteralPath $offline -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '\.(whl|zip|tar\.gz)$' })
    $installed = $false
    if ($archives.Count -gt 0) {
        $localArgs = @("--no-index", "--find-links", $offline)
        $installed = Invoke-DependencyInstall ($localArgs + @("-r", $Requirements))
        if (-not $installed) { $installed = Invoke-DependencyInstall ($localArgs + $core) }
    }
    if (-not $installed) {
        Step "01" "Installing Python packages online"
        $installed = Invoke-DependencyInstall @("-r", $Requirements)
        if (-not $installed) {
            Warn "full dependency install failed; retrying core runtime packages"
            $installed = Invoke-DependencyInstall $core
        }
    }
    if (-not $installed) { Fail "Python dependency installation failed. Check data\setup.log; restore compatible Setup resources for offline use or connect to the internet and retry." }

    if (-not (Test-ProjectPython)) { Fail "Python runtime was created but core imports still fail" }
    Pass "dependencies ready"
}
function Prepare-OptionalEdgeTTS {
    # Edge speech is deliberately optional. Do not touch the network for it
    # unless the user both selected Edge and opened the online privacy gate.
    if (-not (Test-Path -LiteralPath $SettingsPath)) { return }
    $enabled = $false
    try {
        $settings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
        $provider = ([string]$settings.tts_provider).Trim().ToLowerInvariant()
        $enabled = [bool]$settings.voice_output_enabled -and [bool]$settings.tts_allow_online -and ($provider -eq "edge")
    } catch {
        Log-Launch "Optional Edge TTS settings could not be read; skipping package preparation"
        return
    }
    if (-not $enabled) { return }

    try {
        & $VenvPython -c "import edge_tts; print('ok')" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { Pass "optional Edge voice support ready"; return }
    } catch {}

    Step "01" "Optional Edge voice support"
    if (Invoke-DependencyInstall @("edge-tts>=6.1,<8")) {
        try {
            & $VenvPython -c "import edge_tts" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { Pass "Edge voice package installed"; return }
        } catch {}
    }
    Warn "Edge voice package unavailable; Studio will keep the device/browser fallback"
    Log-Launch "Optional Edge TTS install unavailable; continuing without blocking Studio"
}
function Get-OllamaExe {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    if ($env:LOCALAPPDATA) {
        $p = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        if (Test-Path $p) { return $p }
    }
    if ($env:ProgramFiles) {
        $p = Join-Path $env:ProgramFiles "Ollama\ollama.exe"
        if (Test-Path $p) { return $p }
    }
    return $null
}
function Test-Ollama([int]$Port) {
    try { Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/tags" -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}
function Register-OllamaRuntime($Record) {
    $records = @()
    if (Test-Path -LiteralPath $OllamaRuntimeRegistry) {
        try {
            $loaded = Get-Content -LiteralPath $OllamaRuntimeRegistry -Raw | ConvertFrom-Json
            if ($loaded -is [System.Array]) { $records = @($loaded) } elseif ($null -ne $loaded) { $records = @($loaded) }
        } catch { $records = @() }
    }
    $pidValue = [int]$Record.pid
    $portValue = [int]$Record.port
    $records = @($records | Where-Object { -not (([int]$_.pid -eq $pidValue) -and ([int]$_.port -eq $portValue)) })
    $records += $Record
    $tmp = $OllamaRuntimeRegistry + '.tmp'
    try {
        @($records) | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tmp -Encoding UTF8
        Move-Item -LiteralPath $tmp -Destination $OllamaRuntimeRegistry -Force
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}
function Invoke-ProjectOllamaCleanup([int]$KeepPid = 0) {
    if (-not (Test-Path -LiteralPath $KillHostScript)) { return }
    try {
        $psArgs = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$KillHostScript,'-ProjectOnly','-BestEffort')
        if ($KeepPid -gt 0) { $psArgs += @('-KeepPid',[string]$KeepPid) }
        & powershell.exe @psArgs *> $null
        if ($LASTEXITCODE -ne 0) { throw ("cleanup exited with code " + $LASTEXITCODE) }
        Log-Launch 'Stale private Ollama cleanup completed before new runtime start'
    } catch {
        $detail = 'Could not clean stale MatrixStudio Ollama runtimes: ' + $_.Exception.Message
        Log-Launch ('FAIL  ' + $detail)
        throw $detail
    }
}
function Prepare-Ollama([string]$Identity) {
    Step "02" "Private Ollama runtime"
    $ollama = Get-OllamaExe
    if (-not $ollama) { Fail "Ollama was not found. Install Ollama; MatrixStudio2.0 uses its executable with a private model store." }
    $store = Join-Path $Root "OllamaModels"
    New-Item -ItemType Directory -Force -Path $store | Out-Null
    $runtimeMarker = Join-Path $DataDir "ollama.runtime.json"
    $port = 0
    $reuse = $false

    if (Test-Path $runtimeMarker) {
        try {
            $mark = Get-Content $runtimeMarker -Raw | ConvertFrom-Json
            if ([string]$mark.identity -eq $Identity -and [string]$mark.store -eq $store -and [int]$mark.port -gt 0 -and [int]$mark.pid -gt 0) {
                $proc = Get-Process -Id ([int]$mark.pid) -ErrorAction Stop
                $sameExe = $false
                try { $sameExe = ([IO.Path]::GetFullPath($proc.Path) -ieq [IO.Path]::GetFullPath($ollama)) } catch {}
                if ($sameExe -and (Test-Ollama ([int]$mark.port))) { $port = [int]$mark.port; $reuse = $true }
            }
        } catch {}
    }

    if (-not $reuse) {
        # A stale marker used to be overwritten here, which could strand older
        # private Ollama servers. Clean every verified runtime owned by this
        # project before allocating another port.
        Invoke-ProjectOllamaCleanup
        $seed = [Convert]::ToUInt32($Identity.Substring(0,8),16)
        $startPort = 11435 + ($seed % 800)
        for ($i=0; $i -lt 100; $i++) {
            $candidate = $startPort + $i
            if (Test-PortFree $candidate) { $port = $candidate; break }
        }
        if ($port -le 0) { Fail "No free private Ollama port was found." }
    }

    $env:OLLAMA_HOST = "127.0.0.1:$port"
    $env:OLLAMA_MODELS = $store
    $env:OLLAMA_NO_CLOUD = "1"
    $env:OLLAMA_FLASH_ATTENTION = "1"
    $env:OLLAMA_KV_CACHE_TYPE = "q8_0"
    $env:OLLAMA_NUM_PARALLEL = "1"
    $env:OLLAMA_MAX_LOADED_MODELS = "1"

    if (-not $reuse) {
        $psi = [Diagnostics.ProcessStartInfo]::new()
        $psi.FileName = $ollama
        $psi.Arguments = "serve"
        $psi.WorkingDirectory = $Root
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $ollamaProcess = [Diagnostics.Process]::Start($psi)
        $ok = $false
        for ($i=0; $i -lt 80; $i++) { Start-Sleep -Milliseconds 250; if (Test-Ollama $port) { $ok=$true; break } }
        if (-not $ok) { Fail "Private Ollama runtime did not become ready" }
        [PSCustomObject]@{ identity=$Identity; pid=$ollamaProcess.Id; port=$port; exe=$ollama; store=$store } |
            ConvertTo-Json | Set-Content -LiteralPath $runtimeMarker -Encoding UTF8
    }
    $verifiedMarker = Get-Content -LiteralPath $runtimeMarker -Raw | ConvertFrom-Json
    $verifiedRuntime = Get-Process -Id ([int]$verifiedMarker.pid) -ErrorAction Stop
    $verifiedMarker | Add-Member -NotePropertyName started -NotePropertyValue ($verifiedRuntime.StartTime.ToUniversalTime().Ticks.ToString()) -Force
    $verifiedMarker | ConvertTo-Json | Set-Content -LiteralPath $runtimeMarker -Encoding UTF8
    Register-OllamaRuntime $verifiedMarker
    if ($reuse) { Invoke-ProjectOllamaCleanup -KeepPid ([int]$verifiedMarker.pid) }
    $runtimeWord = if ($reuse) { "reused" } else { "started" }
    Log-Launch ("Ollama runtime " + $runtimeWord + " pid=" + [string]$verifiedMarker.pid + " port=" + [string]$verifiedMarker.port + " store=" + [string]$verifiedMarker.store)
    $runtimeAction = if ($reuse) { "verified runtime reused" } else { "private runtime started" }
    Pass ($runtimeAction + " @ 127.0.0.1:$port")
    Say ("       STORE  " + $store) DarkGray
    return [PSCustomObject]@{Exe=$ollama; Port=$port; Store=$store; Reused=$reuse}
}
function Write-SettingsJsonAtomic($Object) {
    $tmp = $SettingsPath + ".launcher.tmp"
    try {
        $Object | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding UTF8
        Move-Item -LiteralPath $tmp -Destination $SettingsPath -Force
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}
function Get-ConfiguredModel {
    if (Test-Path $SettingsPath) {
        try {
            $s = Get-Content $SettingsPath -Raw | ConvertFrom-Json
            if ($s.ollama_chat_model) { return [string]$s.ollama_chat_model }
        } catch {}
    }
    return $StarterModel
}
function Set-ConfiguredModel([string]$Model) {
    try {
        $s = if (Test-Path $SettingsPath) { Get-Content $SettingsPath -Raw | ConvertFrom-Json } else { [PSCustomObject]@{} }
        if ($null -eq $s.PSObject.Properties["ollama_chat_model"]) { $s | Add-Member -NotePropertyName ollama_chat_model -NotePropertyValue $Model }
        else { $s.ollama_chat_model = $Model }
        Write-SettingsJsonAtomic $s
    } catch { Warn "could not update selected model in settings" }
}
function Get-InstalledModels([int]$Port) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/tags" -TimeoutSec 4
        return @($r.models | ForEach-Object { if ($_.name) { [string]$_.name } elseif ($_.model) { [string]$_.model } } | Where-Object { $_ })
    } catch { return @() }
}
function Ensure-ChatModel($Runtime) {
    Step "03" "Chat model preflight"
    $configured = Get-ConfiguredModel
    $models = @(Get-InstalledModels $Runtime.Port)
    if ($models -contains $configured) { Pass "$configured ready"; return }
    if ($models.Count -gt 0) {
        $fallback = [string]$models[0]
        Set-ConfiguredModel $fallback
        Pass "selected installed model $fallback"
        return
    }

    Warn "project model store is empty"
    Say "       FIRST RUN  installing starter model $configured" Cyan
    Say "       This happens once and stays inside .\OllamaModels" DarkGray
    Write-Host ""
    & $Runtime.Exe pull $configured
    $code = $LASTEXITCODE
    Write-Host ""
    $models = @(Get-InstalledModels $Runtime.Port)
    if ($code -eq 0 -and $models.Count -gt 0) {
        if (-not ($models -contains $configured)) { $configured = [string]$models[0] }
        Set-ConfiguredModel $configured
        Pass "$configured installed and ready"
    } else {
        Warn "starter model was not installed; Studio will open with a one-click model installer"
    }
}
function Get-AppPort {
    $preferred = 8765
    if (Test-Path $SettingsPath) {
        try {
            $rawPort = [int]((Get-Content $SettingsPath -Raw | ConvertFrom-Json).port)
            if ($rawPort -ge 1024 -and $rawPort -le 65535) {
                $preferred = $rawPort
            } else {
                Log-Launch ("Ignoring invalid saved app port " + $rawPort + "; using 8765")
            }
        } catch {
            Log-Launch "Could not read saved app port; using 8765"
        }
    }

    $end = [Math]::Min(65535, $preferred + 199)
    for ($p=$preferred; $p -le $end; $p++) {
        if ($p -ge 1024 -and (Test-PortFree $p)) { return $p }
    }

    # If a saved high port left too little scan space, fall back to the normal range.
    if ($preferred -ne 8765) {
        for ($p=8765; $p -le 8964; $p++) { if (Test-PortFree $p) { return $p } }
    }
    Fail "No free MatrixStudio2.0 app port found"
}
function Set-ConfiguredPort([int]$Port) {
    if ($Port -lt 1024 -or $Port -gt 65535) { return }
    try {
        $s = if (Test-Path $SettingsPath) { Get-Content $SettingsPath -Raw | ConvertFrom-Json } else { [PSCustomObject]@{} }
        if ($null -eq $s.PSObject.Properties["port"]) { $s | Add-Member -NotePropertyName port -NotePropertyValue $Port }
        else { $s.port = $Port }
        Write-SettingsJsonAtomic $s
    } catch {
        Log-Launch ("Could not persist repaired app port " + $Port)
    }
}

trap {
    $message = $_.Exception.Message
    Log-Launch ("UNHANDLED  " + $message)
    Write-Host ""
    Write-Host "  STARTUP ERROR  " -NoNewline -ForegroundColor Red
    Write-Host $message -ForegroundColor Red
    Write-Host "  See data\launch.log for details." -ForegroundColor DarkGray
    exit 1
}

Banner
Log-Launch ("START  " + $BuildId + " root=" + $Root)
if (Test-ExistingStudio) { Start-Sleep -Milliseconds 150; exit 0 }
Prepare-Python
Prepare-OptionalEdgeTTS
$id = Hash-Root
$runtime = Prepare-Ollama $id
Ensure-ChatModel $runtime
Step "04" "Desktop interface"
$appPort = Get-AppPort
Set-ConfiguredPort $appPort
$env:MATRIXSTUDIO2_INSTANCE_ID = "ms2-$id"
$env:MATRIXSTUDIO2_PORT = [string]$appPort
Remove-Item $ReadyMarker -Force -ErrorAction SilentlyContinue
$launchTag = (Get-Date -Format "yyyyMMdd-HHmmssfff") + "-" + $PID
$stdoutLog = Join-Path $DataDir ("server.stdout." + $launchTag + ".log")
$stderrLog = Join-Path $DataDir ("server.stderr." + $launchTag + ".log")
Log-Launch ("Launching desktop on port " + $appPort + " with " + $VenvPython)
try {
    $proc = Start-Process -FilePath $VenvPython -ArgumentList ('"' + (Join-Path $Root 'app.py') + '"') -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
} catch {
    Fail ("Could not start desktop process: " + $_.Exception.Message)
}
Pass "desktop process started"
try {
    [PSCustomObject]@{ pid=$proc.Id; port=$appPort; instance_id=$env:MATRIXSTUDIO2_INSTANCE_ID; root=$Root; started_at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds() } |
        ConvertTo-Json | Set-Content -LiteralPath $AppRuntimeMarker -Encoding UTF8
} catch {}
Log-Launch ("Desktop process initiated pid=" + $proc.Id + "; launcher handoff complete")
Say "       HANDOFF  desktop interface initiated" DarkGray
Start-Sleep -Milliseconds 250
exit 0
