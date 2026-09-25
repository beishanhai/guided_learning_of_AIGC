@echo off
rem ChaiJingXue one-click start (double-click friendly)
setlocal
cd /d "%~dp0"

set "PWSH=pwsh"
where pwsh >nul 2>nul || set "PWSH=powershell"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" echo Startup failed, exit code %CODE%
pause
endlocal
