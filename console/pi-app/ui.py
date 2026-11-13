"""Screen layout: reads the code from the Console Screen Designer and draws it with pygame.

The layout file holds one command per line, exactly as the designer writes them:

    ui.fill(name, x, y, w, h, colour, radius)
    ui.frame(name, x, y, w, h, line, colour, radius)
    ui.text(name, x, y, size, colour, font, weight, align, "TEXT")   # font is an id from fonts/fonts.json
    ui.line(name, x1, y1, x2, y2, width, colour)
    ui.circle(name, x, y, radius, line, colour)      # line 0 = filled
    ui.wave(name, x, y, w, h, colour)
    ui.meter(name, x, y, w, h, colour, level)

Every item has a name, so the app can change it while running, for example
screen.set("clock", t="012.3.1") or screen.set("playhead", x1=600, x2=600).
"""
import json
import math
import os
import re

import pygame

WIDTH, HEIGHT = 1280, 400
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")


def _load_fonts():
    """fonts/fonts.json lists every font: id -> {"name": ..., "files": {"400": "file.ttf", ...}}."""
    with open(os.path.join(FONT_DIR, "fonts.json"), encoding="utf-8") as f:
        data = json.load(f)
    return {fid: {int(w): fn for w, fn in info["files"].items()} for fid, info in data.items()}


FONT_FILES = _load_fonts()


def system_family(family):
    """The theme page can swap the two fonts everything else uses: "sans" (main text, the menus) and
    "mono" (labels and numbers: the tape, the sequencer, the FX pages)."""
    if family not in ("sans", "mono"):
        return family
    try:
        import theme
        fams = theme.section("system").get("families", {})
    except Exception:
        return family
    chosen = fams.get("main_text" if family == "sans" else "labels_and_numbers", family)
    return chosen if chosen in FONT_FILES else family

# ---------------------------------------------------------------- reading the layout

# command -> (item type, argument kinds, field names); n = number, c = colour, s = text
SPEC = {
    "fill": ("rect", "snnnncn", ["name", "x", "y", "w", "h", "c", "r"]),
    "frame": ("frame", "snnnnncn", ["name", "x", "y", "w", "h", "t", "c", "r"]),
    "text": ("text", "snnncsnss", ["name", "x", "y", "s", "c", "f", "wt", "a", "t"]),
    "line": ("line", "snnnnnc", ["name", "x1", "y1", "x2", "y2", "t", "c"]),
    "circle": ("circle", "snnnnc", ["name", "x", "y", "rad", "t", "c"]),
    "wave": ("wave", "snnnnc", ["name", "x", "y", "w", "h", "c"]),
    "meter": ("meter", "snnnncn", ["name", "x", "y", "w", "h", "c", "v"]),
}
LINE_RE = re.compile(r'^\s*ui\.(\w+)\s*\((.*)\)\s*;?\s*(//.*)?$')
HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def split_args(s):
    """Split 'a, "b, c", 3' into ['a', 'b, c', '3'], keeping track of which were quoted."""
    out, cur, in_q, quoted, i = [], "", False, False, 0
    while i < len(s):
        ch = s[i]
        if in_q:
            if ch == "\\" and i + 1 < len(s):
                cur += s[i + 1]
                i += 2
                continue
            if ch == '"':
                in_q = False
            else:
                cur += ch
        elif ch == '"':
            if cur.strip():
                return None
            cur, in_q, quoted = "", True, True
        elif ch == ",":
            out.append((cur if quoted else cur.strip(), quoted))
            cur, quoted = "", False
        elif not quoted:
            cur += ch
        i += 1
    if in_q:
        return None
    if cur.strip() or quoted or out:
        out.append((cur if quoted else cur.strip(), quoted))
    return out


def parse_line(line):
    m = LINE_RE.match(line)
    if not m or m.group(1) not in SPEC:
        return None
    kind, kinds, keys = SPEC[m.group(1)]
    args = split_args(m.group(2))
    if args is None or len(args) != len(kinds):
        return None
    it = {"type": kind}
    for (val, quoted), k, key in zip(args, kinds, keys):
        if k == "n":
            try:
                it[key] = int(round(float(val)))
            except ValueError:
                return None
            if quoted:
                return None
        elif k == "c":
            if not HEX_RE.match(val):
                return None
            it[key] = val.upper()
        else:
            it[key] = val
    if kind == "text":
        it["f"] = it["f"] if it["f"] in FONT_FILES else "sans"
        it["a"] = it["a"] if it["a"] in ("left", "center", "right") else "left"
        it["s"] = max(4, it["s"])
    for key in ("w", "h", "rad"):
        if key in it:
            it[key] = max(1, it[key])
    if kind in ("frame", "line"):
        it["t"] = max(1, it["t"])
    if kind == "circle":
        it["t"] = max(0, it["t"])
    return it


def parse(text):
    """Turn designer code into a list of items. Returns (items, number of lines skipped)."""
    items, bad = [], 0
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("//"):
            continue
        it = parse_line(line)
        if it:
            items.append(it)
        else:
            bad += 1
    return items, bad


# ---------------------------------------------------------------- sample waveform
# The same pseudo-random waveform the designer shows, so the two look alike.
# Real recordings will replace this once the audio engine exists.

M32 = 0xFFFFFFFF


def _hash(s):
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & M32
    return h


def _rng(seed):
    state = [seed & M32]

    def nxt():
        state[0] = (state[0] + 0x6D2B79F5) & M32
        s = state[0]
        t = ((s ^ (s >> 15)) * (1 | s)) & M32
        t = (((t + (((t ^ (t >> 7)) * (61 | t)) & M32)) & M32) ^ t)
        return ((t ^ (t >> 14)) & M32) / 4294967296
    return nxt


def _jsround(v):
    return math.floor(v + 0.5)


def sample_wave_bars(name, x, y, w, h):
    """List of (x, y, w, h) bars for the sample waveform."""
    r = _rng(_hash(name or "wave"))
    cy = y + h / 2
    env, target, run = 0.0, 0.0, 0
    on = r() > .3
    bars = []
    px = x
    while px < x + w - 1:
        old = run
        run -= 1
        if old <= 0:
            on = r() > .28
            run = 10 + math.floor(r() * 60)
            target = .35 + r() * .65 if on else 0
        env += (target - env) * .18
        a = max(env * (.45 + r() * .55), .04) * (h - 2)
        bars.append((px, _jsround(cy - a / 2), 2, max(1, _jsround(a))))
        px += 3
    return bars


# ---------------------------------------------------------------- drawing

def rgb(c):
    return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))


class Screen:
    def __init__(self, items):
        self.items = items
        self.by_name = {it["name"]: it for it in items if it.get("name")}
        self._fonts = {}
        self._waves = {}
        # name -> function(surface, item) that draws that item instead of the normal drawing
        self.custom = {}
        # name -> function(surface) drawn straight after that item
        self.after = {}

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            items, bad = parse(f.read())
        if bad:
            print(f"Layout: skipped {bad} line(s) in {os.path.basename(path)} that weren't understood")
        return cls(items)

    def get(self, name):
        return self.by_name.get(name)

    def set(self, name, **changes):
        """Change an item by name, e.g. set("clock", t="001.1.1"). Returns True if anything changed."""
        it = self.by_name.get(name)
        if not it:
            return False
        changed = any(it.get(k) != v for k, v in changes.items())
        it.update(changes)
        return changed

    def font(self, family, weight, size):
        family = system_family(family)
        weights = FONT_FILES.get(family) or FONT_FILES["sans"]
        wt = min(weights, key=lambda w: abs(w - weight))
        key = (family, wt, size)
        if key not in self._fonts:
            path = os.path.join(FONT_DIR, weights[wt])
            self._fonts[key] = pygame.font.Font(path if os.path.exists(path) else None, size)
        return self._fonts[key]

    def _wave_surface(self, it):
        key = (it["name"], it["w"], it["h"], it["c"])
        surf = self._waves.get(key)
        if surf is None:
            surf = pygame.Surface((it["w"], it["h"]), pygame.SRCALPHA)
            col = rgb(it["c"])
            for bx, by, bw, bh in sample_wave_bars(it["name"], 0, 0, it["w"], it["h"]):
                surf.fill(col, (bx, by, bw, bh))
            self._waves[key] = surf
        return surf

    def draw(self, surf):
        surf.fill((0, 0, 0))
        for it in self.items:
            self.draw_item(surf, it)

    def draw_item(self, surf, it):
        fn = self.custom.get(it.get("name"))
        if fn:
            fn(surf, it)
        else:
            self.draw_default(surf, it)
        after = self.after.get(it.get("name"))
        if after:
            after(surf)

    def draw_default(self, surf, it):
        kind, col = it["type"], rgb(it["c"])
        if kind == "rect":
            pygame.draw.rect(surf, col, (it["x"], it["y"], it["w"], it["h"]), 0, it["r"])
        elif kind == "frame":
            t = max(1, min(it["t"], it["w"] // 2, it["h"] // 2))
            pygame.draw.rect(surf, col, (it["x"], it["y"], it["w"], it["h"]), t, it["r"])
        elif kind == "text":
            if not it["t"]:
                return
            img = self.font(it["f"], it["wt"], it["s"]).render(it["t"], True, col)
            x = it["x"]
            if it["a"] == "center":
                x -= img.get_width() // 2
            elif it["a"] == "right":
                x -= img.get_width()
            surf.blit(img, (x, it["y"]))
        elif kind == "line":
            pygame.draw.line(surf, col, (it["x1"], it["y1"]), (it["x2"], it["y2"]), it["t"])
        elif kind == "circle":
            pygame.draw.circle(surf, col, (it["x"], it["y"]), it["rad"], it["t"])
        elif kind == "wave":
            surf.blit(self._wave_surface(it), (it["x"], it["y"]))
        elif kind == "meter":
            back = pygame.Surface((it["w"], it["h"]), pygame.SRCALPHA)
            back.fill(col + (64,))
            surf.blit(back, (it["x"], it["y"]))
            v = max(0, min(100, it["v"])) / 100
            if it["w"] >= it["h"]:
                pygame.draw.rect(surf, col, (it["x"], it["y"], round(it["w"] * v), it["h"]))
            else:
                fh = round(it["h"] * v)
                pygame.draw.rect(surf, col, (it["x"], it["y"] + it["h"] - fh, it["w"], fh))
