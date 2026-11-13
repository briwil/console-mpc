#!/usr/bin/env python3
"""Draws the first-install progress pictures: launcher/install-screens.raw = six 320x240 frames, 4 bytes per pixel (B, G, R, 0),
one after the other (the screen is 32-bit; only black, grey and white are used, so the colour order doesn't matter).
install.sh writes one of them to /dev/fb0 with dd:  0 starting, 1 checking, 2 copying Console, 3 copying Python, 4 done, 5 error.
   python3 tools/make-install-screens.py [out]        (needs Pillow)"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "launcher", "install-screens.raw")
FONT = os.path.join(HERE, "..", "mpcui", "fonts", "Silkscreen-Regular.ttf")
W, H = 320, 240
BIG, SMALL = ImageFont.truetype(FONT, 16), ImageFont.truetype(FONT, 8)


def frame(title, lines, bar=None, small=()):
    im = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(im)

    def centred(text, y, font, fill=(255, 255, 255)):
        w = d.textlength(text, font=font)
        d.text(((W - w) // 2, y), text, font=font, fill=fill)
    centred(title, 40, BIG)
    y = 84
    for t in lines:
        centred(t, y, BIG, (190, 190, 190))
        y += 26
    if bar is not None:
        d.rectangle([40, 150, 280, 168], outline=(255, 255, 255))
        d.rectangle([43, 153, 43 + int(234 * bar), 165], fill=(255, 255, 255))
    y = 190
    for t in small:
        centred(t, y, SMALL, (150, 150, 150))
        y += 14
    return im


FRAMES = [
    frame("INSTALLING CONSOLE", ["PLEASE WAIT"], 0.05, ["THIS TAKES ABOUT A MINUTE", "DON'T SWITCH THE MPC OFF"]),
    frame("INSTALLING CONSOLE", ["CHECKING THE FILES"], 0.15, ["THIS TAKES ABOUT A MINUTE", "DON'T SWITCH THE MPC OFF"]),
    frame("INSTALLING CONSOLE", ["COPYING CONSOLE"], 0.45, ["THIS TAKES ABOUT A MINUTE", "DON'T SWITCH THE MPC OFF"]),
    frame("INSTALLING CONSOLE", ["COPYING PYTHON"], 0.8, ["THIS TAKES ABOUT A MINUTE", "DON'T SWITCH THE MPC OFF"]),
    frame("CONSOLE IS INSTALLED", ["STARTING"], 1.0),
    frame("COULDN'T INSTALL", ["THE MPC APP STARTS NOW"], None,
          ["WHAT HAPPENED IS IN THE FILE", "CONSOLE/INSTALL-STATUS.TXT", "ON THE SD CARD"]),
]
data = bytearray()
for im in FRAMES:
    px = im.tobytes()
    for i in range(0, len(px), 3):
        data += bytes((px[i + 2], px[i + 1], px[i], 0))
open(OUT, "wb").write(bytes(data))
print("wrote", OUT, len(FRAMES), "frames,", len(data) // 1024, "KB")
if "--png" in sys.argv:
    for n, im in enumerate(FRAMES):
        im.save("/tmp/install-screen-%d.png" % n)
