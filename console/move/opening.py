"""The opening animation on the screen at start-up (made in the Move Screen Designer: anim/opening).

    op = Opening()
    if op.draw(frame, now):    # True while it's playing (the frame drawn); False once it's done
"""
import json
import os

import numpy as np

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anim", "opening")


def _load():
    """[(pixels (64, 128), seconds shown)], or [] if it can't be read."""
    try:
        with open(os.path.join(HERE, "animation.json")) as f:
            meta = json.load(f)
        fps = float(meta.get("meta", {}).get("fps", 10)) or 10.0
        out = []
        for n, fr in enumerate(meta["frames"], 1):
            with open(os.path.join(HERE, "hex", "%03d.txt" % n)) as f:
                rows = [r.strip() for r in f if r.strip()]
            px = np.array([[(int(r, 16) >> (127 - x)) & 1 for x in range(128)] for r in rows[:64]], np.uint8)
            out.append((px, max(1, int(fr.get("hold", 1))) / fps))
        return out
    except Exception as ex:                       # noqa: BLE001
        print("Opening animation:", ex)
        return []


class Opening:
    def __init__(self):
        self.frames = _load()
        self.start = None
        self.done = not self.frames

    def stop(self):
        self.done = True

    def draw(self, frame, now):
        if self.done:
            return False
        if self.start is None:
            self.start = now
        t = now - self.start
        for px, secs in self.frames:
            if t < secs:
                frame.px[:] = px
                return True
            t -= secs
        self.done = True
        return False
