@echo off
rem ChaiJingXue one-click stop (double-click friendly)
setlocal
cd /d "%~dp0"

set "PWSH=pwsh"
where pwsh >nul 2>nul || set "PWSH=powershell"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
echo.
pause
endlocal
