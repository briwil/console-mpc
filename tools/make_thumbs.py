#!/usr/bin/env python3
"""Pictures for instruments and inserts (128x64, 1 bit, white on black), in the format of console/move/instimg and fximg
(64 rows of 32 hex digits).  python3 tools/make_thumbs.py  writes them and a preview sheet (thumbs-preview.png).
The OP-1 Suite ones are a simplified OP-1 with the name at the bottom left; the others have a picture of their own."""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MOVE = os.path.join(ROOT, "console", "move")
FONT = os.path.join(ROOT, "mpcui", "fonts", "Silkscreen-Regular.ttf")
BIG = os.path.join(ROOT, "mpcui", "fonts", "Jersey15-Regular.ttf")
W, H = 128, 64


class Pic:
    def __init__(self):
        self.im = Image.new("1", (W, H), 0)
        self.d = ImageDraw.Draw(self.im)
        self.d.fontmode = "1"
        self.font = ImageFont.truetype(FONT, 8)
        self.big = ImageFont.truetype(BIG, 16)
        self.mid = ImageFont.truetype(BIG, 14)

    def px(self, x, y, v=1):
        if 0 <= x < W and 0 <= y < H:
            self.im.putpixel((int(x), int(y)), v)

    def rect(self, x0, y0, x1, y1, fill=False, v=1):
        (self.d.rectangle([x0, y0, x1, y1], fill=v) if fill else self.d.rectangle([x0, y0, x1, y1], outline=v))

    def line(self, x0, y0, x1, y1, v=1):
        self.d.line([x0, y0, x1, y1], fill=v)

    def circle(self, cx, cy, r, fill=False, v=1):
        self.d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=v, fill=v if fill else None)

    def knob(self, cx, cy, r=3, ang=None):
        self.circle(cx, cy, r)
        a = math.radians(-135 + 270 * (0.5 if ang is None else ang))
        self.line(cx, cy, cx + round(math.sin(a) * (r - 1)), cy - round(math.cos(a) * (r - 1)))

    def text(self, x, y, s, v=1):
        self.d.text((x, y - 1), s, fill=v, font=self.font)

    def title(self, x, y, s, v=1):
        self.d.text((x, y), s, fill=v, font=self.big)

    def heading(self, x, y, s, v=1):
        self.d.text((x, y), s, fill=v, font=self.mid)

    def frame(self):
        self.rect(0, 0, W - 1, H - 1)

    def hex(self):
        a = np.array(self.im, np.uint8)
        return ["%032x" % int("".join(str(int(b)) for b in row), 2) for row in a]


# ------------------------------------------------------------------ the OP-1 sketch, simplified
def op1(name):
    p = Pic()
    p.rect(2, 2, 125, 45)                                    # the body
    for gy in range(4):                                      # speaker dots
        for gx in range(5):
            p.px(7 + gx * 3, 6 + gy * 3)
    p.rect(24, 6, 46, 16)                                    # screen
    p.line(27, 8, 43, 8)
    for i in range(4):
        p.rect(27 + i * 4, 11, 29 + i * 4, 14)
    for i in range(4):                                       # the four encoders
        cx = 62 + i * 14
        p.rect(cx - 6, 5, cx + 6, 16)
        p.knob(cx, 10, 3, (0.2, 0.45, 0.7, 0.35)[i])
    p.rect(114, 5, 121, 16)                                  # (play)
    p.line(116, 8, 116, 13)
    p.line(116, 8, 119, 10)
    p.line(116, 13, 119, 10)
    for row, n in ((20, 14), (26, 11)):                      # button rows
        for i in range(n):
            p.rect(6 + i * 8, row, 10 + i * 8, row + 4)
    for i in range(15):                                      # keys
        x = 6 + round(i * 7.6)
        p.rect(x, 32, x + 5, 42)
    p.title(3, 46, name)
    return p


# ------------------------------------------------------------------ pictures of their own
def keys(p, x0, y0, x1, y1, n):
    w = (x1 - x0) / n
    p.rect(x0, y0, x1, y1)
    for i in range(1, n):
        p.line(round(x0 + i * w), y0, round(x0 + i * w), y1)
    for i in range(n - 1):
        if i % 7 not in (2, 6):
            x = round(x0 + (i + 1) * w - w * 0.3)
            p.rect(x, y0, x + max(1, round(w * 0.6)), y0 + (y1 - y0) * 3 // 5, fill=True)


def profit5(name="PROFIT-5"):
    p = Pic()
    p.rect(2, 2, 125, 61)
    p.heading(5, 3, name) if len(name) < 12 else p.text(6, 6, name)
    for i in range(5):                                       # five voices
        p.circle(78 + i * 9, 9, 2, fill=(i % 2 == 0))
    for i in range(10):
        p.knob(10 + i * 11, 26, 3, (i * 37 % 10) / 10)
    p.rect(6, 33, 20, 40)                                    # wheels
    p.rect(6, 43, 20, 58)
    keys(p, 24, 43, 122, 58, 12)
    for i in range(7):
        p.rect(24 + i * 14, 34, 30 + i * 14, 38)
    return p


def jn106(name="JN-106"):
    p = Pic()
    p.rect(2, 2, 125, 61)
    p.heading(5, 3, name) if len(name) < 12 else p.text(6, 6, name)
    p.rect(88, 5, 121, 12)
    for i in range(8):                                       # the Juno sliders
        x = 10 + i * 14
        p.rect(x, 16, x + 3, 38)
        y = 18 + (i * 7) % 16
        p.rect(x - 2, y, x + 5, y + 3, fill=True)
    keys(p, 6, 43, 121, 58, 14)
    return p


def sturm(name="STURM-TP"):
    p = Pic()
    p.rect(2, 2, 125, 61)
    p.heading(5, 3, name) if len(name) < 12 else p.text(6, 6, name)
    for r in range(4):                                       # pads
        for c in range(4):
            on = (r * 4 + c) in (0, 5, 6, 10, 15)
            p.rect(76 + c * 11, 14 + r * 11, 83 + c * 11, 21 + r * 11, fill=on)
    for i in range(2):                                       # two sample oscillators
        y = 20 + i * 18
        p.rect(6, y, 62, y + 13)
        pts = [(8 + k, y + 7 + round(5 * math.sin(k / (4 + i * 3.0)) * (1 - k / 70))) for k in range(0, 52)]
        for a, b in zip(pts, pts[1:]):
            p.line(a[0], a[1], b[0], b[1])
    return p


def monomodule(name="MONOMODULE"):
    p = Pic()
    p.rect(2, 2, 125, 61)
    p.heading(5, 3, name) if len(name) < 12 else p.text(6, 6, name)
    p.rect(6, 17, 56, 38)                                    # the little LCD
    for i, v in enumerate((7, 12, 5, 14, 9, 11, 4, 13, 8, 10)):
        p.line(9 + i * 5, 36, 9 + i * 5, 36 - v)
    for i in range(4):
        for j in range(2):
            p.knob(70 + i * 14, 24 + j * 14, 4, (i * 3 + j * 5) % 10 / 10)
    for i in range(16):
        p.rect(6 + i * 7, 46, 10 + i * 7, 50, fill=(i % 4 == 0))
    p.rect(6, 54, 121, 58)
    return p


def clementine(name="CLEMENTINE-XT"):
    p = Pic()
    p.rect(2, 2, 125, 61)
    p.heading(5, 3, name) if len(name) < 12 else p.text(6, 6, name)
    for k in range(6):                                       # a wavetable: the wave morphs from row to row
        y = 22 + k * 7
        prev = None
        for x in range(8, 100):
            t = x / 92
            v = math.sin(x / (3.0 + k * 0.9)) * (4 - k * 0.3) + 0
            pt = (x, y + round(v * 0.9) - 2)
            if prev:
                p.line(prev[0], prev[1], pt[0], pt[1])
            prev = pt
    p.knob(112, 26, 5, .7)
    p.knob(112, 44, 5, .3)
    return p


def w9(name="9W9"):
    p = Pic()
    p.rect(2, 2, 125, 61)
    p.rect(6, 5, 61, 16, fill=True)
    p.text(9, 7, name, 0)
    for i in range(6):
        p.circle(72 + i * 9, 10, 3, fill=(i == 2))
    for i in range(16):                                      # steps
        p.rect(6 + i * 7, 21, 10 + i * 7, 25, fill=(i % 4 == 0 or i in (6, 10, 14)))
    for r in range(2):                                       # pads
        for c in range(6):
            p.rect(6 + c * 14, 31 + r * 14, 6 + c * 14 + 10, 31 + r * 14 + 10, fill=((r * 6 + c) in (0, 3, 8)))
    p.rect(92, 31, 121, 59)
    p.knob(100, 40, 3, .3)
    p.knob(113, 40, 3, .7)
    p.knob(100, 52, 3, .6)
    p.knob(113, 52, 3, .2)
    return p


def oxzygen(name="OXZYGEN"):
    p = Pic()
    p.rect(2, 2, 125, 61)
    p.heading(5, 3, name) if len(name) < 12 else p.text(6, 6, name)
    for (cx, cy, r) in ((22, 40, 11), (50, 32, 7), (70, 46, 9), (92, 30, 5), (106, 46, 7), (38, 54, 3), (84, 54, 3), (116, 22, 3)):
        p.circle(cx, cy, r)
        if r > 4:
            p.circle(cx - r // 3, cy - r // 3, 1, fill=True)
    pts = [(60 + k, 18 + round(3 * math.sin(k / 4.0))) for k in range(0, 56)]
    for a, b in zip(pts, pts[1:]):
        p.line(a[0], a[1], b[0], b[1])
    return p


def vhs(name="VHS VIBES"):
    p = Pic()
    p.rect(2, 2, 125, 61)
    p.rect(8, 8, 119, 46)                                    # the cassette
    p.rect(14, 12, 113, 24)                                  # label
    p.text(18, 14, name)
    p.rect(30, 30, 97, 42)                                   # the tape window
    p.circle(44, 36, 5)
    p.circle(83, 36, 5)
    for a in (0, 120, 240):
        for cx in (44, 83):
            t = math.radians(a)
            p.line(cx, 36, cx + round(math.sin(t) * 4), 36 - round(math.cos(t) * 4))
    p.line(49, 36, 78, 36)
    for i in range(0, 96, 3):                                # wobbling tape underneath
        p.px(16 + i, 52 + round(2 * math.sin(i / 5.0)))
        p.px(17 + i, 55 + round(2 * math.sin(i / 3.0 + 1)))
    return p


def boris(name="BORIS"):
    p = Pic()
    p.rect(2, 2, 125, 61)
    p.heading(5, 3, name) if len(name) < 12 else p.text(6, 6, name)
    import random
    rnd = random.Random(7)
    for _ in range(26):                                      # grains: small windowed bursts
        x = rnd.randint(8, 118)
        y = rnd.randint(18, 56)
        r = rnd.choice((1, 1, 2, 3))
        p.circle(x, y, r, fill=rnd.random() < 0.4)
    for i in range(5):                                       # the buffer
        p.line(8, 59, 118, 59)
    p.rect(88, 6, 120, 12)
    return p


OP1_INSTRUMENTS = {"op1-cluster": "CLUSTER", "op1-dbox": "DBOX", "op1-digital": "DIGITAL", "op1-dna": "DNA", "op1-drwave": "DR WAVE",
                   "op1-dsynth": "D SYNTH", "op1-fm": "FM", "op1-phase": "PHASE", "op1-pulse": "PULSE", "op1-string": "STRING",
                   "op1-voltage": "VOLTAGE"}
OP1_FX = {"op1-cwo": "CWO", "op1-delay": "DELAY", "op1-grid": "GRID", "op1-nitro": "NITRO", "op1-phone": "PHONE", "op1-punch": "PUNCH",
          "op1-spring": "SPRING"}
OTHERS = {"instimg": {"profit5": profit5, "jn106": jn106, "sturm": sturm, "monomodule": monomodule, "clementine": clementine,
                      "w9": w9, "oxzygen": oxzygen},
          "fximg": {"vhs-vibes": vhs, "boris": boris}}


def main():
    sheet = []
    out = {}
    for mid, nm in OP1_INSTRUMENTS.items():
        out[("instimg", mid)] = op1(nm)
    for mid, nm in OP1_FX.items():
        out[("fximg", mid)] = op1(nm)
    for folder, d in OTHERS.items():
        for mid, fn in d.items():
            out[(folder, mid)] = fn()
    for (folder, mid), p in out.items():
        os.makedirs(os.path.join(MOVE, folder), exist_ok=True)
        with open(os.path.join(MOVE, folder, mid + ".txt"), "w") as f:
            f.write("\n".join(p.hex()) + "\n")
        sheet.append((mid, p))
    old = os.path.join(MOVE, "instimg", "model-72.txt")             # (Model-72 has its picture already, under the Move's id)
    if os.path.exists(old):
        open(os.path.join(MOVE, "instimg", "model72.txt"), "w").write(open(old).read())
    cols = 4
    rows = (len(sheet) + cols - 1) // cols
    img = Image.new("L", (cols * 136 + 8, rows * 84 + 8), 40)
    d = ImageDraw.Draw(img)
    for i, (mid, p) in enumerate(sheet):
        x, y = 8 + (i % cols) * 136, 8 + (i // cols) * 84
        d.text((x, y - 2), mid, fill=200)
        img.paste(p.im.convert("L").point(lambda v: 255 if v else 0), (x, y + 10))
    img = img.resize((img.width * 2, img.height * 2), Image.NEAREST)
    img.save(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "thumbs-preview.png"))
    print(len(out), "pictures")


if __name__ == "__main__":
    main()
