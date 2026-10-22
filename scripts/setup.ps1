# Create .venv for the tray widget and install its dependencies.
# The tray needs tkinter (part of the standard CPython installer) plus pystray + Pillow.
# Run from a normal prompt -- no administrator rights needed here.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Python "C:\Python312\python.exe"
#
# -Python is only needed when the interpreter with tkinter is not the one that
# `python` / `py -3` resolves to on PATH.

param([string]$Python = '')

$ErrorActionPreference = 'Stop'
$proj = Split-Path -Parent $PSScriptRoot

function Say($m) { Write-Host $m }

Say "============================================================"
Say " DJI Mic Mini Monitor - environment setup"
Say "============================================================"
Say ""

# ---------- 1. locate a Python that has tkinter ----------
Say "[1/4] Looking for Python with tkinter..."
$candidates = @()
if ($Python) { $candidates += $Python }
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd) { $candidates += $cmd.Source }
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    try {
        $p = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($p) { $candidates += $p.Trim() }
    } catch { }
}
$chosen = $null
foreach ($exe in $candidates | Select-Object -Unique) {
    try {
        $tk = & $exe -c "import tkinter; print(tkinter.TkVersion)" 2>$null
        if ($tk) {
            Say "      $exe  (tk $tk)"
            $chosen = $exe
            break
        }
    } catch { }
}
if (-not $chosen) {
    Say "[ERROR] No Python with tkinter found."
    Say "        Install CPython 3.9+ from python.org (the installer ships tkinter by default),"
    Say "        then run this script again."
    exit 1
}

# ---------- 2. create the venv ----------
Say ""
Say "[2/4] Creating .venv ..."
$venv = Join-Path $proj '.venv'
if (Test-Path $venv) {
    Say "      .venv already exists, reusing it"
} else {
    & $chosen -m venv $venv
    Say "      $venv"
}
$vpy = Join-Path $venv 'Scripts\python.exe'

# ---------- 3. install dependencies ----------
Say ""
Say "[3/4] Installing pystray + Pillow ..."
& $vpy -m pip install --quiet --upgrade pip 2>&1 | Out-Null
$indexes = @('', 'https://mirrors.aliyun.com/pypi/simple', 'https://pypi.tuna.tsinghua.edu.cn/simple')
$ok = $false
foreach ($idx in $indexes) {
    $pipArgs = @('-m', 'pip', 'install', '--quiet', 'pystray', 'Pillow')
    if ($idx) { $pipArgs += @('-i', $idx) }
    try {
        & $vpy @pipArgs 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Say "      installed via $(if ($idx) { $idx } else { 'default index' })"
            $ok = $true
            break
        }
    } catch { }
}
if (-not $ok) {
    Say "[ERROR] pip install failed on every index. Check your network / proxy, then retry."
    exit 1
}

# ---------- 4. verify ----------
Say ""
Say "[4/4] Verifying ..."
& $vpy -c "import tkinter, pystray, PIL; from importlib.metadata import version; print('      tk', tkinter.TkVersion, '| pystray', version('pystray'), '| Pillow', PIL.__version__)"
if ($LASTEXITCODE -ne 0) {
    Say "[ERROR] Verification failed."
    exit 1
}
Say ""
Say "Done. Next steps:"
Say "  1) driver\install_winusb.bat   (right click -> Run as administrator)"
Say "  2) scripts\run-tray.bat"
