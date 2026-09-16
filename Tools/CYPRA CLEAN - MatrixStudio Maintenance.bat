@echo off
setlocal EnableExtensions DisableDelayedExpansion

:: MATRIXSTUDIO2.0 // CYPRA CLEAN // Windows Space Recovery
:: Safe single-file cleanup utility using Windows built-ins only.
:: MatrixStudio integration build: 2.3.13-quiet-rag-cleaner-fix-20260916
:: Structured task states: [PASS] [WARN] [SKIP] [FAIL]

chcp 65001 >nul 2>&1

set "CYPRA_MODE=MENU"
if /i "%~1"=="--scan" set "CYPRA_MODE=SCAN"

for %%I in ("%~dp0..") do set "CYPRA_ROOT=%%~fI"
set "CYPRA_LOG_DIR=%CYPRA_ROOT%\Logs\CypraClean"
if not exist "%CYPRA_LOG_DIR%" mkdir "%CYPRA_LOG_DIR%" >nul 2>&1
if not exist "%CYPRA_LOG_DIR%" set "CYPRA_LOG_DIR=%TEMP%\CypraCleanLogs"
if not exist "%CYPRA_LOG_DIR%" mkdir "%CYPRA_LOG_DIR%" >nul 2>&1

for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "CYPRA_STAMP=%%T"
if not defined CYPRA_STAMP set "CYPRA_STAMP=session"
set "CYPRA_LOG=%CYPRA_LOG_DIR%\CypraClean_%CYPRA_STAMP%.log"
set "CYPRA_SCAN_CACHE=%TEMP%\CypraClean_%RANDOM%_%RANDOM%.scan.txt"
set "CYPRA_ADMIN=NO"
set "CYPRA_SHOW_SNAPSHOT=1"
set "CYPRA_TASK=SESSION"
if /i "%CYPRA_MODE%"=="SCAN" goto SCAN_ONLY

:: Reliable administrator check. This does not depend on the Server service.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent()); if($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 0}else{exit 1}" >nul 2>&1
if errorlevel 1 (
  cls
  title MatrixStudio2.0 // CYPRA CLEAN // Administrator Access Required
  color 0A
  call :ELEVATION_SPLASH
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

:: Verify elevation a second time after UAC relaunch.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent()); if($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 0}else{exit 1}" >nul 2>&1
if errorlevel 1 (
  cls
  color 0C
  echo.
  echo   CYPRA CLEAN could not verify Administrator access.
  echo   No cleanup was performed.
  echo.
  call :LOG "[FAIL] ADMINISTRATOR // elevation could not be verified"
  pause
  exit /b 1
)
set "CYPRA_ADMIN=YES"
call :LOG "SESSION START // mode=MENU // root=%CYPRA_ROOT%"
call :LOG "ADMINISTRATOR VERIFIED"

mode con: cols=86 lines=38 >nul 2>&1
title MatrixStudio2.0 // CYPRA CLEAN // SYSTEM MAINTENANCE // ADMIN
color 07

goto MENU

:SCAN_ONLY
call :LOG "SESSION START // mode=SCAN // root=%CYPRA_ROOT%"
mode con: cols=86 lines=38 >nul 2>&1
title MatrixStudio2.0 // CYPRA CLEAN // READ-ONLY SCAN
color 07
cls
call :HEADER
call :SECTION_TITLE "READ-ONLY SCAN"
echo   No files or services will be changed.
echo   Large folders can take a moment to measure.
echo.
call :FULL_SCAN
call :SHOW_LOG_PATH
call :LOG "SESSION END // read-only scan"
if exist "%CYPRA_SCAN_CACHE%" del /q "%CYPRA_SCAN_CACHE%" >nul 2>&1
endlocal
exit /b 0

:MENU
cls
call :HEADER
call :SHOW_DRIVE
if "%CYPRA_SHOW_SNAPSHOT%"=="1" (
  echo.
  call :QUICK_SNAPSHOT
  set "CYPRA_SHOW_SNAPSHOT=0"
)
echo.
call :MENU_GRID
echo.
echo   [SAFE] routine cleanup   [ADMIN] protected system task   [WARN] irreversible
echo   Session log: %CYPRA_LOG%
echo.
set "CYPRA_CHOICE="
set /p "CYPRA_CHOICE=  Select: "
if /i "%CYPRA_CHOICE%"=="1" goto QUICK_SAFE
if /i "%CYPRA_CHOICE%"=="2" goto WINDOWS_UPDATE
if /i "%CYPRA_CHOICE%"=="3" goto WINDOWS_OLD
if /i "%CYPRA_CHOICE%"=="4" goto COMPONENT_STORE
if /i "%CYPRA_CHOICE%"=="5" goto TEMP_FILES
if /i "%CYPRA_CHOICE%"=="6" goto DELIVERY_OPT
if /i "%CYPRA_CHOICE%"=="7" goto RECYCLE_BIN
if /i "%CYPRA_CHOICE%"=="8" goto BROWSER_CACHE
if /i "%CYPRA_CHOICE%"=="9" goto ANALYZER
if /i "%CYPRA_CHOICE%"=="A" goto RECOMMENDED
if /i "%CYPRA_CHOICE%"=="R" goto RESTORE_POINT
if /i "%CYPRA_CHOICE%"=="0" goto EXIT

echo.
powershell -NoProfile -Command "Write-Host '  [WARN] Invalid selection.' -ForegroundColor Yellow"
timeout /t 1 /nobreak >nul
goto MENU

:ELEVATION_SPLASH
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$width=80;" ^
 "$colors=@('DarkGreen','Green','Cyan','Green','DarkCyan','Gray'); $counts=@(14,14,13,13,13,13);" ^
 "function Center([string]$s){if($s.Length -gt $width){$s=$s.Substring(0,$width)}; $l=[math]::Floor(($width-$s.Length)/2); return $s.PadLeft($s.Length+$l).PadRight($width)};" ^
 "Write-Host '+' -NoNewline -ForegroundColor DarkGray; for($i=0;$i -lt $colors.Count;$i++){Write-Host ('='*$counts[$i]) -NoNewline -ForegroundColor $colors[$i]}; Write-Host '+' -ForegroundColor DarkGray;" ^
 "Write-Host '|' -NoNewline -ForegroundColor DarkGray; Write-Host (Center 'MATRIXSTUDIO2.0 // CYPRA CLEAN') -NoNewline -ForegroundColor Cyan; Write-Host '|' -ForegroundColor DarkGray;" ^
 "Write-Host '|' -NoNewline -ForegroundColor DarkGray; Write-Host (Center 'SYSTEM MAINTENANCE // ADMINISTRATOR ACCESS REQUIRED') -NoNewline -ForegroundColor Yellow; Write-Host '|' -ForegroundColor DarkGray;" ^
 "Write-Host '+' -NoNewline -ForegroundColor DarkGray; Write-Host ('-'*$width) -NoNewline -ForegroundColor DarkGray; Write-Host '+' -ForegroundColor DarkGray;" ^
 "Write-Host ''; Write-Host '  MatrixStudio is requesting Administrator access for CYPRA CLEAN.' -ForegroundColor White; Write-Host '  Nothing is deleted before elevation succeeds.' -ForegroundColor Green; Write-Host ''"
exit /b

:HEADER
set "CYPRA_HEADER_MODE=READ-ONLY SCAN"
if /i "%CYPRA_ADMIN%"=="YES" set "CYPRA_HEADER_MODE=ADMINISTRATOR: VERIFIED"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$width=80;" ^
 "$colors=@('DarkGreen','Green','Cyan','Green','DarkCyan','Gray'); $counts=@(14,14,13,13,13,13);" ^
 "function Center([string]$s){if($s.Length -gt $width){$s=$s.Substring(0,$width)}; $l=[math]::Floor(($width-$s.Length)/2); return $s.PadLeft($s.Length+$l).PadRight($width)};" ^
 "$build=[Environment]::OSVersion.Version.Build; $who=[Environment]::UserName; $status=('%CYPRA_HEADER_MODE%  |  WINDOWS {0}  |  {1}' -f $build,$who);" ^
 "Write-Host '+' -NoNewline -ForegroundColor DarkGray; for($i=0;$i -lt $colors.Count;$i++){Write-Host ('='*$counts[$i]) -NoNewline -ForegroundColor $colors[$i]}; Write-Host '+' -ForegroundColor DarkGray;" ^
 "Write-Host '|' -NoNewline -ForegroundColor DarkGray; Write-Host (Center 'MATRIXSTUDIO2.0 // SYSTEM MAINTENANCE') -NoNewline -ForegroundColor Cyan; Write-Host '|' -ForegroundColor DarkGray;" ^
 "Write-Host '|' -NoNewline -ForegroundColor DarkGray; Write-Host (Center 'CYPRA CLEAN // WINDOWS SPACE RECOVERY') -NoNewline -ForegroundColor Green; Write-Host '|' -ForegroundColor DarkGray;" ^
 "Write-Host '|' -NoNewline -ForegroundColor DarkGray; Write-Host (Center $status) -NoNewline -ForegroundColor Green; Write-Host '|' -ForegroundColor DarkGray;" ^
 "Write-Host '+' -NoNewline -ForegroundColor DarkGray; Write-Host ('-' * $width) -NoNewline -ForegroundColor DarkGray; Write-Host '+' -ForegroundColor DarkGray"
set "CYPRA_HEADER_MODE="
exit /b

:MENU_GRID
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$w=80; $l=40; $r=40;" ^
 "function Row([string]$a,[string]$b,[ConsoleColor]$ca,[ConsoleColor]$cb){Write-Host '|' -NoNewline -ForegroundColor DarkGray; Write-Host $a.PadRight($l) -NoNewline -ForegroundColor $ca; Write-Host $b.PadRight($r) -NoNewline -ForegroundColor $cb; Write-Host '|' -ForegroundColor DarkGray};" ^
 "Write-Host '+' -NoNewline -ForegroundColor DarkGray; Write-Host ('-'*$w) -NoNewline -ForegroundColor DarkGray; Write-Host '+' -ForegroundColor DarkGray;" ^
 "Row ' [SAFE]  [1] QUICK SAFE CLEAN' ' [SAFE]  [6] DELIVERY OPTIMIZATION' Green Green;" ^
 "Row ' [ADMIN] [2] WINDOWS UPDATE CLEANUP' ' [WARN]  [7] RECYCLE BIN' Cyan Yellow;" ^
 "Row ' [WARN]  [3] PREVIOUS WINDOWS / OLD' ' [SAFE]  [8] BROWSER CACHES' Yellow Green;" ^
 "Row ' [ADMIN] [4] COMPONENT STORE' ' [SCAN]  [9] FULL SPACE ANALYZER' Cyan Cyan;" ^
 "Row ' [SAFE]  [5] TEMPORARY FILES' ' [SAFE]  [A] RECOMMENDED CLEANUP' Green Green;" ^
 "Row ' [ADMIN] [R] CREATE RESTORE POINT' '         [0] EXIT' Cyan Gray;" ^
 "Write-Host '+' -NoNewline -ForegroundColor DarkGray; Write-Host ('-'*$w) -NoNewline -ForegroundColor DarkGray; Write-Host '+' -ForegroundColor DarkGray"
exit /b

:SHOW_DRIVE
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=$env:SystemDrive.Substring(0,1); $x=Get-PSDrive -Name $d; $f=[math]::Round($x.Free/1GB,1); $u=[math]::Round($x.Used/1GB,1); Write-Host ('  System drive {0}  {1} GB free  |  {2} GB used' -f $env:SystemDrive,$f,$u) -ForegroundColor Gray"
exit /b

:SHOW_LOG_PATH
powershell -NoProfile -ExecutionPolicy Bypass -Command "Write-Host ''; Write-Host ('  SESSION LOG  ' + $env:CYPRA_LOG) -ForegroundColor DarkGray"
exit /b

:SECTION_TITLE
set "CYPRA_SECTION=%~1"
powershell -NoProfile -Command "$s=$env:CYPRA_SECTION; Write-Host ''; Write-Host ('  // ' + $s) -ForegroundColor Cyan; Write-Host ('  ' + ('-'*76)) -ForegroundColor DarkGray"
set "CYPRA_SECTION="
exit /b

:LOG
set "CYPRA_LOG_MSG=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$line=('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),$env:CYPRA_LOG_MSG); Add-Content -LiteralPath $env:CYPRA_LOG -Value $line -Encoding UTF8" >nul 2>&1
set "CYPRA_LOG_MSG="
exit /b

:RESULT
set "CYPRA_RES_STATE=%~1"
set "CYPRA_RES_TASK=%~2"
set "CYPRA_RES_DETAIL=%~3"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$s=$env:CYPRA_RES_STATE; $t=$env:CYPRA_RES_TASK; $d=$env:CYPRA_RES_DETAIL;" ^
 "$c=if($s -eq 'PASS'){'Green'}elseif($s -eq 'WARN'){'Yellow'}elseif($s -eq 'SKIP'){'DarkGray'}else{'Red'};" ^
 "$line=if($d){'  ['+$s+'] '+$t+' // '+$d}else{'  ['+$s+'] '+$t};" ^
 "Write-Host $line -ForegroundColor $c; Add-Content -LiteralPath $env:CYPRA_LOG -Value (('[{0}] ' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))+$line.Trim()) -Encoding UTF8"
set "CYPRA_RES_STATE="
set "CYPRA_RES_TASK="
set "CYPRA_RES_DETAIL="
exit /b

:BEGIN_MEASURE
set "CYPRA_BEFORE="
for /f "delims=" %%B in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=$env:SystemDrive.Substring(0,1); [int64](Get-PSDrive -Name $d).Free"') do set "CYPRA_BEFORE=%%B"
call :LOG "TASK START // %CYPRA_TASK% // free=%CYPRA_BEFORE%"
exit /b

:END_MEASURE
set "CYPRA_AFTER="
for /f "delims=" %%B in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=$env:SystemDrive.Substring(0,1); [int64](Get-PSDrive -Name $d).Free"') do set "CYPRA_AFTER=%%B"
set "CYPRA_M_BEFORE=%CYPRA_BEFORE%"
set "CYPRA_M_AFTER=%CYPRA_AFTER%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$b=[int64]$env:CYPRA_M_BEFORE; $a=[int64]$env:CYPRA_M_AFTER; $r=[math]::Max(0,$a-$b);" ^
 "if($r -ge 1GB){$v='{0:N2} GB' -f ($r/1GB)}elseif($r -ge 1MB){$v='{0:N0} MB' -f ($r/1MB)}elseif($r -ge 1KB){$v='{0:N0} KB' -f ($r/1KB)}else{$v='{0} B' -f $r};" ^
 "$line=('  [INFO] SPACE DELTA // reclaimed this task: {0}' -f $v); Write-Host $line -ForegroundColor Cyan; Add-Content -LiteralPath $env:CYPRA_LOG -Value (('[{0}] ' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))+$line.Trim()) -Encoding UTF8"
call :LOG "TASK END // %CYPRA_TASK% // free=%CYPRA_AFTER%"
set "CYPRA_M_BEFORE="
set "CYPRA_M_AFTER="
exit /b

:QUICK_SNAPSHOT
call :SECTION_TITLE "PRE-CLEAN SNAPSHOT"
echo   Estimated disposable data. Windows.old and component store use the full analyzer.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='SilentlyContinue';" ^
 "function Size([string[]]$paths){[int64]$sum=0;$seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase);foreach($p in $paths){foreach($i in @(Get-Item -Path $p -Force -ErrorAction SilentlyContinue)){if(-not $i){continue};if(-not $seen.Add($i.FullName)){continue};if($i.PSIsContainer){$m=Get-ChildItem -LiteralPath $i.FullName -Recurse -Force -File -ErrorAction SilentlyContinue|Measure-Object Length -Sum;if($m.Sum){$sum += [int64]$m.Sum}}elseif($i.Length){$sum += [int64]$i.Length}}};$sum};" ^
 "function F([int64]$b){if($b -ge 1GB){'{0:N2} GB'-f($b/1GB)}elseif($b -ge 1MB){'{0:N0} MB'-f($b/1MB)}elseif($b -ge 1KB){'{0:N0} KB'-f($b/1KB)}else{'{0} B'-f$b}};" ^
 "$temp=Size @($env:TEMP,(Join-Path $env:LOCALAPPDATA 'Temp'),(Join-Path $env:SystemRoot 'Temp'),(Join-Path $env:LOCALAPPDATA 'CrashDumps'),(Join-Path $env:LOCALAPPDATA 'D3DSCache'),(Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportArchive'),(Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportQueue'));" ^
 "$update=Size @((Join-Path $env:SystemRoot 'SoftwareDistribution\Download'));" ^
 "$recycle=Size @((Join-Path $env:SystemDrive '$Recycle.Bin'));" ^
 "[int64]$do=0;try{$snap=Get-DeliveryOptimizationPerfSnap -ErrorAction Stop;if($snap.CacheSizeBytes){$do=[int64]$snap.CacheSizeBytes}}catch{};" ^
 "$total=$temp+$update+$recycle+$do;" ^
 "$rows=@(@('Temp + diagnostics',$temp),@('Windows Update downloads',$update),@('Recycle Bin',$recycle),@('Delivery Optimization',$do));foreach($r in $rows){Write-Host ('  {0,-31} {1,14}' -f $r[0],(F ([int64]$r[1]))) -ForegroundColor Gray};" ^
 "if(Test-Path (Join-Path $env:SystemDrive 'Windows.old')){Write-Host ('  {0,-31} {1,14}' -f 'Windows.old','FULL SCAN') -ForegroundColor Yellow};" ^
 "Write-Host ('  {0,-31} {1,14}' -f 'Known disposable subtotal',(F $total)) -ForegroundColor Green;" ^
 "$msg=('SNAPSHOT // temp={0} update={1} recycle={2} delivery={3} subtotal={4}' -f $temp,$update,$recycle,$do,$total);Add-Content -LiteralPath $env:CYPRA_LOG -Value (('[{0}] ' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))+$msg) -Encoding UTF8"
exit /b

:FULL_SCAN
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='SilentlyContinue';" ^
 "function Size([string[]]$paths){[int64]$sum=0;$seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase);foreach($p in $paths){foreach($i in @(Get-Item -Path $p -Force -ErrorAction SilentlyContinue)){if(-not $i){continue};if(-not $seen.Add($i.FullName)){continue};if($i.PSIsContainer){$m=Get-ChildItem -LiteralPath $i.FullName -Recurse -Force -File -ErrorAction SilentlyContinue|Measure-Object Length -Sum;if($m.Sum){$sum += [int64]$m.Sum}}elseif($i.Length){$sum += [int64]$i.Length}}};$sum};" ^
 "function F([int64]$b){if($b -ge 1GB){'{0:N2} GB'-f($b/1GB)}elseif($b -ge 1MB){'{0:N0} MB'-f($b/1MB)}elseif($b -ge 1KB){'{0:N0} KB'-f($b/1KB)}else{'{0} B'-f$b}};" ^
 "$browser=@((Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\*\Cache\Cache_Data'),(Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\*\Code Cache'),(Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\*\GPUCache'),(Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\*\Cache\Cache_Data'),(Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\*\Code Cache'),(Join-Path $env:LOCALAPPDATA 'Mozilla\Firefox\Profiles\*\cache2'),(Join-Path $env:LOCALAPPDATA 'BraveSoftware\Brave-Browser\User Data\*\Cache\Cache_Data'),(Join-Path $env:LOCALAPPDATA 'Opera Software\Opera Stable\Cache'),(Join-Path $env:LOCALAPPDATA 'Opera Software\Opera GX Stable\Cache'));" ^
 "$rows=@();$rows += [pscustomobject]@{Name='Windows.old';Bytes=(Size @((Join-Path $env:SystemDrive 'Windows.old')))};$rows += [pscustomobject]@{Name='Temp + diagnostics';Bytes=(Size @($env:TEMP,(Join-Path $env:LOCALAPPDATA 'Temp'),(Join-Path $env:SystemRoot 'Temp'),(Join-Path $env:LOCALAPPDATA 'CrashDumps'),(Join-Path $env:LOCALAPPDATA 'D3DSCache'),(Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportArchive'),(Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportQueue')))};$rows += [pscustomobject]@{Name='Windows Update downloads';Bytes=(Size @((Join-Path $env:SystemRoot 'SoftwareDistribution\Download')))};$rows += [pscustomobject]@{Name='Browser caches';Bytes=(Size $browser)};$rows += [pscustomobject]@{Name='Recycle Bin';Bytes=(Size @((Join-Path $env:SystemDrive '$Recycle.Bin')))};[int64]$do=0;try{$snap=Get-DeliveryOptimizationPerfSnap -ErrorAction Stop;if($snap.CacheSizeBytes){$do=[int64]$snap.CacheSizeBytes}}catch{};$rows += [pscustomobject]@{Name='Delivery Optimization';Bytes=$do};" ^
 "$total=[int64](($rows|Measure-Object Bytes -Sum).Sum);Write-Host '  CATEGORY                          ESTIMATED SIZE' -ForegroundColor DarkGray;Write-Host '  ------------------------------------------------' -ForegroundColor DarkGray;foreach($r in $rows){Write-Host ('  {0,-31} {1,14}' -f $r.Name,(F $r.Bytes))};Write-Host '  ------------------------------------------------' -ForegroundColor DarkGray;Write-Host ('  {0,-31} {1,14}' -f 'Potential recoverable',(F $total)) -ForegroundColor Green;" ^
 "$lines=@('FULL SCAN');$lines += $rows|ForEach-Object{('{0}={1}'-f $_.Name,$_.Bytes)};$lines += ('Potential recoverable={0}'-f$total);Add-Content -LiteralPath $env:CYPRA_LOG -Value $lines -Encoding UTF8"
exit /b

:CORE_TEMP
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='SilentlyContinue';$paths=@($env:TEMP,(Join-Path $env:LOCALAPPDATA 'Temp'),(Join-Path $env:SystemRoot 'Temp'),(Join-Path $env:LOCALAPPDATA 'CrashDumps'),(Join-Path $env:LOCALAPPDATA 'D3DSCache'),(Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportArchive'),(Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportQueue'));" ^
 "function CountBytes(){[int64]$b=0;[int]$c=0;$seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase);foreach($p in $paths){foreach($i in @(Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue)){if(-not $i -or -not $seen.Add($i.FullName)){continue};$m=Get-ChildItem -LiteralPath $i.FullName -Recurse -Force -File -ErrorAction SilentlyContinue|Measure-Object Length -Sum;$c += [int]$m.Count;if($m.Sum){$b += [int64]$m.Sum}}};@($c,$b)};" ^
 "$before=CountBytes;if($before[0] -eq 0){exit 10};foreach($p in $paths){if(Test-Path -LiteralPath $p){Get-ChildItem -LiteralPath $p -Force -ErrorAction SilentlyContinue|Remove-Item -Recurse -Force -ErrorAction SilentlyContinue}};$after=CountBytes;if($after[0] -lt $before[0] -or $after[1] -lt $before[1]){exit 0}else{exit 20}"
set "CYPRA_RC=%errorlevel%"
if "%CYPRA_RC%"=="0" call :RESULT PASS "TEMP + DIAGNOSTICS" "cleanup verified"
if "%CYPRA_RC%"=="10" call :RESULT SKIP "TEMP + DIAGNOSTICS" "nothing disposable found"
if "%CYPRA_RC%"=="20" call :RESULT FAIL "TEMP + DIAGNOSTICS" "no measurable reduction; files may be locked"
exit /b

:CORE_DELIVERY
powershell -NoProfile -ExecutionPolicy Bypass -Command "if(-not (Get-Command Delete-DeliveryOptimizationCache -ErrorAction SilentlyContinue)){exit 10};try{Delete-DeliveryOptimizationCache -Force -ErrorAction Stop;exit 0}catch{exit 20}"
set "CYPRA_RC=%errorlevel%"
if "%CYPRA_RC%"=="0" call :RESULT PASS "DELIVERY OPTIMIZATION" "cache command completed"
if "%CYPRA_RC%"=="10" call :RESULT SKIP "DELIVERY OPTIMIZATION" "cleanup API unavailable on this Windows build"
if "%CYPRA_RC%"=="20" call :RESULT FAIL "DELIVERY OPTIMIZATION" "Windows rejected the cleanup request"
exit /b

:CORE_WINDOWS_UPDATE
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='Stop';$names=@('wuauserv','bits');$running=@{};$restoreFailed=$false;$rc=0;$target=Join-Path $env:SystemRoot 'SoftwareDistribution\Download';" ^
 "foreach($n in $names){try{$s=Get-Service -Name $n -ErrorAction Stop;$running[$n]=($s.Status -eq 'Running')}catch{$running[$n]=$false}};" ^
 "try{foreach($n in $names){if($running[$n]){Stop-Service -Name $n -Force -ErrorAction Stop}};if(-not(Test-Path -LiteralPath $target)){ $rc=10 }else{$before=@(Get-ChildItem -LiteralPath $target -Force -Recurse -File -ErrorAction SilentlyContinue).Count;if($before -eq 0){$rc=10}else{Get-ChildItem -LiteralPath $target -Force -ErrorAction SilentlyContinue|Remove-Item -Recurse -Force -ErrorAction SilentlyContinue;$after=@(Get-ChildItem -LiteralPath $target -Force -Recurse -File -ErrorAction SilentlyContinue).Count;if($after -lt $before){$rc=0}else{$rc=20}}}}catch{$rc=20}finally{foreach($n in $names){if($running[$n]){try{Start-Service -Name $n -ErrorAction Stop}catch{$restoreFailed=$true}}}};" ^
 "if($restoreFailed){exit 30};exit $rc"
set "CYPRA_RC=%errorlevel%"
if "%CYPRA_RC%"=="0" call :RESULT PASS "WINDOWS UPDATE DOWNLOADS" "cache reduced and prior service state restored"
if "%CYPRA_RC%"=="10" call :RESULT SKIP "WINDOWS UPDATE DOWNLOADS" "download cache is already empty"
if "%CYPRA_RC%"=="20" call :RESULT FAIL "WINDOWS UPDATE DOWNLOADS" "cache could not be reduced"
if "%CYPRA_RC%"=="30" call :RESULT FAIL "WINDOWS UPDATE SERVICES" "cleanup ran but previous service state could not be fully restored"
exit /b

:CORE_COMPONENT_STORE
powershell -NoProfile -Command "Write-Host '  [ADMIN] Running supported Windows component cleanup...' -ForegroundColor Cyan; Write-Host '          This can take a while.' -ForegroundColor DarkGray"
Dism.exe /Online /Cleanup-Image /StartComponentCleanup
if errorlevel 1 (
  call :RESULT FAIL "COMPONENT STORE" "DISM returned an error"
) else (
  call :RESULT PASS "COMPONENT STORE" "DISM cleanup completed"
)
exit /b

:CORE_BROWSER_CACHE
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='SilentlyContinue';$log=$env:CYPRA_LOG;$defs=@(" ^
 "@{Name='Edge';Proc='msedge';Paths=@((Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\*\Cache\Cache_Data'),(Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\*\Code Cache'),(Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\*\GPUCache'))}," ^
 "@{Name='Chrome';Proc='chrome';Paths=@((Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\*\Cache\Cache_Data'),(Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\*\Code Cache'),(Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\*\GPUCache'))}," ^
 "@{Name='Firefox';Proc='firefox';Paths=@((Join-Path $env:LOCALAPPDATA 'Mozilla\Firefox\Profiles\*\cache2'))}," ^
 "@{Name='Brave';Proc='brave';Paths=@((Join-Path $env:LOCALAPPDATA 'BraveSoftware\Brave-Browser\User Data\*\Cache\Cache_Data'),(Join-Path $env:LOCALAPPDATA 'BraveSoftware\Brave-Browser\User Data\*\Code Cache'))}," ^
 "@{Name='Opera / GX';Proc='opera';Paths=@((Join-Path $env:LOCALAPPDATA 'Opera Software\Opera Stable\Cache'),(Join-Path $env:LOCALAPPDATA 'Opera Software\Opera GX Stable\Cache'),(Join-Path $env:APPDATA 'Opera Software\Opera Stable\Cache'),(Join-Path $env:APPDATA 'Opera Software\Opera GX Stable\Cache'))});" ^
 "function Emit($state,$name,$detail){$c=if($state -eq 'PASS'){'Green'}elseif($state -eq 'SKIP'){'DarkGray'}else{'Red'};$line=('  [{0}] BROWSER {1} // {2}'-f$state,$name,$detail);Write-Host $line -ForegroundColor $c;Add-Content -LiteralPath $log -Value (('[{0}] '-f(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))+$line.Trim()) -Encoding UTF8};" ^
 "foreach($b in $defs){if(Get-Process -Name $b.Proc -ErrorAction SilentlyContinue){Emit 'SKIP' $b.Name 'browser is running';continue};$found=@();foreach($pat in $b.Paths){$found += @(Get-Item -Path $pat -Force -ErrorAction SilentlyContinue|Where-Object{$_.PSIsContainer})};if(-not $found){Emit 'SKIP' $b.Name 'cache not found';continue};$before=@($found|ForEach-Object{Get-ChildItem -LiteralPath $_.FullName -Recurse -Force -File -ErrorAction SilentlyContinue}).Count;foreach($i in $found){Remove-Item -LiteralPath $i.FullName -Recurse -Force -ErrorAction SilentlyContinue};$remain=0;foreach($pat in $b.Paths){$remain += @(Get-Item -Path $pat -Force -ErrorAction SilentlyContinue).Count};if($remain -eq 0){Emit 'PASS' $b.Name ('cache removed; files scanned='+$before)}else{Emit 'FAIL' $b.Name 'some cache folders remain'}}"
exit /b

:CORE_RECYCLE_BIN
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='SilentlyContinue';$drives=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'|Where-Object{$_.DeviceID -match '^[A-Za-z]:$'});if(-not $drives){exit 10};" ^
 "function CountPayload(){[int]$count=0;foreach($d in $drives){$bin=$d.DeviceID+'\$Recycle.Bin';if(Test-Path -LiteralPath $bin){$count += @(Get-ChildItem -LiteralPath $bin -Force -Recurse -File -ErrorAction SilentlyContinue|Where-Object{$_.Name -match '^\$[IR]'}).Count}};return $count};" ^
 "$before=CountPayload;if($before -eq 0){exit 10};$commandFailed=$false;foreach($d in $drives){$bin=$d.DeviceID+'\$Recycle.Bin';if(-not(Test-Path -LiteralPath $bin)){continue};$driveCount=@(Get-ChildItem -LiteralPath $bin -Force -Recurse -File -ErrorAction SilentlyContinue|Where-Object{$_.Name -match '^\$[IR]'}).Count;if($driveCount -le 0){continue};try{Clear-RecycleBin -DriveLetter $d.DeviceID.Substring(0,1) -Force -ErrorAction Stop|Out-Null}catch{$commandFailed=$true}};" ^
 "$remain=$before;for($i=0;$i -lt 20;$i++){Start-Sleep -Milliseconds 250;$remain=CountPayload;if($remain -eq 0){exit 0}};if($remain -lt $before){exit 20};if($commandFailed){exit 30};exit 20"
set "CYPRA_RC=%errorlevel%"
if "%CYPRA_RC%"=="0" call :RESULT PASS "RECYCLE BIN" "Windows reports the recycle payload is empty"
if "%CYPRA_RC%"=="10" call :RESULT SKIP "RECYCLE BIN" "already empty"
if "%CYPRA_RC%"=="20" call :RESULT WARN "RECYCLE BIN" "cleanup ran; protected or transient recycle metadata is still visible"
if "%CYPRA_RC%"=="30" call :RESULT FAIL "RECYCLE BIN" "Windows rejected the recycle cleanup request"
exit /b

:QUICK_SAFE
cls
call :HEADER
call :SECTION_TITLE "QUICK SAFE CLEAN"
echo   Disposable temp, diagnostic, shader, and Delivery Optimization caches.
echo.
set "CYPRA_TASK=QUICK SAFE CLEAN"
call :BEGIN_MEASURE
call :CORE_TEMP
call :CORE_DELIVERY
call :END_MEASURE
goto PAUSE_RETURN

:WINDOWS_UPDATE
cls
call :HEADER
call :SECTION_TITLE "WINDOWS UPDATE CLEANUP"
echo   Clears downloaded update packages only. Installed updates stay installed.
echo   Existing Windows Update and BITS service state is restored in a finally block.
echo.
set "CYPRA_TASK=WINDOWS UPDATE CLEANUP"
call :BEGIN_MEASURE
call :CORE_WINDOWS_UPDATE
call :END_MEASURE
goto PAUSE_RETURN

:WINDOWS_OLD
cls
call :HEADER
call :SECTION_TITLE "PREVIOUS WINDOWS / WINDOWS.OLD"
set "CYPRA_OLD=%SystemDrive%\Windows.old"
if not exist "%CYPRA_OLD%" (
  call :RESULT SKIP "WINDOWS.OLD" "no previous Windows installation found"
  goto PAUSE_RETURN
)
echo.
powershell -NoProfile -Command "Write-Host '  [WARN] This permanently removes the previous Windows installation.' -ForegroundColor Yellow; Write-Host '         You will lose the built-in rollback path to that previous version.' -ForegroundColor Yellow; Write-Host '         Your current Windows installation is not targeted.' -ForegroundColor Green"
echo.
set "CYPRA_CONFIRM="
set /p "CYPRA_CONFIRM=  Type DELETE to continue: "
if /i not "%CYPRA_CONFIRM%"=="DELETE" (
  call :RESULT SKIP "WINDOWS.OLD" "cancelled by user"
  goto PAUSE_RETURN
)
set "CYPRA_TASK=WINDOWS.OLD"
call :BEGIN_MEASURE
powershell -NoProfile -Command "Write-Host '  [ADMIN] Removing Windows rollback data...' -ForegroundColor Cyan"
Dism.exe /Online /Remove-OSUninstall >nul 2>&1
if exist "%CYPRA_OLD%" (
  takeown /F "%CYPRA_OLD%" /A /R /D Y >nul 2>&1
  icacls "%CYPRA_OLD%" /grant *S-1-5-32-544:F /T /C /Q >nul 2>&1
  rmdir /S /Q "%CYPRA_OLD%" >nul 2>&1
)
call :END_MEASURE
if exist "%CYPRA_OLD%" (
  call :RESULT FAIL "WINDOWS.OLD" "some files remain locked; restart Windows and retry"
) else (
  call :RESULT PASS "WINDOWS.OLD" "previous Windows rollback files removed"
)
goto PAUSE_RETURN

:COMPONENT_STORE
cls
call :HEADER
call :SECTION_TITLE "WINDOWS COMPONENT STORE"
echo   Removes superseded component versions using supported DISM servicing.
echo.
set "CYPRA_TASK=COMPONENT STORE"
call :BEGIN_MEASURE
call :CORE_COMPONENT_STORE
call :END_MEASURE
goto PAUSE_RETURN

:TEMP_FILES
cls
call :HEADER
call :SECTION_TITLE "TEMPORARY FILES"
echo   Removes known temporary, crash-report, and shader-cache content.
echo.
set "CYPRA_TASK=TEMPORARY FILES"
call :BEGIN_MEASURE
call :CORE_TEMP
call :END_MEASURE
goto PAUSE_RETURN

:DELIVERY_OPT
cls
call :HEADER
call :SECTION_TITLE "DELIVERY OPTIMIZATION CACHE"
echo   Removes Windows Delivery Optimization cache where supported.
echo.
set "CYPRA_TASK=DELIVERY OPTIMIZATION"
call :BEGIN_MEASURE
call :CORE_DELIVERY
call :END_MEASURE
goto PAUSE_RETURN

:RECYCLE_BIN
cls
call :HEADER
call :SECTION_TITLE "RECYCLE BIN"
echo   This permanently empties Recycle Bins on fixed local drives.
echo   Cleanup is verified after the Windows command finishes.
echo.
choice /C YN /N /M "  Empty Recycle Bins now? [Y/N]: "
if errorlevel 2 (
  call :RESULT SKIP "RECYCLE BIN" "cancelled by user"
  goto PAUSE_RETURN
)
echo.
set "CYPRA_TASK=RECYCLE BIN"
call :BEGIN_MEASURE
call :CORE_RECYCLE_BIN
call :END_MEASURE
goto PAUSE_RETURN

:BROWSER_CACHE
cls
call :HEADER
call :SECTION_TITLE "BROWSER CACHES"
echo   Edge, Chrome, Firefox, Brave, Opera, and Opera GX.
echo   Running browsers are skipped. Cookies, passwords, history, bookmarks,
echo   profiles, and sessions are untouched.
echo.
set "CYPRA_TASK=BROWSER CACHES"
call :BEGIN_MEASURE
call :CORE_BROWSER_CACHE
call :END_MEASURE
goto PAUSE_RETURN

:RECOMMENDED
cls
call :HEADER
call :SECTION_TITLE "RECOMMENDED CLEANUP"
echo   Runs temp cleanup, Delivery Optimization, update-download cleanup,
echo   and supported component cleanup.
echo.
echo   Previous Windows files, Recycle Bin, and browser caches are NOT included.
echo.
set "CYPRA_CONFIRM="
set /p "CYPRA_CONFIRM=  Run recommended cleanup? [Y/N]: "
if /i not "%CYPRA_CONFIRM%"=="Y" (
  call :RESULT SKIP "RECOMMENDED CLEANUP" "cancelled by user"
  goto PAUSE_RETURN
)
set "CYPRA_TASK=RECOMMENDED CLEANUP"
call :BEGIN_MEASURE
call :CORE_TEMP
call :CORE_DELIVERY
call :CORE_WINDOWS_UPDATE
call :CORE_COMPONENT_STORE
call :END_MEASURE
goto PAUSE_RETURN

:RESTORE_POINT
cls
call :HEADER
call :SECTION_TITLE "CREATE RESTORE POINT"
echo   Windows System Protection must already be enabled for the system drive.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try{Checkpoint-Computer -Description 'CYPRA CLEAN Pre-Cleanup' -RestorePointType 'MODIFY_SETTINGS' -ErrorAction Stop;exit 0}catch{exit 20}"
if errorlevel 1 (
  call :RESULT FAIL "RESTORE POINT" "Windows did not create the restore point"
) else (
  call :RESULT PASS "RESTORE POINT" "CYPRA CLEAN Pre-Cleanup created"
)
goto PAUSE_RETURN

:ANALYZER
cls
call :HEADER
call :SECTION_TITLE "FULL SPACE ANALYZER"
echo   Read-only scan of known disposable locations. Large folders can take a moment.
echo   Sizes are approximate when Windows has locked files.
echo.
call :FULL_SCAN
echo.
powershell -NoProfile -Command "Write-Host '  [ADMIN] Checking Windows component-store reclaimability...' -ForegroundColor Cyan; Write-Host '          This DISM analysis is read-only.' -ForegroundColor DarkGray"
echo.
Dism.exe /Online /Cleanup-Image /AnalyzeComponentStore
echo.
call :SHOW_DRIVE
call :SHOW_LOG_PATH
goto PAUSE_RETURN

:PAUSE_RETURN
set "CYPRA_SHOW_SNAPSHOT=1"
echo.
call :SHOW_LOG_PATH
echo.
echo   Press any key to return to the menu...
pause >nul
goto MENU

:EXIT
cls
call :HEADER
echo.
call :SHOW_DRIVE
call :LOG "SESSION END // normal exit"
call :SHOW_LOG_PATH
echo.
powershell -NoProfile -Command "Write-Host '  Returning control to MatrixStudio.' -ForegroundColor Gray"
echo.
if exist "%CYPRA_SCAN_CACHE%" del /q "%CYPRA_SCAN_CACHE%" >nul 2>&1
endlocal
exit /b 0
