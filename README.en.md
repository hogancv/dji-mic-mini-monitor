# DJI Mic Mini Monitor

[中文](README.md) · **English**

Read the live status of a **DJI Mic Mini** receiver over USB on Windows: transmitter battery, charging state, noise-cancel / low-cut / auto-off switches, and receiver gain. Ships with a tray widget that lives in the notification area and a 1 Hz battery/charging monitor.

> Unofficial. Not affiliated with DJI. The protocol is community reverse engineering and may break with a firmware update.

![Tray icon and panel](docs/images/screenshot.png)

Left, in the red box: the tray icon in the notification area, with the battery number drawn straight onto it (green while charging, red at ≤15%, amber at ≤35%, blue otherwise). Right: the panel, opened with a left click.

## Features

- **Battery**: transmitter gauge (7 steps), estimated percentage, charging flag, online state
- **Switches**: noise cancel, low cut, auto power-off, LEDs off; receiver gain, noise cancel, auto-off, stereo tracking
- **Tray widget**: borderless rounded card docked to the bottom-right of the work area, draggable, remembers its position, single instance
- **Contact-bounce detection**: if the charging bit flips ≥3 times in a minute the status line turns amber and says so — this project exists because of exactly that problem
- **1 Hz monitor**: `charge_monitor.py` samples once per second and writes a CSV, so two cables or two chargers can be compared directly
- **No third-party dependency** for the reader: standard library `ctypes` talking to `winusb.dll`

## Requirements

| Item | Requirement |
|---|---|
| OS | Windows 10 / 11 x64 |
| Device | DJI Mic Mini receiver (1TX+1RX or 2TX+1RX), connected over USB |
| Runtime | Python 3.9+ **with tkinter** (the python.org installer includes it) |
| DJI software | None. DJI Mimo is not needed |

Verified on Windows 10 22H2 with a 1TX+1RX kit and current receiver firmware.

## Download the exe (no Python needed)

If you just want the tool:

1. Download `DJIMicMiniTray-v1.0.0-win64.zip` (Releases page, or `release/` in the repo) and **extract it** somewhere — do not run it from inside the archive
2. Right click `driver\install_winusb.bat` → Run as administrator (once)
3. Double click `DJIMicMiniTray.exe`

Single file (~19 MB), no install, no Python, no dependencies. A few seconds of unpacking on first launch is normal; `使用说明.txt` inside the package has the full guide (Chinese).

> The exe is unsigned, so a few antivirus engines flag it — a well-known PyInstaller false positive, not malware. Use the source route below if that bothers you.

## Getting started (from source)

### 1. Bind WinUSB to the receiver's vendor interface (once, admin)

```bat
driver\install_winusb.bat        &rem right click -> Run as administrator
```

The script creates a local self-signed code-signing certificate, signs the catalog and installs the package. **No reboot, no test-signing mode.** The package contains no binary of its own — it only redirects to Microsoft's `winusb.sys`.

Only `MI_06` (the status channel) is touched. Audio (`MI_01`) and HID (`MI_00`) keep their inbox drivers.

To undo: `driver\uninstall_winusb.bat`.

### 2. Create the Python environment

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Creates `.venv` and installs `pystray` + `Pillow` (needed by the tray widget only).

### 3. Run

```bat
scripts\run-tray.bat
```

## Usage

### Tray widget

| Action | Result |
|---|---|
| Left click | Open / close the panel |
| Right click → Show panel | Same |
| Right click → Reset to bottom-right | Recover a panel dragged off-screen |
| Right click → Show battery digits on icon | Toggle between digits and a battery glyph |
| Right click → Run at startup | Writes `HKCU\...\Run`, toggleable |
| Right click → Quit | Exits (do this before running the CLI scripts) |
| Drag inside the panel / `Esc` | Move / hide |

### Command line

```bash
python src/micbattery.py           # one snapshot
python src/micbattery.py --watch   # refresh every 2 s
python src/micbattery.py --json    # machine readable
```

### Monitor (cable / dock diagnostics)

```bash
python src/charge_monitor.py 60 --label stock-cable
python src/charge_monitor.py --raw
python src/dock_check.py 25
```

One line per second, changes flagged inline, a summary at the end, and a `charge_log_MMDD_HHMMSS.csv` written automatically.

## What can and cannot be read

| Value | Status |
|---|---|
| Transmitter gauge (1 full → 7 empty) | Yes |
| Transmitter charging flag | Yes |
| Noise cancel / low cut / auto-off / LEDs | Yes |
| Receiver gain / noise cancel / auto-off / stereo | Yes |
| Exact battery percentage | No — only 3 bits / 7 steps in firmware; percentages are estimates |
| **Receiver's own battery** | No — that record only exists in the older v1 frame; current firmware sends v2 only |
| Real-time input level | Present in the 23-byte level frame, not parsed here |

## Building the exe

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1       &rem first time: create .venv
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1   &rem build
```

Output:

| Path | Contents |
|---|---|
| `release\bin\DJIMicMiniTray.exe` | onefile, windowed, icon and version resource embedded |
| `release\DJIMicMiniTray-v1.0.0-win64\` | exe + `driver\` + readme |
| `release\DJIMicMiniTray-v1.0.0-win64.zip` | the folder above, ready to attach to a GitHub release |

PyInstaller is installed automatically on the first build. Pass `-Version 1.1.0` to change the version. The icon is drawn by `scripts/make_icon.py` (4x supersampled, then downsampled); edit `GREEN` there to change the colour.

## How it works

The receiver is a composite USB device (`VID_2CA3 & PID_4011`). The status stream runs over interface `MI_06`, Bulk OUT `0x06` / Bulk IN `0x86`. The device pushes frames about once per second, CRC16 terminated. Battery lives in the transmitter slot at offset `+7`: bits 2–4 are the gauge, bit 1 is the charging flag.

The HID route does not work: the two vendor collections on `MI_00` open fine but yield no data and reject writes with error 87.

Frame layout, field offsets, CRC parameters and the three Windows-specific pitfalls are documented in **[docs/PROTOCOL.md](docs/PROTOCOL.md)** (Chinese).

## Troubleshooting

- **Still a yellow mark / Problem 28** — make sure the receiver is plugged in and not held by another process; check the `signature status` line printed by the installer.
- **`WinUsb_Initialize failed, err=6`** — not a handle problem. WinUSB requires the device handle to be opened with `FILE_FLAG_OVERLAPPED`.
- **Charging always shows "no"** — run `dock_check.py`, lift the transmitter off the dock and put it back. If it never flips, the dock is unpowered or the contacts are not seated. On the machine this project was built on it turned out to be **poor contact**, not a cable.
- **Monitor script fails to read** — the tray widget owns `MI_06`. Quit it first.

## Credits

Protocol knowledge comes from the following community work. **No code was copied** — `micbattery.py` is an independent `ctypes` implementation against WinUSB, with the frame layout taken from the public documentation below and verified byte by byte on real hardware (CRC residues, lengths and offsets all match).

| Project | Author | License | How it is used here |
|---|---|---|---|
| [ShadowBitBasher/DJI-Mic-Control](https://github.com/ShadowBitBasher/DJI-Mic-Control) | **ShadowBitBasher** | Unlicense (public domain) | **Primary source.** Its `PROTOCOL.md` documents the frame structure, command set and field layout; [docs/PROTOCOL.md](docs/PROTOCOL.md) reorganises it and adds measured findings |
| [caballeropedro/dji-mic](https://github.com/caballeropedro/dji-mic) | **caballeropedro** | No license declared (all rights reserved) | Cross-checked protocol understanding only |
| [usokawa/dji-mic-mo](https://github.com/usokawa/dji-mic-mo) | **usokawa** | BSD-2-Clause | Cross-checked protocol understanding only |
| [w1ne/stereo-bridge](https://github.com/w1ne/stereo-bridge) | **w1ne** | Apache-2.0 | Background: LC3 streams received directly on Android without a receiver. Not used |
| [WilliamPrime/DJI-mic-mini-dongle-replacement](https://github.com/WilliamPrime/DJI-mic-mini-dongle-replacement) | **WilliamPrime** | GPL-3.0 | Background: hardware replacement for the USB-C phone adapter. Not used |
| [flight-commander/dji_mic2_firmware](https://github.com/flight-commander/dji_mic2_firmware) | **flight-commander** | No license declared | Background: Mic 2 firmware archive. Not used |
| [pbatard/libwdi](https://github.com/pbatard/libwdi) (Zadig) | **Pete Batard** | GPL-3.0 | Not bundled. The general tool for binding WinUSB to such interfaces; this project uses a self-signed INF instead so nothing has to be downloaded |

Runtime dependencies, installed by `scripts/setup.ps1` and not vendored here:

| Dependency | Author / maintainer | License | Purpose |
|---|---|---|---|
| [pystray](https://github.com/moses-palmer/pystray) | **Moses Palmér** | LGPLv3 | Tray icon and menu |
| [Pillow](https://python-pillow.org/) | **Jeffrey A. Clark and the Pillow contributors** | MIT-CMU | Icon rendering |
| [CPython](https://www.python.org/) / `tkinter` | **Python Software Foundation** | PSF License | Panel UI |
| [PyInstaller](https://pyinstaller.org/) | **Hartmut Goebel, Giovanni Bajo, David Vierra, David Cortesi, Martin Zibricky and the PyInstaller Development Team** | GPL-2.0-or-later with the bootloader exception (which allows packaging code under any license) | Build time only: bundles the tray widget into a single exe |

If any attribution above is wrong, please open an issue and it will be corrected.

## Known limitations

- Windows only. macOS and Linux need no driver at all (the vendor interface is reachable from user space), but no port is included
- Read-only. Writing settings is not implemented
- Only a 1TX+1RX kit was tested. 2TX is handled by the slot loop and should work, but is untested
- The percentage is an estimate of a 7-step gauge, not a real percentage
- The receiver's own battery is not reported by current firmware

## License

[MIT](LICENSE). The protocol write-up in `docs/PROTOCOL.md` is derived from Unlicense community documentation, credited in that file.
