# Bind WinUSB to the DJI Mic Mini receiver's vendor interface (MI_06).
#
# Why this is needed: the receiver exposes a vendor interface (interface 6) that
# carries the status/control stream on Bulk OUT 0x06 / Bulk IN 0x86. Windows has
# no inbox driver for it, so it shows up as "Problem 28" (drivers not installed)
# and user-mode code cannot open it. winusb.sys is the standard way to expose it.
#
# What this script does, in order:
#   1. reuses or creates a local self-signed code-signing certificate
#   2. trusts it in LocalMachine\Root + LocalMachine\TrustedPublisher
#   3. builds a driver package from djimic_winusb.inf and signs its catalog
#   4. installs it with pnputil
#   5. verifies the device state and, if possible, reads the battery
#
# The package contains no binary of its own -- it only redirects to Microsoft's
# own winusb.sys -- which is why a locally signed catalog is enough and no
# test-signing mode or reboot is required.
#
# Run elevated. To undo everything, use uninstall_winusb.ps1.

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }
$proj = Split-Path -Parent $root

function Say($msg) { Write-Host $msg }

# ---------- 0. admin check ----------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Say "[ERROR] Must run as Administrator."
    exit 1
}

Say "============================================================"
Say " DJI Mic Mini WinUSB binder  (interface MI_06)"
Say " HWID: USB\VID_2CA3&PID_4011&MI_06"
Say "============================================================"
Say ""

# ---------- 1. local code-signing certificate ----------
Say "[1/5] Preparing local code-signing certificate..."
$subject = 'CN=DJI Mic Mini WinUSB Local Signing'
$cert = Get-ChildItem Cert:\LocalMachine\My |
        Where-Object { $_.Subject -eq $subject -and $_.HasPrivateKey } |
        Sort-Object NotAfter -Descending | Select-Object -First 1

if (-not $cert) {
    $cert = New-SelfSignedCertificate -Type Custom -Subject $subject `
        -KeyUsage DigitalSignature -KeyAlgorithm RSA -KeyLength 2048 `
        -CertStoreLocation 'Cert:\LocalMachine\My' `
        -NotAfter (Get-Date).AddYears(5) `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')
    Say "      created new cert: $($cert.Thumbprint)"
} else {
    Say "      reusing cert: $($cert.Thumbprint)"
}

$cerPath = Join-Path $env:TEMP 'djimic_local_signing.cer'
Export-Certificate -Cert $cert -FilePath $cerPath -Type CERT | Out-Null
foreach ($store in @('Cert:\LocalMachine\Root', 'Cert:\LocalMachine\TrustedPublisher')) {
    try {
        Import-Certificate -FilePath $cerPath -CertStoreLocation $store | Out-Null
        Say "      trusted in $store"
    } catch {
        Say "      already trusted in $store"
    }
}
Say ""

# ---------- 2. build package folder ----------
Say "[2/5] Building driver package..."
# Inside the repo, keep the build next to the sources; when this script runs from
# an extracted release package (no src\micbattery.py), use TEMP so nothing is
# written into the package folder.
if (Test-Path (Join-Path $proj 'src\micbattery.py')) {
    $pkg = Join-Path $proj 'build\driver_pkg'
} else {
    $pkg = Join-Path $env:TEMP 'djimic_winusb_pkg'
}
if (Test-Path $pkg) { Remove-Item -LiteralPath $pkg -Recurse -Force }
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'djimic_winusb.inf') -Destination $pkg -Force
Say "      $pkg"
Say ""

# ---------- 3. catalog + signature ----------
Say "[3/5] Generating and signing catalog..."
$catTmp = Join-Path $env:TEMP 'djimic_winusb.cat'
if (Test-Path $catTmp) { Remove-Item -LiteralPath $catTmp -Force }
New-FileCatalog -Path $pkg -CatalogFilePath $catTmp -CatalogVersion 2.0 | Out-Null
$sig = Set-AuthenticodeSignature -FilePath $catTmp -Certificate $cert -HashAlgorithm SHA256
Say "      signature status: $($sig.Status)"
if ($sig.Status -ne 'Valid') {
    Say "      [WARN] $($sig.StatusMessage)"
}
Copy-Item -LiteralPath $catTmp -Destination (Join-Path $pkg 'djimic_winusb.cat') -Force
Say ""

# ---------- 4. install ----------
Say "[4/5] Installing driver package..."
& pnputil.exe /add-driver "$pkg\djimic_winusb.inf" /install
Say "      pnputil exit code: $LASTEXITCODE"
& pnputil.exe /scan-devices | Out-Null
Say ""

# ---------- 5. verify ----------
Say "[5/5] Device state after install:"
Start-Sleep -Seconds 2
$dev = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like '*VID_2CA3&PID_4011&MI_06*' }
if ($dev) {
    $dev | Select-Object Status, Class, FriendlyName, Problem |
        Format-List | Out-String | Write-Host
} else {
    Say "      MI_06 not found (is the receiver still plugged in?)"
}
Say ""

# ---------- bonus: read the battery right away ----------
$py = Join-Path $proj '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { $py = $c.Source }
}
$script = Join-Path $proj 'src\micbattery.py'
if ($dev -and $dev.Status -eq 'OK' -and (Test-Path $py) -and (Test-Path $script)) {
    Say "------------------------------------------------------------"
    Say " Reading battery from the receiver via WinUSB..."
    Say "------------------------------------------------------------"
    Push-Location $proj
    try { & $py $script } catch { Say "micbattery.py failed: $_" }
    Pop-Location
} else {
    Say "Skipped the battery read (device not OK yet, or Python/script missing)."
}
Say ""
Say "Finished."
