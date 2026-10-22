"""Per-second battery + charging monitor for DJI Mic Mini transmitter.

Purpose: swap charging cables / ports on the dock and see immediately whether
the TX reports "charging", plus whether the 7-step gauge actually climbs.

    python charge_monitor.py                 # run until Ctrl+C
    python charge_monitor.py 120             # run 120 seconds
    python charge_monitor.py 120 --csv a.csv # explicit log path
    python charge_monitor.py --label 键盘原装线
    python charge_monitor.py --raw            # also dump the TX status bytes

Every second it prints one row. Any change of the charging bit or the gauge is
flagged inline. All rows are also appended to a CSV so several cables can be
compared afterwards.

Requires micbattery.py next to this file and the receiver's MI_06 bound to
WinUSB (install_winusb.bat).
"""
import sys, os, time, csv
import micbattery as mb

GAUGE_TXT = {1: '满', 2: '较满', 3: '良好', 4: '中等', 5: '偏低', 6: '低', 7: '即将关机'}
BAR_W = 7


def bar(gauge):
    if not gauge:
        return '?' * BAR_W
    filled = max(0, min(BAR_W, 8 - gauge))
    return '#' * filled + '.' * (BAR_W - filled)


def parse_args():
    dur = 0.0
    csv_path = None
    label = ''
    raw_mode = False
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == '--csv' and i + 1 < len(sys.argv):
            csv_path = sys.argv[i + 1]; i += 2
        elif a == '--label' and i + 1 < len(sys.argv):
            label = sys.argv[i + 1]; i += 2
        elif a == '--raw':
            raw_mode = True; i += 1
        elif a in ('-h', '--help'):
            print(__doc__); sys.exit(0)
        else:
            try:
                dur = float(a)
            except ValueError:
                print(f'无法识别的参数: {a}'); sys.exit(2)
            i += 1
    if csv_path is None:
        csv_path = 'charge_log_%s.csv' % time.strftime('%m%d_%H%M%S')
    return dur, csv_path, label, raw_mode


def main():
    dur, csv_path, label, raw_mode = parse_args()
    h, iface = mb.open_device()

    f = open(csv_path, 'w', newline='', encoding='utf-8-sig')
    w = csv.writer(f)
    w.writerow(['elapsed_s', 'clock', 'gauge', 'percent', 'charging',
                'raw_plus7', 'frames_in_sec', 'note'])

    print('=' * 74)
    print('DJI Mic Mini 发射器  电量 / 充电状态  1 秒采样' +
          (f'   标签: {label}' if label else ''))
    print('=' * 74)
    print('说明: 「充电」由发射器自己上报（底座触点有电流才会变是）')
    print('      「帧」= 这一秒收到的状态帧数，正常约 1/秒；持续 0 表示掉线')
    print('      档位 1 满 → 7 空，每档约 14%，短时间内只会缓慢爬升')
    print('-' * 74)
    print(' 时间     档位       电量   充电  帧   变化')
    print('-' * 74)

    t0 = time.time()
    buf = bytearray()
    last_gauge = None
    last_charging = None
    prev_gauge = None
    rows = 0
    charge_sec = 0
    online_sec = 0
    first_gauge = None
    total_frames = 0
    lost_sec = 0
    miss_streak = 0
    k = 0

    try:
        while True:
            now = time.time()
            elapsed = now - t0
            if dur and elapsed >= dur:
                break

            # --- collect frames for this 1-second window ---
            # anchored to a fixed schedule so CSV writing never accumulates drift
            k += 1
            win_end = t0 + k
            frames = 0
            latest = None
            while True:
                remain = win_end - time.time()
                if remain <= 0:
                    break
                # never block past the end of the window
                tmo = max(20, min(200, int(remain * 1000)))
                chunk = mb.read_chunk(iface, timeout_ms=tmo, h=h)
                if chunk is None:
                    raise RuntimeError(f'读取错误 {mb.ctypes.get_last_error()}')
                if not chunk:          # timeout, nothing arrived yet
                    continue
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
                    frames += 1
                    s = fr[52:84]
                    code = (s[7] >> 2) & 0x07
                    latest = (code, bool(s[7] & 0x02), s[7], bytes(s))

            elapsed = time.time() - t0
            clock = time.strftime('%H:%M:%S')
            total_frames += frames

            if latest is None:
                # The TX status push runs at ~1 Hz, so a single silent second is
                # normal jitter. Only after 3 in a row do we call it offline.
                miss_streak += 1
                lost_sec += 1
                if last_charging is not None and miss_streak < 3:
                    hp = mb.GAUGE_PCT.get(last_gauge)
                    w.writerow([f'{elapsed:.2f}', clock, last_gauge,
                                '' if hp is None else hp,
                                'yes' if last_charging else 'no', '', 0,
                                '本秒无帧(沿用上值)'])
                    print(f'{elapsed:7.1f}s  {bar(last_gauge)}    {last_gauge}/7  '
                          f'~{hp}%  {"是" if last_charging else "否"}   0     (本秒无帧)')
                else:
                    note = '掉线' if last_charging is not None else '等待数据'
                    w.writerow([f'{elapsed:.2f}', clock, '', '', '', '', 0, note])
                    print(f'{elapsed:7.1f}s  {"-" * BAR_W}   --      ?     '
                          f'0     {note}  连续 {miss_streak} 秒')
                f.flush()
                continue

            miss_streak = 0

            gauge, charging, raw7, slot = latest
            online_sec += 1
            if charging:
                charge_sec += 1
            rows += 1
            if first_gauge is None:
                first_gauge = gauge

            notes = []
            if last_charging is not None and charging != last_charging:
                notes.append('开始充电 ←' if charging else '停止充电 ←')
            if last_gauge is not None and gauge != last_gauge:
                d = last_gauge - gauge          # positive = gaining charge
                notes.append(('电量上升 %+d 档' % d) if d > 0 else ('电量下降 %+d 档' % d))
            if last_charging is None:
                notes.append('首帧')
            if frames == 0:
                notes.append('本秒无帧')

            pct = mb.GAUGE_PCT.get(gauge)
            w.writerow([f'{elapsed:.2f}', clock, gauge,
                        '' if pct is None else pct,
                        'yes' if charging else 'no',
                        f'0x{raw7:02X}', frames, ';'.join(notes)])
            f.flush()

            mark = ''
            if any(n.startswith(('开始充电', '停止充电')) for n in notes):
                mark = '  <<< ' + ' / '.join(notes)
            elif notes:
                mark = '  (' + ' / '.join(notes) + ')'

            pct_s = f'~{pct}%' if pct is not None else '  ?  '
            print(f'{elapsed:7.1f}s  {bar(gauge)}    {gauge}/7  '
                  f'{pct_s:>5}  {"是" if charging else "否"}   {frames:<4}{mark}')
            if raw_mode:
                print('          raw ' + ' '.join('%02X' % b for b in slot[:12]))

            last_gauge = gauge
            last_charging = charging

    except KeyboardInterrupt:
        print('\n已手动停止。')
    except Exception as e:
        print(f'\n中断: {e}')
    finally:
        f.close()
        mb.winusb.WinUsb_Free(iface)
        mb.k32.CloseHandle(h)

    # ---------------- summary ----------------
    span = time.time() - t0
    print('-' * 74)
    print(f'时长 {span:.1f}s   有效秒数 {online_sec}   丢失 {lost_sec}   收到状态帧 {total_frames}')
    if rows:
        print(f'充电占比 {charge_sec / online_sec * 100:.0f}%  ({charge_sec}/{online_sec} 秒)')
        tail = f'  末档位 {last_gauge}/7'
        if first_gauge is not None and last_gauge is not None:
            gained = first_gauge - last_gauge
            if gained > 0:
                tail += f'   (首 {first_gauge} → 末 {last_gauge}，共升 {gained} 档)'
            elif gained == 0:
                tail += f'   (首 {first_gauge} → 末 {last_gauge}，档位未变)'
            else:
                tail += f'   (首 {first_gauge} → 末 {last_gauge}，下降 {-gained} 档)'
        print(tail)
        if charge_sec == 0:
            print('判定: 全程未检测到充电 —— 这根线 / 这个口没有给底座供电。')
        elif last_gauge is not None and first_gauge is not None and last_gauge >= first_gauge:
            print('判定: 有充电标志但档位没上升，若时长超过 5 分钟需怀疑底座或电池。')
        else:
            print('判定: 充电正常，档位在上升。')
    else:
        print('没有拿到任何状态帧，检查接收器是否插好、发射器是否开机。')
    print(f'日志: {os.path.abspath(csv_path)}')
    print('-' * 74)
    print('对比线材时: 换线后重新运行本脚本，比较「充电占比」和「首末档位」。')


if __name__ == '__main__':
    main()
