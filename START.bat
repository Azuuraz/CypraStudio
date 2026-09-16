@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0START.ps1"
set "MS2_EXIT=%errorlevel%"
if not "%MS2_EXIT%"=="0" (
  echo.
  echo MatrixStudio2.0 launch failed. Press any key to close this window.
  pause >nul
)
exit %MS2_EXIT%
