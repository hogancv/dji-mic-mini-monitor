"""Generate build/icon.ico for the packaged exe.

Drawn at 4x and downsampled so the bitmap stays crisp at 16 px.
Design: solid green rounded square + white battery glyph, matching the
tray icon's look while staying legible at taskbar size.

    python scripts/make_icon.py [output.ico]
"""
import os
import sys

from PIL import Image, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join('build', 'icon.ico')
S = 512                      # logical canvas
K = 4                        # supersample factor
W = S * K

GREEN = (22, 163, 74, 255)   # #16a34a
WHITE = (255, 255, 255, 255)


def draw_icon():
    img = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = W // 32
    d.rounded_rectangle([pad, pad, W - pad, W - pad], radius=int(W * 0.22), fill=GREEN)

    # battery body + cap, scaled from the 64 px tray design (10..57 x 18..46)
    sx = W / 64.0
    x0, y0, x1, y1 = 13 * sx, 20 * sx, 47 * sx, 44 * sx
    stroke = int(3.2 * sx)
    d.rounded_rectangle([x0, y0, x1, y1], radius=int(3 * sx), outline=WHITE, width=stroke)
    d.rounded_rectangle([x1 + stroke * 0.6, (y0 + y1) / 2 - 3.2 * sx,
                         x1 + stroke * 2.6, (y0 + y1) / 2 + 3.2 * sx],
                        radius=int(1.4 * sx), fill=WHITE)
    # two thirds full
    inner = [x0 + stroke * 1.6, y0 + stroke * 1.6, x0 + (x1 - x0) * 0.62, y1 - stroke * 1.6]
    d.rounded_rectangle(inner, radius=int(1.6 * sx), fill=WHITE)
    return img.resize((S, S), Image.LANCZOS)


def main():
    os.makedirs(os.path.dirname(OUT) or '.', exist_ok=True)
    icon = draw_icon()
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    icon.save(OUT, format='ICO', sizes=sizes)
    print(f'wrote {OUT} ({os.path.getsize(OUT)} bytes, sizes {[s[0] for s in sizes]})')


if __name__ == '__main__':
    main()
