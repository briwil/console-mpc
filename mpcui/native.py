"""Console's own 320 x 240 screens for the MPC Sample (the Move's screen is 128 x 64, one bit per pixel).

mpc_app.py installs this on top of Console's pages.draw: for a page that has a native version (just the tape for now)
it draws the full-colour frame and hands it to the bridge through /tmp/console-native.rgb ("CNAT", a counter, then
320 x 240 RGB bytes); for every other page it removes that file and the bridge shows the Move's screen scaled up.
Nothing in Console's own files changes. If anything here fails, the page falls back to the Move screen.
"""
import os
import time

import numpy as np

import screen as _screen
import tape

W, H = 320, 240
PATH = os.environ.get("CONSOLE_NATIVE", "/tmp/console-native.rgb")

BG = (16, 20, 24)
BAR = (34, 40, 46)
FG = (242, 235, 221)
MID = (150, 156, 160)
DIM = (90, 98, 106)
ACC = (232, 176, 75)
RED = (214, 72, 72)
GREEN = (110, 200, 130)
LANE = (22, 28, 34)
LANE_SEL = (28, 36, 46)
BOX = (50, 58, 66)
BOX_SEL = (68, 78, 92)
WHITE = (255, 255, 255)

_glyphs = {}


def _glyph(ch):
    g = _glyphs.get(ch)
    if g is None:
        cols = _screen.FONT.get(ch, _screen.FONT["?"] if ch.strip() else _screen.FONT[" "])
        g = np.zeros((7, 5), bool)
        for x, b in enumerate(cols):
            for y in range(7):
                if b & (1 << y):
                    g[y, x] = True
        _glyphs[ch] = g
    return g


_fonts = {}
_masks = {}
FONT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "BarlowCondensed-Medium.ttf")
FONT_CANDIDATES = [os.environ.get("CONSOLE_FONT", ""),
                   "/data/UserData/console/move/fonts/BarlowCondensed-Medium.ttf",
                   "/home/claude/briwil/console-move/move/fonts/BarlowCondensed-Medium.ttf"]


def _font(size):
    if size in _fonts:
        return _fonts[size]
    f = None
    try:
        from PIL import ImageFont
        for path in FONT_CANDIDATES:
            if path and os.path.exists(path):
                f = ImageFont.truetype(path, size)
                top = f.getbbox("H")[1]                          # where the capital letters start below the line's top
                f.cap_pad = top
                break
    except Exception:
        f = None
    _fonts[size] = f
    return f


def _mask(font, s):
    """The text as an anti-aliased alpha array (cached: the same words come up every frame)."""
    key = (id(font), s)
    m = _masks.get(key)
    if m is None:
        from PIL import Image, ImageDraw
        w = int(font.getlength(s)) + 2
        if len(_masks) > 600:
            _masks.clear()
        im = Image.new("L", (max(1, w), font.size + 6), 0)
        ImageDraw.Draw(im).text((0, 0), s, font=font, fill=255)
        m = np.asarray(im, np.float32) / 255.0
        _masks[key] = m
    return m


class Canvas:
    def __init__(self):
        self.px = np.empty((H, W, 3), np.uint8)
        self.clear()

    def clear(self, c=BG):
        self.px[:] = c

    def rect(self, x, y, w, h, c):
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(W, int(x + w)), min(H, int(y + h))
        if x1 > x0 and y1 > y0:
            self.px[y0:y1, x0:x1] = c

    def frame(self, x, y, w, h, c):
        self.rect(x, y, w, 1, c)
        self.rect(x, y + h - 1, w, 1, c)
        self.rect(x, y, 1, h, c)
        self.rect(x + w - 1, y, 1, h, c)

    def text(self, x, y, s, c=FG, scale=1):
        """Smooth text (Barlow Condensed, anti-aliased) if the font file is there, else the 5 x 7 pixel font.
        (x, y) is the top of the capital letters, the same place the pixel font had them; scale 2 = big."""
        s = str(s).upper()
        font = _font(12 if scale == 1 else 22 if scale == 2 else 12 * scale)
        if font is None:
            return self._pixel_text(x, y, s, c, scale)
        a = _mask(font, s)
        if a is None:
            return
        y0 = y - font.cap_pad
        if y0 < 0:
            a, y0 = a[-y0:], 0                                   # (the font's blank top rows may fall off the screen)
        h, w = a.shape
        x1, y1 = min(W, x + w), min(H, y0 + h)
        if x < 0 or x1 <= x or y1 <= y0:
            return
        a = a[:y1 - y0, :x1 - x][..., None]
        region = self.px[y0:y1, x:x1].astype(np.float32)
        self.px[y0:y1, x:x1] = (region * (1 - a) + np.array(c, np.float32) * a).astype(np.uint8)

    def _pixel_text(self, x, y, s, c, scale):
        for ch in s:
            g = _glyph(ch)
            if scale > 1:
                g = np.kron(g, np.ones((scale, scale), bool))
            gh, gw = g.shape
            if 0 <= x and x + gw <= W and 0 <= y and y + gh <= H:
                self.px[y:y + gh, x:x + gw][g] = c
            x += 6 * scale

    @staticmethod
    def width(s, scale=1):
        font = _font(12 if scale == 1 else 22 if scale == 2 else 12 * scale)
        if font is None:
            return len(str(s)) * 6 * scale
        return int(font.getlength(str(s).upper()) + 0.5)

    def bytes(self, seq):
        return b"CNAT" + int(seq & 0xFFFFFFFF).to_bytes(4, "little") + self.px.tobytes()


canvas = Canvas()
_seq = 0
_last = None


def publish():
    global _seq, _last
    data = canvas.px.tobytes()
    if data == _last and os.path.exists(PATH):
        return
    _last = data
    _seq += 1
    tmp = PATH + ".tmp"
    with open(tmp, "wb") as f:
        f.write(b"CNAT" + _seq.to_bytes(4, "little") + data)
    os.replace(tmp, PATH)


def remove():
    global _last
    _last = None
    try:
        os.remove(PATH)
    except OSError:
        pass


# ------------------------------------------------------------------ the tape

TOP_H, RULER_Y, RULER_H, LANES_Y, LANE_H, BOTTOM_H = 10, 11, 11, 24, 25, 12


def draw_tape(T):
    """The tape page: a slim top line, a ruler, all 8 tracks, a slim bottom line."""
    c = canvas
    c.clear()
    e, t = T.engine, T.tape
    # top line
    c.rect(0, 0, W, TOP_H, BAR)
    rec = bool(T.recording)
    state = "REC" if rec else "PLAY" if T.playing else "STOP"
    if e and e.rec_mode == "overdub" and rec:
        state = "ODUB"
    c.text(4, 1, state, RED if rec else ACC if T.playing else MID)
    c.text(40, 1, "%.0f BPM" % (e.bpm if e else 120), MID)
    if getattr(T, "song", None) is not None and T.song.on and T.song.rows:
        c.text(96, 1, "SONG", MID)
    pos = T.position_text(t.pos)[:14]
    c.text(W - 4 - c.width(pos), 1, pos, FG)
    if not e:
        return
    fpb = e.frames_per_beat()
    x0, x1 = 22, W - 4
    mid = x0 + (x1 - x0) // 3                                  # the playhead: a third of the way in, more of what's ahead
    ppb = (x1 - x0) / (tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR)
    # the ruler
    c.rect(x0, RULER_Y, x1 - x0, RULER_H, (28, 34, 40))
    bar = tape.BEATS_PER_BAR
    k = int(t.pos - (mid - x0) / ppb) - 1
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= x1:
            break
        if x >= x0:
            in_bar = k % bar
            if abs(in_bar) < 1e-6:
                c.rect(x, RULER_Y + 3, 1, 8, FG)
                c.text(x + 3, RULER_Y + 3, str(int(k // bar) + 1), MID)
            elif ppb >= 6:
                c.rect(x, RULER_Y + 8, 1, 3, DIM)
        k += 1
    region = e.loop_region()
    if region:                                                  # the loop: an amber bar along the top of the ruler
        a = int(round(mid + (region[0] / fpb - t.pos) * ppb))
        b = int(round(mid + (region[1] / fpb - t.pos) * ppb))
        c.rect(max(x0, a), RULER_Y, max(0, min(x1, b) - max(x0, a)), 2, ACC if e.loop_on else DIM)
    # the tracks
    sel = T.armed - 1
    half = (LANE_H - 5) // 2
    for n in range(8):
        top = LANES_Y + n * LANE_H
        is_sel = n == sel
        if is_sel:
            c.rect(0, top - 1, W, LANE_H, LANE_SEL)
            c.rect(0, top, 18, LANE_H - 3, FG)
            c.text(6, top + 8, str(n + 1), BG)
        else:
            c.text(6, top + 8, str(n + 1), MID)
        if n in e.arm_extra:
            c.rect(19, top + 2, 2, LANE_H - 7, RED)
        muted = not e.audible(n)
        if muted:
            c.text(7, top + 17, "M", DIM)
        c.rect(x0, top + LANE_H - 2, x1 - x0, 1, (40, 46, 52))
        ch = e.chans(n)[0]
        boxes = e.regions[ch]
        lv = e.levels[ch] if ch < len(e.levels) else None
        lv = np.asarray(lv) if lv is not None and len(lv) else None
        body = (BOX_SEL if is_sel else BOX) if not muted else (36, 42, 48)
        ink = (ACC if is_sel else FG) if not muted else DIM
        for i, r in enumerate(boxes):
            xa = int(round(mid + (r[0] / fpb - t.pos) * ppb))
            xb = int(round(mid + (r[1] / fpb - t.pos) * ppb))
            if xb <= x0 or xa >= x1:
                continue
            spliced_before = i > 0 and int(boxes[i - 1][1]) == int(r[0])
            spliced_after = i + 1 < len(boxes) and int(boxes[i + 1][0]) == int(r[1])
            a = max(x0, xa + (2 if spliced_before else 0))
            b = min(x1, xb - (1 if spliced_after else 0))
            if b <= a:
                continue
            c.rect(a, top, b - a, LANE_H - 3, body)
            c.rect(a, top, b - a, 1, MID)
            c.rect(a, top + LANE_H - 4, b - a, 1, MID)
            if lv is not None:
                xs = np.arange(a, b)
                idx = ((t.pos + (xs - mid) / ppb) * tape.RES).astype(int)
                ok = (idx >= 0) & (idx < len(lv))
                h = np.zeros(len(xs), int)
                h[ok] = np.maximum(1, np.rint(np.minimum(1.0, lv[idx[ok]].astype(float)) * half).astype(int))
                rows = np.arange(LANE_H - 5)[:, None]
                mask = (np.abs(rows - half) <= h[None, :]) & (h[None, :] > 0)
                sub = c.px[top + 1:top + LANE_H - 4, a:b]
                sub[mask[:sub.shape[0], :sub.shape[1]]] = ink
            if xa >= x0 and not spliced_before:
                c.rect(xa, top, 1, LANE_H - 3, FG)
            if spliced_after and x0 <= xb < x1:
                c.rect(xb, top - 1, 1, LANE_H - 2, WHITE)
    # the playhead
    c.rect(mid, RULER_Y, 1, LANES_Y - RULER_Y + 8 * LANE_H - 1, WHITE)
    c.rect(mid - 3, RULER_Y - 2, 7, 3, WHITE)
    # the bottom line: a message if there is one, else the selected track
    c.rect(0, H - BOTTOM_H, W, BOTTOM_H, BAR)
    if T.message and time.monotonic() < T.message_until:
        c.text(4, H - 10, T.message[:50], ACC)
        return
    pan = e.pans[sel]
    pan_t = "C" if abs(pan) < 0.05 else ("L%d" % round(-pan * 100) if pan < 0 else "R%d" % round(pan * 100))
    c.text(4, H - 10, "T%d" % T.armed, FG)
    c.text(28, H - 10, "VOL %d" % round(e.volumes[sel] * 100), MID)
    c.text(84, H - 10, "PAN %s" % pan_t, MID)
    c.text(134, H - 10, "STEREO" if sel in e.stereo else "MONO", MID)
    if region and e.loop_on:
        c.text(W - 4 - c.width("LOOP"), H - 10, "LOOP", ACC)


# ------------------------------------------------------------------ the zoomed track

def draw_focus(T):
    """The zoomed track (B3 again): the whole width and most of the height for one track's sound."""
    c = canvas
    c.clear()
    e, t = T.engine, T.tape
    n = T.focus.shown
    c.rect(0, 0, W, TOP_H, BAR)
    rec = bool(T.recording)
    state = "REC" if rec else "PLAY" if T.playing else "STOP"
    c.text(4, 1, state, RED if rec else ACC if T.playing else MID)
    c.text(40, 1, "TRACK %d" % n, FG)
    c.text(100, 1, "%.0f BPM" % (e.bpm if e else 120), MID)
    pos = T.position_text(t.pos)[:14]
    c.text(W - 4 - c.width(pos), 1, pos, FG)
    if not e:
        return
    fpb = e.frames_per_beat()
    x0, x1 = 4, W - 4
    mid = (x0 + x1) // 2
    ppb = (x1 - x0) / (tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR)
    # ruler: ticks on the beats, longer on the half bar and the bar (with its number)
    bar = tape.BEATS_PER_BAR
    c.rect(x0, RULER_Y, x1 - x0, RULER_H, (28, 34, 40))
    k = int(t.pos - (mid - x0) / ppb) - 1
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= x1:
            break
        if x >= x0:
            in_bar = k % bar
            if abs(in_bar) < 1e-6:
                c.rect(x, RULER_Y + 3, 1, 8, FG)
                c.text(x + 3, RULER_Y + 3, str(int(k // bar) + 1), MID)
            elif ppb >= 6 and abs(in_bar - bar / 2) < 1e-6:
                c.rect(x, RULER_Y + 6, 1, 5, MID)
            elif ppb >= 6:
                c.rect(x, RULER_Y + 8, 1, 3, DIM)
        k += 1
    region = e.loop_region()
    if region:
        a = int(round(mid + (region[0] / fpb - t.pos) * ppb))
        b = int(round(mid + (region[1] / fpb - t.pos) * ppb))
        c.rect(max(x0, a), RULER_Y, max(0, min(x1, b) - max(x0, a)), 2, ACC if e.loop_on else DIM)
    # the track
    lane_top, lane_bot = RULER_Y + RULER_H + 3, H - 44
    centre = (lane_top + lane_bot) // 2
    half = (lane_bot - lane_top) // 2 - 3
    c.rect(x0, lane_top, x1 - x0, lane_bot - lane_top, LANE)
    c.rect(x0, centre, x1 - x0, 1, (40, 46, 52))
    ch = e.chans(n - 1)[0]
    boxes = e.regions[ch]
    lv = e.levels[ch] if ch < len(e.levels) else None
    lv = np.asarray(lv) if lv is not None and len(lv) else None
    here = None
    for i, r in enumerate(boxes):
        xa = int(round(mid + (r[0] / fpb - t.pos) * ppb))
        xb = int(round(mid + (r[1] / fpb - t.pos) * ppb))
        if r[0] / fpb <= t.pos < r[1] / fpb:
            here = r
        if xb <= x0 or xa >= x1:
            continue
        a, b = max(x0, xa), min(x1, xb)
        if b <= a:
            continue
        under = r[0] / fpb <= t.pos < r[1] / fpb
        c.rect(a, lane_top, b - a, lane_bot - lane_top, BOX_SEL if under else BOX)
        if lv is not None:
            xs = np.arange(a, b)
            idx = ((t.pos + (xs - mid) / ppb) * tape.RES).astype(int)
            ok = (idx >= 0) & (idx < len(lv))
            h = np.zeros(len(xs), int)
            h[ok] = np.maximum(1, np.rint(np.minimum(1.0, lv[idx[ok]].astype(float)) * half).astype(int))
            rows = np.arange(lane_bot - lane_top)[:, None]
            mask = (np.abs(rows - (centre - lane_top)) <= h[None, :]) & (h[None, :] > 0)
            c.px[lane_top:lane_bot, a:b][mask] = ACC if under else FG
        if xa >= x0:
            c.rect(xa, lane_top, 1, lane_bot - lane_top, FG)
        if xb < x1:
            c.rect(xb - 1, lane_top, 1, lane_bot - lane_top, FG)
    for i, r in enumerate(boxes):                               # a splice: an I-beam where two boxes touch
        if i and int(boxes[i - 1][1]) == int(r[0]):
            x = int(round(mid + (r[0] / fpb - t.pos) * ppb))
            if x0 <= x < x1:
                c.rect(x, lane_top, 1, lane_bot - lane_top, WHITE)
                c.rect(x - 3, lane_top, 7, 1, WHITE)
                c.rect(x - 3, lane_bot - 1, 7, 1, WHITE)
    c.rect(mid, RULER_Y, 1, lane_bot - RULER_Y, WHITE)          # the playhead
    c.rect(mid - 3, RULER_Y - 2, 7, 3, WHITE)
    # the settings: what knobs 1, 2 and 4-6 change
    py = H - 40
    c.rect(0, py, W, 40, BAR)
    stereo = (n - 1) in e.stereo
    try:
        src = e.input_text(n - 1)
    except Exception:
        src = "?"
    c.text(6, py + 5, "K1", DIM); c.text(24, py + 5, "STEREO" if stereo else "MONO", FG)
    c.text(100, py + 5, "K2", DIM); c.text(118, py + 5, "IN " + str(src)[:14], FG)
    c.text(6, py + 18, "BOX", DIM if here is None else ACC)
    if here is None:
        c.text(36, py + 18, "MOVE THE PLAYHEAD ONTO A BOX", DIM)
    else:
        gain = here[3] if len(here) > 3 else 0.0
        fin = (here[4] if len(here) > 4 else 0) / 44100.0
        fout = (here[5] if len(here) > 5 else 0) / 44100.0
        def fade(sec):
            return "OFF" if sec <= 0 else ("%d MS" % round(sec * 1000) if sec < 1 else "%.2g S" % sec)
        c.text(36, py + 18, "K4 GAIN %+.1f DB" % gain, FG)
        c.text(150, py + 18, "K5 IN " + fade(fin), FG)
        c.text(236, py + 18, "K6 OUT " + fade(fout), FG)
    if T.message and time.monotonic() < T.message_until:
        c.rect(0, H - 12, W, 12, ACC)
        c.text(4, H - 10, T.message[:50], BG)


# ------------------------------------------------------------------ the drum sequencer

CELL = (24, 30, 36)
CELL_LINE = (50, 58, 66)
SEL_FILL = (60, 50, 30)


class NotNative(Exception):
    """This view of the page has no native version: the Move's screen (scaled) is shown instead."""


def draw_seq(T):
    """The drum sequencer: the lane's 16 steps as big cells (height = velocity), then the lane's settings (nothing
    selected) or the picked setting of the selected steps (see moveseq.py for how the pads and knobs work)."""
    import sequencer
    c = canvas
    c.clear()
    e = T.engine
    ms, sp, seq = T.mseq, T.seqp, e.seq
    lane = sp.lane
    ln = seq.lane(lane)
    first = ms.first()
    names = getattr(e.drums, "lane_names", None) or []
    name = names[lane] if lane < len(names) else "LANE %d" % (lane + 1)
    pat = "PAT %d" % (seq.current + 1) + (">%d" % (seq.queued + 1) if seq.queued is not None else "")
    selected = ms.held is not None
    knobs = ms.knob_list() if selected else None
    c.rect(0, 0, W, TOP_H, BAR)
    if selected:
        c.text(4, 1, ms.which(), ACC)
        c.text(W - 4 - c.width(name[:14]), 1, name[:14], MID)
    else:
        c.text(4, 1, name[:14], ACC)
        c.text(W - 4 - c.width(pat), 1, pat, MID)
    # the 16 steps
    at = ms.playing_step()
    y = 15
    sel = set(ms.selected) if selected else set()
    for k in range(16):
        i = first + k
        x = 4 + k * 19
        if i >= ln.length:
            c.rect(x + 7, y + 16, 3, 2, DIM)
            continue
        if sequencer.dark(i, sequencer.TRIPLETS):
            c.rect(x + 3, y + 16, 11, 2, DIM)
            continue
        is_sel = i in sel
        c.rect(x, y, 17, 34, SEL_FILL if is_sel else CELL)
        c.frame(x, y, 17, 34, ACC if is_sel else CELL_LINE)
        st = ln.steps[i]
        if st.on:
            v = st.vel if st.vel else sequencer.DEFAULT_VELOCITY
            h = max(3, int(26 * min(127, v) / 127.0))
            c.rect(x + 2, y + 31 - h, 13, h, ACC if is_sel else FG)
        if at is not None and i == at:
            c.rect(x, y + 36, 17, 3, WHITE)
        c.text(x + (5 if i < 9 else 2), y + 41, str(i + 1), FG if (k % 4 == 0) else MID)
    # the lane's pages: 16 steps each; the shown one is lit
    npages = max(1, (ln.length + 15) // 16)
    gap = 4
    seg = (W - 8 - gap * (npages - 1)) // npages
    for p in range(npages):
        c.rect(4 + p * (seg + gap), y + 56, seg, 4, ACC if p == first // 16 else CELL_LINE)
    c.text(4, y + 63, "STEPS %d-%d OF %d" % (first + 1, min(first + 16, ln.length), ln.length), DIM)
    top = 106
    if not selected:
        # the lane's settings: knobs 1-4
        cw = (W - 8 - 3 * 6) // 4
        for i, (label, value, _locked) in enumerate(knobs_lane(ms)[:4]):
            x = 4 + i * (cw + 6)
            c.rect(x, top, cw, 66, CELL)
            c.frame(x, top, cw, 66, CELL_LINE)
            c.text(x + 6, top + 7, str(label)[:10], MID)
            c.text(x + 6, top + 26, str(value)[:6], FG, 2)
            c.text(x + 6, top + 52, "K%d" % (i + 1), DIM)
        hint = "SHIFT + STEPS: SELECT    SHIFT + SEQ: SETTINGS PADS"
    elif knobs:
        label, value, on = knobs[0]
        key = ms.pad_items()[ms.sel][0]
        ct = ms.chance_text(key)
        c.rect(4, top, W - 8, 96, CELL)
        c.frame(4, top, W - 8, 96, ACC)
        c.text(14, top + 8, str(label)[:20], ACC, 2)
        c.text(14, top + 40, "K1", DIM)
        c.text(36, top + 34, str(value)[:8], FG, 3)
        if key == "vel":
            try:
                frac = max(0.0, min(1.0, float(value) / 127.0))
            except ValueError:
                frac = 0.0
            c.rect(150, top + 44, 156, 8, CELL_LINE)
            c.rect(150, top + 44, int(156 * frac), 8, ACC)
        if ct is not None:
            c.text(14, top + 74, "K2 CHANCE  %s" % ct, MID)
        c.text(W - 14 - c.width("SAME PAD AGAIN: OFF" if on else "TURN K1 TO SET IT"), top + 74, "SAME PAD AGAIN: OFF" if on else "TURN K1 TO SET IT", DIM)
        hint = "SEQ: BACK TO THE STEPS    TAP A STEP: DONE"
    else:
        # steps selected, no setting picked: knobs 1-8 are the drum's sound page, turning one locks it on the steps
        items = ms.lock_list()
        c.text(8, top, "SOUND: " + str(ms.page_name())[:18], ACC)
        cw = (W - 8 - 3 * 6) // 4
        for i, (label, value, locked, lockable) in enumerate(items[:8]):
            col, row = i % 4, i // 4
            x, yy = 4 + col * (cw + 6), top + 16 + row * 40
            c.rect(x, yy, cw, 36, SEL_FILL if locked else CELL)
            c.frame(x, yy, cw, 36, ACC if locked else CELL_LINE)
            c.text(x + 5, yy + 5, str(label)[:11], MID if lockable else DIM)
            c.text(x + 5, yy + 18, str(value)[:7], FG if lockable else DIM)
        hint = "PADS (SHIFT + SEQ): STEP SETTINGS    TAP A STEP: DONE"
    c.rect(0, H - 12, W, 12, BAR)
    if T.message and time.monotonic() < T.message_until:
        c.text(4, H - 10, T.message[:50], ACC)
    else:
        c.text(4, H - 10, hint, DIM)


def knobs_lane(ms):
    return ms.knob_list()



def on_tape_page(T, menu):
    """True when Console's own pages.draw would be drawing the tape page (see the end of its if / elif chain)."""
    if menu is not None and (menu.open or menu.kits.open):
        return False
    pop = getattr(T, "input_popup", None)
    if pop and time.monotonic() < pop[0] and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        return False
    if T.fx_page or T.seq_page or T.drum_page or T.inst_page or getattr(T, "song_page", False):
        return False
    return True


def on_seq_page(T, menu):
    """True when pages.draw would draw seq_page for a drum lane (not the synth's sequencer, punch FX or automation)."""
    if menu is not None and (menu.open or menu.kits.open):
        return False
    if T.fx_page or not T.seq_page:
        return False
    if getattr(T, "punch", None) is not None and T.punch.active():
        return False
    if getattr(T, "auto", None) is not None and T.auto.active():
        return False
    try:
        return not T.synth_shown()
    except Exception:
        return False


def install(pages):
    """Wraps pages.draw: the original always runs (it draws the Move screen); then, on the tape page, ours replaces it."""
    original = pages.draw
    state = {"errors": 0}

    def draw(f, T, menu=None):
        original(f, T, menu)
        try:
            card = T.pagefx.state() if getattr(T, "pagefx", None) is not None else None
            if card is None and T.engine and on_tape_page(T, menu):
                (draw_tape if T.focus.track is None else draw_focus)(T)
                publish()
                return
            if card is None and T.engine and on_seq_page(T, menu):
                draw_seq(T)
                publish()
                return
        except Exception:
            import traceback
            state["errors"] += 1
            if state["errors"] < 4:
                print("native screen error:\n" + traceback.format_exc(), flush=True)
        remove()

    pages.draw = draw
