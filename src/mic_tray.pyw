"""DJI Mic Mini tray widget (Windows).

Lives in the notification area and shows what the receiver actually reports:
TX battery gauge, charging state, and the transmitter / receiver settings.

    pythonw mic_tray.pyw          # normal start: tray icon + panel
    pythonw mic_tray.pyw --hidden # tray icon only, panel opens on click

Tray icon: left click = open/close panel, right click = menu.
Two icon styles, toggled from the menu: a coloured badge carrying the battery
percentage as digits (default), or a battery drawing with a proportional fill.
The panel can be dragged; its position and the icon style are remembered in
tray_state.json.

Needs micbattery.py in the same folder plus the receiver's MI_06 bound to
WinUSB (install_winusb.bat).
"""
import ctypes, ctypes.wintypes as w, json, os, sys, threading, time, winreg
import tkinter as tk
from PIL import Image, ImageDraw
import pystray

import micbattery as mb

APP = 'DJI Mic Mini'
if getattr(sys, 'frozen', False):
    # PyInstaller onefile: __file__ lives in a temp dir that is wiped on exit,
    # so anchor everything at the exe instead.
    HERE = os.path.dirname(os.path.abspath(sys.executable))
    SCRIPT = os.path.abspath(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    SCRIPT = os.path.abspath(__file__)
STATE_FILE = os.path.join(HERE, 'tray_state.json')
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'DJIMicMiniTray'

# ---------- palette (light card) ----------
TRANS = '#ff00ff'          # keyed out via -transparentcolor
CARD = '#ffffff'
BORDER = '#e3e6eb'
TEXT = '#111827'
SUB = '#374151'
MUTED = '#6b7280'
FAINT = '#9ca3af'
TRACK = '#eceff3'
BLUE = '#2563eb'
GREEN = '#16a34a'
AMBER = '#d97706'
RED = '#dc2626'

W, H = 296, 208
FONT = 'Microsoft YaHei UI'

user32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = [('left', w.LONG), ('top', w.LONG), ('right', w.LONG), ('bottom', w.LONG)]


def work_area():
    r = RECT()
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
        return r.left, r.top, r.right, r.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# ---------------- single instance ----------------
_mutex = None


def already_running():
    global _mutex
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    _mutex = k32.CreateMutexW(None, False, 'Local\\DjiMicMiniTrayWidget')
    return ctypes.get_last_error() == 183


# ---------------- autostart ----------------
def autostart_cmd():
    pyw = sys.executable
    if pyw.lower().endswith('python.exe'):
        pyw = pyw[:-len('python.exe')] + 'pythonw.exe'
    return f'"{pyw}" "{SCRIPT}"'


def is_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, RUN_NAME)
        return v.strip().lower() == autostart_cmd().strip().lower()
    except OSError:
        return False


def set_autostart(on):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_cmd())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# ---------------- persisted ui state ----------------
def load_state():
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(d):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------- device reader ----------------
class Reader(threading.Thread):
    """Keeps the vendor interface open and refreshes `self.state` from status frames."""

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.state = None          # latest decoded status dict
        self.ts = 0.0              # wall clock of last good status frame
        self.error = '正在连接…'
        self.stopped = False

    def snapshot(self):
        with self.lock:
            return self.state, self.ts, self.error

    def _put(self, st):
        with self.lock:
            self.state = st
            self.ts = time.time()
            self.error = None

    def _fail(self, msg):
        with self.lock:
            self.error = msg

    def run(self):
        while not self.stopped:
            try:
                h, iface = mb.open_device()
            except Exception as e:
                self._fail(str(e))
                time.sleep(2)
                continue
            self._fail('已连接，等待状态帧…')
            buf = bytearray()
            try:
                while not self.stopped:
                    chunk = mb.read_chunk(iface, timeout_ms=300, h=h)
                    if chunk is None:
                        raise RuntimeError('读取失败，正在重连…')
                    if not chunk:
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
                        if mb.is_status_frame(fr):
                            self._put(mb.decode_status(fr))
            except Exception as e:
                self._fail(str(e))
            finally:
                try:
                    mb.winusb.WinUsb_Free(iface)
                    mb.k32.CloseHandle(h)
                except Exception:
                    pass
            if not self.stopped:
                time.sleep(1.5)


# ---------------- tray icon art ----------------
def tray_image(gauge, charging, offline):
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body = [10, 18, 50, 46]
    cap = [51, 26, 58, 38]

    if offline:
        ring = '#d1d5db'
    elif charging:
        ring = GREEN
    elif gauge and gauge >= 6:
        ring = RED
    else:
        ring = '#e5e7eb'

    # dark halo under a light ring -> readable on both dark and light taskbars
    d.rounded_rectangle(body, radius=7, outline='#111827', width=8)
    d.rounded_rectangle(body, radius=7, outline=ring, width=4)
    d.rounded_rectangle(cap, radius=2, fill=ring)

    # fill proportional to the 7-step gauge (1 = full .. 7 = empty)
    if gauge and not offline:
        frac = max(0.0, min(1.0, (8 - gauge) / 7.0))
        inner_w = int((body[2] - body[0] - 12) * frac)
        if inner_w >= 2:
            col = GREEN if charging else (RED if gauge >= 6 else (AMBER if gauge == 5 else '#60a5fa'))
            d.rounded_rectangle([body[0] + 6, body[1] + 6,
                                 body[0] + 6 + inner_w, body[3] - 6],
                                radius=3, fill=col)
    if offline:
        d.line([42, 10, 22, 54], fill='#9ca3af', width=5)
    return img


# 3x5 pixel digits -- keep a percentage readable when the 64px art is
# downscaled to a 16px notification-area icon
_DIGITS = {
    '0': ('111', '101', '101', '101', '111'),
    '1': ('010', '110', '010', '010', '111'),
    '2': ('111', '001', '111', '100', '111'),
    '3': ('111', '001', '111', '001', '111'),
    '4': ('101', '101', '111', '001', '001'),
    '5': ('111', '100', '111', '001', '111'),
    '6': ('111', '100', '111', '101', '111'),
    '7': ('111', '001', '001', '001', '001'),
    '8': ('111', '101', '111', '101', '111'),
    '9': ('111', '101', '111', '001', '111'),
    '-': ('000', '000', '111', '000', '000'),
}


def tray_image_digits(pct, charging, offline):
    """Coloured badge with the battery percentage as the icon itself."""
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if offline or pct is None:
        bg, fg, label = '#4b5563', '#d1d5db', '--'
    else:
        fg = '#ffffff'
        if charging:
            bg = GREEN
        elif pct <= 15:
            bg = RED
        elif pct <= 35:
            bg = AMBER
        else:
            bg = BLUE
        label = str(int(pct))

    d.rounded_rectangle([0, 0, 63, 63], radius=15, fill=bg)

    n = len(label)
    s = 4
    for cand in (9, 8, 7, 6, 5, 4):
        if n * 3 * cand + (n - 1) * cand <= 56:
            s = cand
            break
    w = n * 3 * s + (n - 1) * s
    x0 = (64 - w) // 2
    y0 = (64 - 5 * s) // 2
    for ch in label:
        rows = _DIGITS.get(ch)
        if rows:
            for ry, row in enumerate(rows):
                for rx, bit in enumerate(row):
                    if bit == '1':
                        d.rectangle([x0 + rx * s, y0 + ry * s,
                                     x0 + rx * s + s - 1, y0 + ry * s + s - 1], fill=fg)
        x0 += 4 * s
    return img


# ---------------- panel ----------------
class Panel:
    def __init__(self, reader, app):
        self.reader = reader
        self.app = app
        self.root = tk.Tk()
        self.root.title(APP)
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg=TRANS)
        try:
            self.root.attributes('-transparentcolor', TRANS)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self.root, width=W, height=H, bg=TRANS, highlightthickness=0)
        self.canvas.pack()
        self.root.withdraw()
        self.drag = None
        self._flips = []
        self._last_charging = None
        self.canvas.bind('<Button-1>', self._press)
        self.canvas.bind('<B1-Motion>', self._drag_to)
        self.root.bind('<Escape>', lambda e: self.hide())
        self._signature = None

        pos = app.ui.get('pos')
        if isinstance(pos, list) and len(pos) == 2:
            self.pos = (int(pos[0]), int(pos[1]))
        else:
            self.pos = self.dock_pos()

    @staticmethod
    def dock_pos():
        l, t, r, b = work_area()
        return (r - W - 12, b - H - 12)

    def dock(self):
        self.pos = self.dock_pos()
        self._apply_pos()
        self.app.ui['pos'] = list(self.pos)
        save_state(self.app.ui)

    # ----- geometry -----
    def _apply_pos(self):
        x, y = self.pos
        self.root.geometry(f'{W}x{H}+{x}+{y}')

    def _press(self, e):
        self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())
        if self.canvas.find_withtag('close') and self._hit_close(e):
            self.hide()

    def _hit_close(self, e):
        items = self.canvas.find_overlapping(e.x, e.y, e.x, e.y)
        return any('close' in self.canvas.gettags(i) for i in items)

    def _drag_to(self, e):
        if not self.drag:
            return
        x = e.x_root - self.drag[0]
        y = e.y_root - self.drag[1]
        l, t, r, b = work_area()
        x = max(l, min(x, r - W))
        y = max(t, min(y, b - H))
        self.pos = (x, y)
        self.root.geometry(f'{W}x{H}+{x}+{y}')

    def show(self):
        self._apply_pos()
        self.root.deiconify()
        self.root.attributes('-topmost', True)
        self.root.lift()
        self.root.focus_force()
        self.refresh(force=True)

    def hide(self):
        self.root.withdraw()
        self.app.ui['pos'] = list(self.pos)
        save_state(self.app.ui)

    def toggle(self):
        if self.root.winfo_viewable():
            self.hide()
        else:
            self.show()

    # ----- drawing helpers -----
    def _rr(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
               x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
               x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.canvas.create_polygon(pts, smooth=True, splinesteps=16, **kw)

    def _txt(self, x, y, text, **kw):
        kw.setdefault('font', (FONT, 9))
        kw.setdefault('fill', SUB)
        kw.setdefault('anchor', 'w')
        return self.canvas.create_text(x, y, text=text, **kw)

    # ----- render -----
    def refresh(self, force=False):
        st, ts, err = self.reader.snapshot()
        age = time.time() - ts if ts else None
        online = bool(st) and age is not None and age < 6

        tx = None
        if online and st.get('tx'):
            tx = next((t for t in st['tx'] if t.get('unit') == 1), st['tx'][0])

        gauge = tx['gauge'] if tx else None
        pct = tx.get('percent_estimate') if tx else None
        charging = bool(tx and tx['charging'])

        # track charging on/off flapping -> usually the dock pogo pins
        now = time.time()
        if online:
            if self._last_charging is not None and charging != self._last_charging:
                self._flips.append(now)
            self._last_charging = charging
        self._flips = [t for t in self._flips if now - t < 60]
        n_flip = len(self._flips)
        unstable = n_flip >= 3

        sig = (online, gauge, pct, charging, unstable, n_flip,
               tx and tx['nc_enabled'], tx and tx['low_cut'], tx and tx['auto_off'],
               st and st.get('gain_db'), st and st.get('nc_enabled'),
               st and st.get('auto_off'), st and st.get('stereo'),
               err, int(age) // 5 if age else None)
        if sig == self._signature and not force:
            self.root.after(400, self.refresh)
            return
        self._signature = sig

        c = self.canvas
        c.delete('all')

        # card
        self._rr(1, 1, W - 1, H - 1, 13, fill=CARD, outline=BORDER, width=1)

        # header
        self._txt(16, 18, 'DJI Mic Mini', font=(FONT, 11, 'bold'), fill=TEXT)
        c.create_text(W - 18, 18, text='✕', font=(FONT, 10), fill=FAINT,
                      anchor='e', tags=('close',))
        # generous invisible hit box so the ✕ is easy to click
        c.create_rectangle(W - 34, 4, W - 4, 34, outline='', fill='', tags=('close',))
        # status dot + text
        if online:
            dot, label = GREEN, '已连接'
        elif st:
            dot, label = AMBER, f'无状态帧 {int(age)}s'
        else:
            dot, label = RED, (err or '未连接')
        if unstable:
            dot = AMBER
            label = f'触点接触不稳 · 近1分钟{n_flip}次通断'
        c.create_oval(16, 38, 23, 45, fill=dot, outline='')
        self._txt(29, 42, label, font=(FONT, 9), fill=MUTED)

        c.create_line(16, 60, W - 16, 60, fill='#eef0f3')

        # ---- transmitter ----
        self._txt(16, 72, '发射器 TX1' if tx else '发射器', font=(FONT, 9), fill=MUTED)

        bx1, by1, bx2, by2 = 16, 84, 118, 96
        self._rr(bx1, by1, bx2, by2, 5, fill=TRACK, outline='')
        if gauge:
            frac = max(0.0, min(1.0, (8 - gauge) / 7.0))
            fw = int((bx2 - bx1) * frac)
            if fw >= 3:
                col = GREEN if charging else (RED if gauge >= 6 else (AMBER if gauge == 5 else BLUE))
                self._rr(bx1, by1, bx1 + max(fw, 10), by2, 5, fill=col, outline='')

        gtxt = f'{gauge}/7' if gauge else '—'
        self._txt(126, 90, gtxt, font=(FONT, 12, 'bold'), fill=TEXT)
        ptxt = f'~{pct}%' if pct is not None else ''
        self._txt(168, 91, ptxt, font=(FONT, 9), fill=MUTED)

        cw = 74
        chip_x2 = W - 16
        chip_x1 = chip_x2 - cw
        if not tx:
            self._rr(chip_x1, 82, chip_x2, 98, 8, fill='#f3f4f6', outline='')
            c.create_text((chip_x1 + chip_x2) / 2, 90, text='无数据', font=(FONT, 9), fill=MUTED)
        elif charging:
            self._rr(chip_x1, 82, chip_x2, 98, 8, fill='#e8f7ee', outline='')
            c.create_text((chip_x1 + chip_x2) / 2, 90, text='充电中', font=(FONT, 9), fill=GREEN)
        else:
            self._rr(chip_x1, 82, chip_x2, 98, 8, fill='#f3f4f6', outline='')
            c.create_text((chip_x1 + chip_x2) / 2, 90, text='未充电', font=(FONT, 9), fill=MUTED)

        def onoff(v):
            return '开' if v else '关'

        if tx:
            self._txt(16, 114, f"降噪 {onoff(tx['nc_enabled'])}  ·  低切 {onoff(tx['low_cut'])}"
                               f"  ·  自动关机 {onoff(tx['auto_off'])}", font=(FONT, 9), fill=SUB)
        else:
            self._txt(16, 114, '发射器未开机或不在范围内', font=(FONT, 9), fill=FAINT)

        c.create_line(16, 130, W - 16, 130, fill='#eef0f3')

        # ---- receiver ----
        self._txt(16, 142, '接收器', font=(FONT, 9), fill=MUTED)
        if st and st.get('gain_db') is not None:
            self._txt(16, 160, f"增益 {st['gain_db']:+d} dB  ·  降噪 {onoff(st.get('nc_enabled'))}",
                      font=(FONT, 9), fill=SUB)
            self._txt(16, 178, f"自动关机 {onoff(st.get('auto_off'))}  ·  "
                               f"立体声跟踪 {onoff(st.get('stereo'))}", font=(FONT, 9), fill=SUB)
        else:
            self._txt(16, 160, '—', font=(FONT, 9), fill=FAINT)

        stamp = time.strftime('%H:%M:%S', time.localtime(ts)) if ts else '—'
        c.create_text(16, H - 12, text=f'更新 {stamp}', font=(FONT, 8), fill=FAINT, anchor='w')
        tip = '左键拖动  ·  Esc 收起'
        c.create_text(W - 16, H - 12, text=tip, font=(FONT, 8), fill=FAINT, anchor='e')

        self.root.after(400, self.refresh)


# ---------------- app ----------------
class App:
    def __init__(self):
        self.ui = load_state()
        self.icon_style = self.ui.get('icon_style', 'digits')
        self.reader = Reader()
        self.panel = Panel(self.reader, self)
        self.icon = None
        self.last_icon_sig = None

    # ----- icon -----
    def build_icon(self, gauge, pct, charging, online):
        if self.icon_style == 'digits':
            return tray_image_digits(pct, charging, not online)
        return tray_image(gauge, charging, not online)

    def _icon_loop(self):
        while True:
            st, ts, err = self.reader.snapshot()
            age = time.time() - ts if ts else None
            online = bool(st) and age is not None and age < 6
            tx = None
            if online and st and st.get('tx'):
                tx = next((t for t in st['tx'] if t.get('unit') == 1), st['tx'][0])
            gauge = tx['gauge'] if tx else None
            pct = tx.get('percent_estimate') if tx else None
            charging = bool(tx and tx['charging'])
            sig = (gauge, pct, charging, online, self.icon_style)
            if self.icon and sig != self.last_icon_sig:
                self.last_icon_sig = sig
                try:
                    self.icon.icon = self.build_icon(gauge, pct, charging, online)
                    if online and tx:
                        state = '充电中' if charging else '未充电'
                        self.icon.title = f'DJI Mic Mini · TX1 {gauge}/7 ~{pct}% · {state}'
                    else:
                        self.icon.title = 'DJI Mic Mini · 未连接'
                except Exception:
                    pass
            time.sleep(1)

    # ----- menu actions -----
    def act_show(self, icon=None, item=None):
        self.panel.root.after(0, self.panel.toggle)

    def act_dock(self, icon=None, item=None):
        self.panel.root.after(0, lambda: (self.panel.dock(), self.panel.show()))

    def act_style(self, icon=None, item=None):
        self.icon_style = 'battery' if self.icon_style == 'digits' else 'digits'
        self.ui['icon_style'] = self.icon_style
        save_state(self.ui)
        self.last_icon_sig = None      # force a redraw on the next tick
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def style_checked(self, item):
        return self.icon_style == 'digits'

    def act_autostart(self, icon, item):
        set_autostart(not is_autostart())
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def autostart_checked(self, item):
        return is_autostart()

    def act_quit(self, icon, item):
        self.ui['pos'] = list(self.panel.pos)
        save_state(self.ui)
        self.reader.stopped = True
        try:
            self.icon.stop()
        except Exception:
            pass
        self.panel.root.after(0, self.panel.root.destroy)

    def run(self):
        menu = pystray.Menu(
            pystray.MenuItem('显示面板', self.act_show, default=True),
            pystray.MenuItem('图标上显示电量数字', self.act_style, checked=self.style_checked),
            pystray.MenuItem('复位到右下角', self.act_dock),
            pystray.MenuItem('开机自动运行', self.act_autostart, checked=self.autostart_checked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出', self.act_quit),
        )
        self.icon = pystray.Icon('dji_mic_mini',
                                 self.build_icon(None, None, False, False),
                                 'DJI Mic Mini · 正在连接…', menu)
        self.reader.start()
        threading.Thread(target=self.icon.run, daemon=True).start()
        threading.Thread(target=self._icon_loop, daemon=True).start()

        if '--hidden' not in sys.argv:
            self.panel.root.after(300, self.panel.show)
        self.panel.refresh(force=True)
        self.panel.root.mainloop()


def main():
    if already_running():
        return
    App().run()


if __name__ == '__main__':
    main()
