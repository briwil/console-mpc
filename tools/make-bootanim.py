#!/usr/bin/env python3
"""Packs a Sample Screen Designer export (the unzipped folder with anim.txt and rgb/NNN.rgb) into launcher/bootanim.bin.
   python3 tools/make-bootanim.py <folder> [out]     "CANM", u16 frames, u16 fps, a hold byte per frame, raw 320x240 RGB frames"""
import struct, sys, os
args = [a for a in sys.argv[1:] if a != "--png"]; use_png = "--png" in sys.argv    # --png: take the pictures in frames/ (needs Pillow) instead of rgb/
d = args[0]; out = args[1] if len(args) > 1 else os.path.join(os.path.dirname(__file__), "..", "launcher", "bootanim.bin")
fps, holds = 12, []
for line in open(os.path.join(d, "anim.txt")):
    w = line.split()
    if w[:1] == ["fps"]: fps = int(w[1])
    if w[:1] == ["frame"]: holds.append(int(w[3]))
data = b""
for i in range(len(holds)):
    if use_png:
        from PIL import Image
        f = Image.open(os.path.join(d, "frames", "%03d.png" % (i + 1))).convert("RGB").tobytes()
    else:
        f = open(os.path.join(d, "rgb", "%03d.rgb" % (i + 1)), "rb").read()
    assert len(f) == 320 * 240 * 3, "frame %d is not 320x240 RGB" % (i + 1)
    data += f
open(out, "wb").write(b"CANM" + struct.pack("<HH", len(holds), fps) + bytes(holds) + data)
print("wrote", out, len(holds), "frames at", fps, "ticks/s,", len(data) // 1024, "KB")
