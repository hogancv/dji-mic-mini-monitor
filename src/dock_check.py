"""Watch the TX charging bit live to tell "dock not powered" from "bad contact".

Run it, then lift the transmitter off the dock at ~5s and put it back at ~15s.
Every change of the per-TX flag bytes is printed with a timestamp.

    python dock_check.py [seconds]
"""
import sys, time
import micbattery as mb

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0

h, iface = mb.open_device()
buf = bytearray()
t0 = time.time()
last_sig = None
samples = 0
tmo_note = False

print(f'监控 {DUR:.0f} 秒。请在约 5 秒时把发射器从底座上拿起（离开），15 秒时再放回。')
print('时间    +6    +7    +8    +9   档位  充电')
print('-' * 56)
try:
    while time.time() - t0 < DUR:
        chunk = mb.read_chunk(iface, h=h)
        if chunk is None:
            print('读取错误', mb.ctypes.get_last_error())
            break
        buf += chunk
        while True:
            ln = mb.frame_length(buf)
            if ln is None:
                nxt = buf.find(b'\x55', 1)
                if nxt > 0:
                    del buf[:nxt]
                break
            fr = bytes(buf[:ln])
            del buf[:ln]
            if not mb.is_status_frame(fr) or len(fr) < 86:
                continue
            s = fr[52:84]
            sig = (s[6], s[7], s[8], s[9])
            samples += 1
            if sig != last_sig:
                t = time.time() - t0
                print(f'{t:5.1f}s  0x{s[6]:02X}  0x{s[7]:02X}  0x{s[8]:02X}  0x{s[9]:02X}   '
                      f'{(s[7] >> 2) & 7}/7    {"是" if s[7] & 0x02 else "否"}'
                      + ('   <-- 状态变化' if last_sig else ''))
                last_sig = sig
finally:
    mb.winusb.WinUsb_Free(iface)
    mb.k32.CloseHandle(h)

print('-' * 56)
print(f'共解析 {samples} 帧状态帧')
if last_sig:
    print(f'最后: +7=0x{last_sig[1]:02X}  档位 {(last_sig[1] >> 2) & 7}/7  '
          f'充电 {"是" if last_sig[1] & 0x02 else "否"}')
