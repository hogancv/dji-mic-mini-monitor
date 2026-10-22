# Build the standalone exe and the release zip.
#
# Prereq: .venv created by scripts\setup.ps1 (tkinter + pystray + Pillow).
# PyInstaller is installed here on demand if missing.
#
# Output:
#   release\bin\DJIMicMiniTray.exe                      onefile, no console
#   release\DJIMicMiniTray-v<Version>-win64\            exe + driver + readme
#   release\DJIMicMiniTray-v<Version>-win64.zip         what gets attached to a GitHub release
#
# Note: the text readme is copied from packaging\*.txt verbatim, so this script
# stays pure ASCII and cannot be mangled by code-page issues.

param([string]$Version = '1.0.0')

$ErrorActionPreference = 'Stop'
$proj = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $proj '.venv'
$vpy  = Join-Path $venv 'Scripts\python.exe'

function Say($m) { Write-Host $m }

Say "============================================================"
Say " DJI Mic Mini Monitor - build standalone exe  (v$Version)"
Say "============================================================"
Say ""

if (-not (Test-Path $vpy)) {
    Say "[ERROR] .venv not found. Run scripts\setup.ps1 first."
    exit 1
}

# ---------- 1. pyinstaller ----------
Say "[1/4] Checking PyInstaller ..."
# A failing `import` writes to stderr, and with $ErrorActionPreference='Stop'
# PowerShell 5.1 turns native stderr into a terminating error -- so relax it
# for the probe only.
$ErrorActionPreference = 'Continue'
& $vpy -c "import PyInstaller" 2>$null
$hasPI = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = 'Stop'
if (-not $hasPI) {
    Say "      installing ..."
    $ErrorActionPreference = 'Continue'
    & $vpy -m pip install --quiet -i https://mirrors.aliyun.com/pypi/simple pyinstaller
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { Say "[ERROR] pip install pyinstaller failed."; exit 1 }
}
& $vpy -c "import PyInstaller; print('      PyInstaller', PyInstaller.__version__)"
Say ""

# ---------- 2. icon + version resource ----------
Say "[2/4] Generating icon and version resource ..."
& $vpy (Join-Path $PSScriptRoot 'make_icon.py') (Join-Path $proj 'build\icon.ico')

# PyInstaller's version resource is a Python literal. Kept ASCII-only on purpose
# so this script never depends on the console code page.
$parts = ($Version -split '\.') + @('0', '0', '0', '0')
$v4 = ($parts[0..3] -join ', ')
$verFile = Join-Path $proj 'build\version_info.txt'
$verBody = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($v4),
    prodvers=($v4),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'DJI Mic Mini Monitor'),
        StringStruct('FileDescription', 'DJI Mic Mini Monitor - tray widget'),
        StringStruct('FileVersion', '$Version'),
        StringStruct('InternalName', 'DJIMicMiniTray'),
        StringStruct('LegalCopyright', 'MIT License'),
        StringStruct('OriginalFilename', 'DJIMicMiniTray.exe'),
        StringStruct('ProductName', 'DJI Mic Mini Monitor'),
        StringStruct('ProductVersion', '$Version'),
        StringStruct('Comments', 'Unofficial. Reads battery/status over USB via WinUSB.')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
Set-Content -LiteralPath $verFile -Value $verBody -Encoding ASCII
Say "      $verFile"
Say ""

# ---------- 3. build ----------
Say "[3/4] Running PyInstaller ..."
$dist = Join-Path $proj 'release\bin'
$work = Join-Path $proj 'build\pyinstaller'
if (Test-Path $dist) { Remove-Item -LiteralPath $dist -Recurse -Force }
if (Test-Path $work) { Remove-Item -LiteralPath $work -Recurse -Force }
# PyInstaller logs to stderr, which PS 5.1 escalates to a terminating error
# while $ErrorActionPreference is 'Stop'. Relax it and check the exit code instead.
$ErrorActionPreference = 'Continue'
& $vpy -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name DJIMicMiniTray `
    --icon (Join-Path $proj 'build\icon.ico') `
    --version-file $verFile `
    --paths (Join-Path $proj 'src') `
    --distpath $dist --workpath $work --specpath (Join-Path $proj 'build') `
    (Join-Path $proj 'src\mic_tray.pyw') | Select-Object -Last 3
$piExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($piExit -ne 0) { Say "[ERROR] PyInstaller failed (exit $piExit)."; exit 1 }
$exe = Join-Path $dist 'DJIMicMiniTray.exe'
if (-not (Test-Path $exe)) { Say "[ERROR] build produced no exe."; exit 1 }
Say "      $exe  ($([math]::Round((Get-Item $exe).Length / 1MB, 1)) MB)"
Say ""

# ---------- 4. package ----------
Say "[4/4] Assembling release package ..."
$pkg = Join-Path $proj "release\DJIMicMiniTray-v$Version-win64"
if (Test-Path $pkg) { Remove-Item -LiteralPath $pkg -Recurse -Force }
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
Copy-Item -LiteralPath $exe -Destination $pkg

# driver files (flat copies of driver\, so the .bat keeps working from the package)
$drv = Join-Path $pkg 'driver'
New-Item -ItemType Directory -Path $drv -Force | Out-Null
Copy-Item -Path (Join-Path $proj 'driver\*') -Destination $drv -Force

# readme: copied verbatim from packaging\ (first .txt found), no encoding rewriting
$txt = Get-ChildItem (Join-Path $proj 'packaging') -Filter '*.txt' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($txt) { Copy-Item -LiteralPath $txt.FullName -Destination $pkg -Force }

$zip = Join-Path $proj "release\DJIMicMiniTray-v$Version-win64.zip"
if (Test-Path $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path (Join-Path $pkg '*') -DestinationPath $zip -CompressionLevel Optimal
Say "      $zip  ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"
Say ""
Say "Contents:"
Get-ChildItem $pkg -Recurse -File | ForEach-Object {
    "  " + $_.FullName.Substring($pkg.Length + 1)
}
Say ""
Say "Done."
