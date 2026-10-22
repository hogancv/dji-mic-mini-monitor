@echo off
rem Run the tray widget. Uses the project's .venv (created by scripts\setup.ps1).
setlocal
set "PROJ=%~dp0.."
set "PY=%PROJ%\.venv\Scripts\pythonw.exe"
if not exist "%PY%" (
  echo [ERROR] .venv not found.
  echo         Run this first:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  pause
  exit /b 1
)
cd /d "%PROJ%"
if /i "%~1"=="--hidden" (
  start "" "%PY%" "src\mic_tray.pyw" --hidden
) else (
  start "" "%PY%" "src\mic_tray.pyw"
)
exit /b 0
