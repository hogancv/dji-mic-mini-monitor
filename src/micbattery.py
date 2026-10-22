"""DJI Mic Mini receiver — read transmitter battery over USB (Windows, WinUSB).

Usage:
    python micbattery.py            # one snapshot
    python micbattery.py --watch    # keep refreshing every 2s
    python micbattery.py --json     # machine readable

Requires the receiver's vendor interface (MI_06, VID_2CA3 PID_4011) to be bound
to WinUSB -- see install_winusb.bat.
"""
import ctypes, ctypes.wintypes as w, json, sys, time

setupapi = ctypes.WinDLL('setupapi', use_last_error=True)
winusb = ctypes.WinDLL('winusb', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)


class GUID(ctypes.Structure):
    _fields_ = [('Data1', w.DWORD), ('Data2', w.WORD), ('Data3', w.WORD),
                ('Data4', ctypes.c_ubyte * 8)]


class SP_DID(ctypes.Structure):
    _fields_ = [('cbSize', w.DWORD), ('InterfaceClassGuid', GUID),
                ('Flags', w.DWORD), ('Reserved', ctypes.c_void_p)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [('Internal', ctypes.c_void_p), ('InternalHigh', ctypes.c_void_p),
                ('Offset', w.DWORD), ('OffsetHigh', w.DWORD), ('hEvent', ctypes.c_void_p)]


setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), w.LPCWSTR, w.HWND, w.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = w.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                 ctypes.POINTER(GUID), w.DWORD,
                                                 ctypes.POINTER(SP_DID)]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = w.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DID),
                                                      ctypes.c_void_p, w.DWORD,
                                                      ctypes.POINTER(w.DWORD), ctypes.c_void_p]

k32.CreateFileW.restype = ctypes.c_void_p
k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p]
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.CreateEventW.restype = ctypes.c_void_p
k32.CreateEventW.argtypes = [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]
k32.WaitForSingleObject.restype = w.DWORD
k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, w.DWORD]
k32.CancelIoEx.restype = w.BOOL
k32.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.POINTER(OVERLAPPED)]

winusb.WinUsb_Initialize.restype = w.BOOL
winusb.WinUsb_Initialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
winusb.WinUsb_Free.restype = w.BOOL
winusb.WinUsb_Free.argtypes = [ctypes.c_void_p]
winusb.WinUsb_SetPipePolicy.restype = w.BOOL
winusb.WinUsb_SetPipePolicy.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, w.ULONG,
                                        w.ULONG, ctypes.c_void_p]
winusb.WinUsb_ReadPipe.restype = w.BOOL
winusb.WinUsb_ReadPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p,
                                   w.ULONG, ctypes.POINTER(w.ULONG), ctypes.POINTER(OVERLAPPED)]
winusb.WinUsb_GetOverlappedResult.restype = w.BOOL
winusb.WinUsb_GetOverlappedResult.argtypes = [ctypes.c_void_p, ctypes.POINTER(OVERLAPPED),
                                              ctypes.POINTER(w.ULONG), w.BOOL]

GUID_USBDEV = GUID(0xA5DCBF10, 0x6530, 0x11D2,
                   (ctypes.c_ubyte * 8)(0x90, 0x1F, 0x00, 0xC0, 0x4F, 0xB9, 0x51, 0xED))
ERROR_IO_PENDING = 997
PIPE_TRANSFER_TIMEOUT = 0x03
BULK_IN = 0x86
FILE_FLAG_OVERLAPPED = 0x40000000

# 3-bit gauge: 1 = full, 7 = about to shut off. Percent is an estimate only.
GAUGE_PCT = {0: None, 1: 100, 2: 85, 3: 70, 4: 55, 5: 40, 6: 20, 7: 5}


def enum_paths():
    out = []
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(GUID_USBDEV), None, None, 0x02 | 0x10)
    if not hdev:
        return out
    i = 0
    while True:
        did = SP_DID(); did.cbSize = ctypes.sizeof(did)
        if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(GUID_USBDEV),
                                                    i, ctypes.byref(did)):
            break
        i += 1
        need = w.DWORD(0)
        setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(did), None, 0,
                                                  ctypes.byref(need), None)
        if not need.value:
            continue
        buf = ctypes.create_string_buffer(need.value)
        ctypes.cast(buf, ctypes.POINTER(w.DWORD))[0] = 8
        if setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(did), buf, need.value,
                                                     ctypes.byref(need), None):
            out.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    return out


def open_device():
    paths = [p for p in enum_paths() if '2ca3' in p.lower() and 'mi_06' in p.lower()]
    if not paths:
        raise RuntimeError('MI_06 not found - is the receiver plugged in and is WinUSB bound?')
    # FILE_FLAG_OVERLAPPED is mandatory: without it WinUsb_Initialize fails with err 6
    h = k32.CreateFileW(paths[0], 0xC0000000, 3, None, 3, FILE_FLAG_OVERLAPPED, None)
    if not h or h == ctypes.c_void_p(-1).value:
        raise RuntimeError(f'CreateFile failed, err={ctypes.get_last_error()}')
    iface = ctypes.c_void_p()
    if not winusb.WinUsb_Initialize(h, ctypes.byref(iface)):
        k32.CloseHandle(h)
        raise RuntimeError(f'WinUsb_Initialize failed, err={ctypes.get_last_error()}')
    tmo = w.ULONG(800)
    winusb.WinUsb_SetPipePolicy(iface, BULK_IN, PIPE_TRANSFER_TIMEOUT,
                                ctypes.sizeof(tmo), ctypes.byref(tmo))
    return h, iface


def read_chunk(iface, size=512, timeout_ms=800, h=None):
    """Read one bulk-IN chunk.

    Returns bytes on success, b'' on timeout, None on real error.

    On timeout the pending transfer MUST be cancelled before the OVERLAPPED,
    the event and the buffer go out of scope -- otherwise the kernel resumes
    the unfinished I/O into freed memory and the process segfaults. That is
    why `h` (the file handle) is required for timeouts to be safe.
    """
    ev = k32.CreateEventW(None, True, False, None)
    ov = OVERLAPPED(); ov.hEvent = ev
    buf = ctypes.create_string_buffer(size)
    got = w.ULONG(0)
    try:
        if winusb.WinUsb_ReadPipe(iface, BULK_IN, buf, size, ctypes.byref(got), ctypes.byref(ov)):
            return buf.raw[:got.value]
        if ctypes.get_last_error() != ERROR_IO_PENDING:
            return None
        if k32.WaitForSingleObject(ev, timeout_ms) != 0:
            if h:
                # cancel, then reap the cancelled transfer before freeing anything
                k32.CancelIoEx(h, ctypes.byref(ov))
                k32.WaitForSingleObject(ev, 1000)
                winusb.WinUsb_GetOverlappedResult(iface, ctypes.byref(ov),
                                                  ctypes.byref(got), False)
            return b''
        if not winusb.WinUsb_GetOverlappedResult(iface, ctypes.byref(ov), ctypes.byref(got), False):
            return None
        return buf.raw[:got.value]
    finally:
        k32.CloseHandle(ev)


def crc16(data, seed):
    c = seed
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c >> 1) ^ 0x8408) if c & 1 else (c >> 1)
    return c & 0xFFFF


def frame_length(buf):
    """Total frame length if a valid frame starts at 0, else None."""
    if len(buf) < 6 or buf[0] != 0x55:
        return None
    ln = buf[1]
    if ln < 8 or ln > 256 or len(buf) < ln:
        return None
    for seed, residue in ((0x3692, 0x0000), (0x0000, 0xBB01)):
        if crc16(buf[:ln], seed) == residue:
            return ln
    return None


def is_status_frame(fr):
    """v2 status push: 54 / 86 / 118 bytes = 54 + 32 per connected TX.
    Identity/level pushes also carry the 5b 03 03 marker, so length is the
    discriminator: only the status push has (len - 54) % 32 == 0."""
    return (len(fr) in (54, 86, 118)
            and fr[9] == 0x5B and fr[10] == 0x03 and fr[11] == 0x03)


def decode_status(fr):
    """Decode a v2 status push (len 54 / 86 / 118)."""
    state = {'version': 'v2', 'tx': [], 'rx_connected_mask': None,
             'gain_db': None, 'nc_enabled': None, 'auto_off': None, 'stereo': None}
    if len(fr) >= 49:
        state['rx_connected_mask'] = fr[44]
        state['nc_enabled'] = bool(fr[20] & 0x20)
        state['strong_nc'] = bool(fr[20] & 0x08)
        state['auto_off'] = bool(fr[21] & 0x01)
        state['stereo'] = bool(fr[21] & 0x04)
        g = fr[22]
        state['gain_db'] = g - 256 if g > 127 else g
    n = (len(fr) - 54) // 32 if len(fr) >= 86 else 0
    for k in range(n):
        s = fr[52 + k * 32: 52 + (k + 1) * 32]
        if len(s) < 10:
            break
        code = (s[7] >> 2) & 0x07
        state['tx'].append({
            'unit': s[1],                       # 1 = TX1, 2 = TX2 (physical unit)
            'gauge': code,                      # 1 full .. 7 empty
            'percent_estimate': GAUGE_PCT.get(code),
            'charging': bool(s[7] & 0x02),
            'nc_enabled': bool(s[7] & 0x01),
            'low_cut': bool(s[9] & 0x20),
            'auto_off': bool(s[6] & 0x10),
            'leds_off': bool(s[6] & 0x02),
        })
    return state


def snapshot(timeout=4.0):
    h, iface = open_device()
    buf = bytearray()
    deadline = time.time() + timeout
    best = None
    best_tx = -1
    seen_status = 0
    try:
        while time.time() < deadline:
            chunk = read_chunk(iface, h=h)
            if chunk is None:
                raise RuntimeError(f'read error {ctypes.get_last_error()}')
            buf += chunk
            while True:
                ln = frame_length(buf)
                if ln is None:
                    # resync on next 0x55
                    nxt = buf.find(b'\x55', 1)
                    if nxt > 0:
                        del buf[:nxt]
                    break
                fr = bytes(buf[:ln])
                del buf[:ln]
                if not is_status_frame(fr):
                    continue
                st = decode_status(fr)
                seen_status += 1
                n_tx = len(st['tx'])
                if n_tx >= best_tx:      # prefer the frame with the most TX data
                    best, best_tx = st, n_tx
                # enough evidence: two status frames that agree on TX count
                if seen_status >= 4 and best_tx > 0:
                    return best
    finally:
        winusb.WinUsb_Free(iface)
        k32.CloseHandle(h)
    if best:
        return best
    raise RuntimeError('no status frame received')


def bar(gauge, width=7):
    if not gauge:
        return '?' * width
    filled = max(0, min(width, 8 - gauge))
    return '#' * filled + '.' * (width - filled)


def render(st):
    lines = []
    if not st['tx']:
        lines.append('发射器未连接（或已关机）')
    for tx in st['tx']:
        pct = tx['percent_estimate']
        pct_s = f'{pct}%' if pct is not None else '?'
        flag = '  [充电中]' if tx['charging'] else ''
        lines.append(f"TX{tx['unit']}  电量 {bar(tx['gauge'])}  {tx['gauge']}/7  ~{pct_s}{flag}")
        lines.append(f"     降噪 {'开' if tx['nc_enabled'] else '关'}   "
                     f"低切 {'开' if tx['low_cut'] else '关'}   "
                     f"自动关机 {'开' if tx['auto_off'] else '关'}")
    lines.append(f"接收器增益 {st['gain_db']:+d} dB   "
                 f"降噪 {'开' if st['nc_enabled'] else '关'}   "
                 f"自动关机 {'开' if st['auto_off'] else '关'}")
    return '\n'.join(lines)


def main():
    watch = '--watch' in sys.argv
    as_json = '--json' in sys.argv
    try:
        while True:
            st = snapshot()
            if as_json:
                print(json.dumps(st, ensure_ascii=False))
            else:
                if watch:
                    sys.stdout.write('\x1b[2J\x1b[H')
                    print(time.strftime('%H:%M:%S'))
                print(render(st))
            if not watch:
                break
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'错误: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
