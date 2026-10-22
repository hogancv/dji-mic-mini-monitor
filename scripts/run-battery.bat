@echo off
rem One-shot battery snapshot from the DJI Mic Mini receiver.
rem Extra args are passed through:  --watch   --json
setlocal
set "PROJ=%~dp0.."
set "PY=%PROJ%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%PROJ%"
"%PY%" "src\micbattery.py" %*
echo.
pause
