@echo off
rem 1 Hz battery / charging monitor, for checking dock contacts or cables.
rem Exit the tray widget first: both read the same USB interface.
setlocal
set "PROJ=%~dp0.."
set "PY=%PROJ%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%PROJ%"
set "SECS=%~1"
if "%SECS%"=="" set /p SECS=Seconds to run (blank = until Ctrl+C): 
set "TAG=%~2"
if "%TAG%"=="" set /p TAG=Label for this run (optional): 
if "%SECS%"=="" set SECS=0
echo.
"%PY%" "src\charge_monitor.py" %SECS% --label "%TAG%"
echo.
pause
