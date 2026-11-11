"""The instrument's sound page, designed by Brian: the page line and the instrument's name in big pixel letters, a green
rounded frame under them, and the eight settings in two rows. The setting being touched / turned grows (label 24 px, value up
to 64 px) while the others turn dark and slide out of its way; when it is let go everything eases back.

Everything moves: each setting keeps its own position, text sizes and colour and, every frame, eases toward where it should be
now (exponentially, about a fifth of a second). Silkscreen is only sharp at whole multiples of 8 px, so the sizes step through
8 / 16 / 24 / ... as they grow and shrink (a quick pop-zoom, not a soft smooth one)."""
import math
import time

import numpy as np

import colour

W, H = 320, 240
DARK = colour.DARK_TEXT
WHITE = (255, 255, 255)

# ---- the layout (320 x 240 pixels, taken from the design's SVG) ----
COLS = [46.5, 92.0, 137.5, 183.0]            # the centres of the four columns
LABEL_BASE = [162.5, 205.5]                  # label baselines of the two rows
VALUE_MID = [180.0, 222.5]                   # the line through the middle of a 24 px value in each row
BIG_LABEL = 24                               # the label of the setting being turned
BIG_VALUE = 64                               # ... and its value (the largest that fits)
BIG_MID = [188.5 - 20.0, 230.0 - 20.0]       # the line through the middle of the big value
BIG_LABEL_UP = 57.5                          # the big label's baseline is this far above the big value's baseline
BIG_SHIFT = 26.5                             # the big setting sits this far right of its column
NEAR = 5.0                                   # the settings left of the big one slide this far left
SAME_ROW = 49.0                              # the ones right of it in its row make room
OTHER_ROW = 89.4                             # ... and in the row above it (it reaches up into that row)
TAU = 0.06                                   # seconds: how quickly things ease
LAST = {"key": None, "t": 0.0, "state": None}

_bands = None


def _band_stroke(mask, y, xend, r, w):
    yy, xx = np.mgrid[0:H, 0:W]
    yy, xx = yy + 0.5, xx + 0.5
    cy = y + r
    d = np.sqrt((xx - xend) ** 2 + (yy - cy) ** 2)
    mask |= (abs(yy - y) <= w / 2) & (xx <= xend)                      # the run from the left edge
    mask |= (abs(d - r) <= w / 2) & (xx >= xend) & (yy <= cy)           # the rounded corner
    mask |= (abs(xx - (xend + r)) <= w / 2) & (yy >= cy)                # and down the right side


def bands():
    """The two green bands as a picture (built once): the lighter one outside, the darker one inside."""
    global _bands
    if _bands is None:
        img = np.zeros((H, W, 3), np.uint8)
        outer = np.zeros((H, W), bool)
        inner = np.zeros((H, W), bool)
        _band_stroke(outer, 72.4, 248.6, 59.5, 10.5)
        _band_stroke(inner, 85.4, 248.7, 46.4, 10.5)
        img[outer] = colour.GREENS[3]
        img[inner] = colour.GREENS[2]
        _bands = img
    return _bands


def targets(n, active, texts):
    """Where each of the settings (0..n-1) should be: {cx, lb (label baseline), vm (middle of the value), ls, vs, t (0 dark .. 1 white)}.
    texts[i] = (label, value). active = the index of the one being turned, or None."""
    out = []
    ra, ca = (active // 4, active % 4) if active is not None else (None, None)
    for i in range(n):
        r, c = i // 4, i % 4
        cx = COLS[c]
        if active is None:
            out.append(dict(cx=cx, lb=LABEL_BASE[r], vm=VALUE_MID[r], ls=8, vs=24, t=1.0))
        elif i == active:
            out.append(dict(cx=COLS[c] + BIG_SHIFT, lb=BIG_MID[r] + 20.0 - BIG_LABEL_UP, vm=BIG_MID[r], ls=BIG_LABEL, vs=BIG_VALUE, t=1.0))
        else:
            if c < ca:
                cx -= NEAR
            elif r == ra and c > ca:
                cx += SAME_ROW
            elif r != ra and ra == 1 and c >= ca:
                cx += OTHER_ROW
            out.append(dict(cx=cx, lb=LABEL_BASE[r], vm=VALUE_MID[r], ls=8, vs=24, t=0.0))
    return out


def step(state, goal, dt, snap=False):
    """Eases the settings' current values (state) toward the targets (goal)."""
    k = 1.0 if snap else 1.0 - math.exp(-dt / TAU)
    for s, g in zip(state, goal):
        for key in ("cx", "lb", "vm", "ls", "vs", "t"):
            s[key] = g[key] if snap or key not in s else s[key] + (g[key] - s[key]) * k


def fit_size(font_of, text, sizes, width, trk):
    """The largest of the sizes whose text fits in width pixels."""
    for px in sizes:
        if text_width(font_of(px), text, trk(px)) <= width:
            return px
    return sizes[-1]


def text_width(font, s, track):
    return int(sum(font.getlength(ch) for ch in s) + track * max(0, len(s) - 1) + 0.5)


def draw(T, nat):
    """The page. nat = the native module (canvas, helpers)."""
    c = nat.canvas
    c.clear((0, 0, 0))
    c.px[:] = bands()
    e = T.engine
    d = e.drums
    pages = T.drum_pages()
    T.drum_tab = min(T.drum_tab, len(pages) - 1)
    page_name, params = pages[T.drum_tab]
    params = params[:8]
    names = getattr(d, "names", None) or []
    voice = T.drum_voice
    vname = (names[voice] if voice < len(names) else "") or str(getattr(d, "title", ""))
    now = nat.time.monotonic()
    active = nat._touched[-1] if nat._touched else None
    if active is None:
        newest = 0.0
        for i, _p in enumerate(params):
            when = T.drumpage.edited.get(i + 1, 0.0)
            if now - when < 1.0 and when > newest:
                active, newest = i, when
    if active is not None and active >= len(params):
        active = None

    # the top line (a message replaces it for a moment), then the name
    top = "PAGE %d/%d" % (T.drum_tab + 1, len(pages))
    if len(pages) > 1:
        top += " " + str(page_name).upper()[:12]
    octave = getattr(T, "octave", 0)
    if octave:
        top += " OCT %+d" % octave
    colr = WHITE
    if T.message and now < T.message_until:
        top, colr = T.message[:24], nat.ACC
    c.text_px(6, 19, top, colr, 16, -1)
    title = vname.upper()
    for px, tr in ((48, -6), (32, -4), (24, -3), (16, -2)):
        if text_width(c.pxfont(px), title, tr) <= W - 6 or px == 16:
            cap = c.pxfont(px).cap_h
            c.text_px(3, 45 + cap // 2, title, WHITE, px, tr)
            break

    # the settings
    texts = []
    for p in params:
        texts.append((str(d.label(p)).upper(), str(d.value_text(p)).upper()))
    key = (id(d), voice, page_name, len(params))
    goal = targets(len(params), active, texts)
    snap = LAST["key"] != key or now - LAST["t"] > 0.4 or LAST["state"] is None or len(LAST["state"]) != len(params)
    if snap or LAST["state"] is None:
        LAST["state"] = [dict() for _ in params]
    dt = min(0.05, max(0.0, now - LAST["t"])) if not snap else 0.0
    step(LAST["state"], goal, dt, snap)
    LAST["key"], LAST["t"] = key, now
    # the big one is drawn last so nothing runs over it
    order = sorted(range(len(params)), key=lambda i: i == active)
    for i in order:
        s, (label, value) = LAST["state"][i], texts[i]
        col = colour.mix(DARK, WHITE, max(0.0, min(1.0, s["t"])))
        room = 90 if active == i else 46
        ls = fit_size(c.pxfont, label, [px for px in (24, 16, 8) if px <= max(8, int(round(s["ls"] / 8.0)) * 8)], room, lambda px: 0)
        if text_width(c.pxfont(ls), label, 0) > room:
            label = label[:max(2, room // 6)]
        sizes = [px for px in (64, 48, 40, 32, 24, 16, 8) if px <= max(8, int(round(s["vs"] / 8.0)) * 8)]
        vs = fit_size(c.pxfont, value, sizes, room, lambda px: -px // 8)
        c.text_px(int(round(s["cx"] - text_width(c.pxfont(ls), label, 0) / 2.0)), int(round(s["lb"])), label, col, ls, 0)
        vtr = -(vs // 8)
        base = s["vm"] + 0.3125 * vs
        c.text_px(int(round(s["cx"] - text_width(c.pxfont(vs), value, vtr) / 2.0)), int(round(base)), value, col, vs, vtr)
