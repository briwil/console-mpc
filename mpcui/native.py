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
_HERE = os.path.dirname(os.path.abspath(__file__))
# Jersey 15 (a pixel font, OFL) is the look; Lato / Carlito / Barlow stay as fallbacks. A pixel font is only sharp at its own
# pixel size and whole multiples of it: Jersey 15's is 18 (so 18 / 36 / 54).
FONT_CANDIDATES = [(os.environ.get("CONSOLE_FONT", ""), 18),
                   (os.path.join(_HERE, "fonts", "Jersey15-Regular.ttf"), 18),
                   (os.path.join(_HERE, "fonts", "Carlito-Bold.ttf"), 13),
                   ("/home/claude/briwil/console-move/move/fonts/BarlowCondensed-SemiBold.ttf", 12)]
_chosen = []


def _font(scale):
    """Text sizes: 1 = Console's own 5 x 7 pixel font (small labels); 2 / 3 / 4 = the pixel font (Jersey 15) at 1x / 2x / 3x of
    its pixel size (medium / big / huge). Returns the font with cap_h (capital height) and cap_pad, or None for size 1."""
    if scale == 1:
        return None
    if scale in _fonts:
        return _fonts[scale]
    f = None
    try:
        from PIL import ImageFont
        for path, base in FONT_CANDIDATES:
            if path and os.path.exists(path):
                f = ImageFont.truetype(path, base * (scale - 1))
                box = f.getbbox("H")
                f.cap_pad, f.cap_h = box[1], box[3] - box[1]
                break
    except Exception:
        f = None
    _fonts[scale] = f
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
        dr = ImageDraw.Draw(im)
        dr.fontmode = "1"                                         # no smoothing: crisp pixels
        dr.text((0, 0), s, font=font, fill=255)
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
        font = _font(scale)
        if font is None:
            return self._pixel_text(x, y, s, c, 1 if scale == 1 else scale - 1)
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

    def text_in(self, x, top, h, s, c=FG, scale=1):
        """Text with its capitals centred in the band top .. top + h."""
        font = _font(scale)
        cap = font.cap_h if font is not None else 7 * (1 if scale == 1 else scale - 1)
        self.text(x, top + (h - cap) // 2, s, c, scale)

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
        font = _font(scale)
        if font is None:
            return len(str(s)) * 6 * (1 if scale == 1 else scale - 1)
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


MODE_PATH = os.environ.get("CONSOLE_PAGEMODE", "/tmp/console-pagemode")
_mode = None


def set_mode(ch):
    """Tells the bridge which page is up: "T" = the tape (the pads are the step buttons there), "O" = anything else."""
    global _mode
    if ch == _mode:
        return
    _mode = ch
    try:
        with open(MODE_PATH + ".tmp", "w") as f:
            f.write(ch)
        os.replace(MODE_PATH + ".tmp", MODE_PATH)
    except OSError:
        pass


def remove():
    global _last
    _last = None
    set_mode("O")
    try:
        os.remove(PATH)
    except OSError:
        pass


# ------------------------------------------------------------------ the tape

TOP_H, RULER_Y, RULER_H, LANES_Y, LANE_H, BOTTOM_H = 16, 17, 14, 33, 24, 15


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
    c.text_in(4, 0, TOP_H, state, RED if rec else ACC if T.playing else MID)
    c.text_in(40, 0, TOP_H, "%.0f BPM" % (e.bpm if e else 120), MID)
    if getattr(T, "song", None) is not None and T.song.on and T.song.rows:
        c.text_in(96, 0, TOP_H, "SONG", MID)
    pos = T.position_text(t.pos)[:14]
    c.text_in(W - 4 - c.width(pos), 0, TOP_H, pos, FG)
    if not e:
        return
    fpb = e.frames_per_beat()
    x0, x1 = 26, W - 4
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
                c.rect(x, RULER_Y + 3, 1, RULER_H - 3, FG)
                c.text_in(x + 3, RULER_Y + 1, RULER_H, str(int(k // bar) + 1), MID)
            elif ppb >= 6:
                c.rect(x, RULER_Y + 10, 1, 4, DIM)
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
            c.rect(0, top, 20, LANE_H - 3, FG)
        muted = not e.audible(n)
        label = str(n + 1) + ("M" if muted else "")
        c.text_in(3, top, LANE_H - 3, label, BG if is_sel else (DIM if muted else MID))
        if n in e.arm_extra:
            c.rect(20, top + 2, 2, LANE_H - 7, RED)
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
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, T.message[:44], ACC)
        return
    pan = e.pans[sel]
    pan_t = "C" if abs(pan) < 0.05 else ("L%d" % round(-pan * 100) if pan < 0 else "R%d" % round(pan * 100))
    c.text_in(4, H - BOTTOM_H, BOTTOM_H, "T%d" % T.armed, FG)
    c.text_in(28, H - BOTTOM_H, BOTTOM_H, "VOL %d" % round(e.volumes[sel] * 100), MID)
    c.text_in(84, H - BOTTOM_H, BOTTOM_H, "PAN %s" % pan_t, MID)
    c.text_in(134, H - BOTTOM_H, BOTTOM_H, "STEREO" if sel in e.stereo else "MONO", MID)
    if region and e.loop_on:
        c.text_in(W - 4 - c.width("LOOP"), H - BOTTOM_H, BOTTOM_H, "LOOP", ACC)


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
    c.text_in(4, 0, TOP_H, state, RED if rec else ACC if T.playing else MID)
    c.text_in(40, 0, TOP_H, "TRACK %d" % n, FG)
    c.text_in(100, 0, TOP_H, "%.0f BPM" % (e.bpm if e else 120), MID)
    pos = T.position_text(t.pos)[:14]
    c.text_in(W - 4 - c.width(pos), 0, TOP_H, pos, FG)
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
                c.rect(x, RULER_Y + 3, 1, RULER_H - 3, FG)
                c.text_in(x + 3, RULER_Y + 1, RULER_H, str(int(k // bar) + 1), MID)
            elif ppb >= 6 and abs(in_bar - bar / 2) < 1e-6:
                c.rect(x, RULER_Y + 7, 1, 7, MID)
            elif ppb >= 6:
                c.rect(x, RULER_Y + 10, 1, 4, DIM)
        k += 1
    region = e.loop_region()
    if region:
        a = int(round(mid + (region[0] / fpb - t.pos) * ppb))
        b = int(round(mid + (region[1] / fpb - t.pos) * ppb))
        c.rect(max(x0, a), RULER_Y, max(0, min(x1, b) - max(x0, a)), 2, ACC if e.loop_on else DIM)
    # the track
    lane_top, lane_bot = RULER_Y + RULER_H + 3, H - 56
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
    py = H - 52
    c.rect(0, py, W, 52, BAR)
    stereo = (n - 1) in e.stereo
    try:
        src = e.input_text(n - 1)
    except Exception:
        src = "?"
    c.text_in(6, py + 3, 16, "K1", DIM); c.text_in(28, py + 3, 16, "STEREO" if stereo else "MONO", FG)
    c.text_in(100, py + 3, 16, "K2", DIM); c.text_in(122, py + 3, 16, "IN " + str(src)[:14], FG)
    c.text_in(6, py + 22, 16, "BOX", DIM if here is None else ACC)
    if here is None:
        c.text_in(38, py + 22, 16, "MOVE THE PLAYHEAD ONTO A BOX", DIM)
    else:
        gain = here[3] if len(here) > 3 else 0.0
        fin = (here[4] if len(here) > 4 else 0) / 44100.0
        fout = (here[5] if len(here) > 5 else 0) / 44100.0
        def fade(sec):
            return "OFF" if sec <= 0 else ("%d MS" % round(sec * 1000) if sec < 1 else "%.2g S" % sec)
        c.text_in(38, py + 22, 16, "FADER GAIN %+.1f DB" % gain, FG)
        c.text_in(150, py + 22, 16, "PAD5 IN " + fade(fin), FG)
        c.text_in(228, py + 22, 16, "PAD6 OUT " + fade(fout), FG)
    if T.message and time.monotonic() < T.message_until:
        c.rect(0, H - BOTTOM_H, W, BOTTOM_H, ACC)
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, T.message[:44], BG)


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
        c.text_in(4, 0, TOP_H, ms.which(), ACC)
        c.text_in(W - 4 - c.width(name[:14]), 0, TOP_H, name[:14], MID)
    else:
        c.text_in(4, 0, TOP_H, name[:14], ACC)
        c.text_in(W - 4 - c.width(pat), 0, TOP_H, pat, MID)
    # the 16 steps
    at = ms.playing_step()
    y = 20
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
        c.text(x + (6 if i < 9 else 2), y + 40, str(i + 1), FG if (k % 4 == 0) else MID)
    cur = getattr(ms, "cur", None)
    if cur is not None and not selected and first <= cur < first + 16 and cur < ln.length:     # the step cursor (a drum hit lays a step here)
        x = 4 + (cur - first) * 19
        c.frame(x - 1, y - 1, 19, 36, WHITE)
        c.frame(x - 2, y - 2, 21, 38, WHITE)
    # the lane's pages: 16 steps each; the shown one is lit
    npages = max(1, (ln.length + 15) // 16)
    gap = 4
    seg = (W - 8 - gap * (npages - 1)) // npages
    for p in range(npages):
        c.rect(4 + p * (seg + gap), y + 56, seg, 4, ACC if p == first // 16 else CELL_LINE)
    c.text(4, y + 64, "STEPS %d-%d OF %d" % (first + 1, min(first + 16, ln.length), ln.length), DIM)
    top = 112
    if not selected:
        # the lane's settings: knobs 1-4
        cw = (W - 8 - 3 * 6) // 4
        for i, (label, value, _locked) in enumerate(knobs_lane(ms)[:4]):
            x = 4 + i * (cw + 6)
            c.rect(x, top, cw, 70, CELL)
            c.frame(x, top, cw, 70, CELL_LINE)
            c.text(x + 6, top + 7, str(label)[:9], MID)
            v = str(value)
            c.text(x + 6, top + 26 if len(v) <= 4 else top + 31, v[:9] if len(v) > 4 else v, FG, 3 if len(v) <= 4 else 1)
            c.text(x + 6, top + 57, ("K%d" % (i + 1)) if i < 3 else "FADER", DIM)
        hint = "WHEEL: MOVE BOX   HIT DRUM: ADD STEP"
    elif knobs:
        label, value, on = knobs[0]
        key = ms.pad_items()[ms.sel][0]
        ct = ms.chance_text(key)
        c.rect(4, top, W - 8, 100, CELL)
        c.frame(4, top, W - 8, 100, ACC)
        c.text(14, top + 8, str(label)[:18], ACC, 3)
        c.text(14, top + 46, "K1", DIM)
        c.text(44, top + 34, str(value)[:6], FG, 4)
        if key == "vel":
            try:
                frac = max(0.0, min(1.0, float(value) / 127.0))
            except ValueError:
                frac = 0.0
            c.rect(150, top + 46, 156, 8, CELL_LINE)
            c.rect(150, top + 46, int(156 * frac), 8, ACC)
        if ct is not None:
            c.text(14, top + 78, "K2 CHANCE  %s" % ct, MID)
        c.text(W - 14 - c.width("SAME PAD AGAIN: OFF" if on else "TURN K1 TO SET IT"), top + 78, "SAME PAD AGAIN: OFF" if on else "TURN K1 TO SET IT", DIM)
        hint = "SEQ: BACK TO STEPS  TAP STEP: DONE"
    else:
        # steps selected, no setting picked: knobs 1-8 are the drum's sound page, turning one locks it on the steps
        items = ms.lock_list()
        c.text(8, top, "SOUND: " + str(ms.page_name())[:18], ACC)
        cw = (W - 8 - 3 * 6) // 4
        for i, (label, value, locked, lockable) in enumerate(items[:8]):
            col, row = i % 4, i // 4
            x, yy = 4 + col * (cw + 6), top + 16 + row * 42
            c.rect(x, yy, cw, 38, SEL_FILL if locked else CELL)
            c.frame(x, yy, cw, 38, ACC if locked else CELL_LINE)
            c.text(x + 5, yy + 4, str(label)[:9], MID if lockable else DIM)
            c.text(x + 5, yy + 19, str(value)[:9], FG if lockable else DIM)
        hint = "SHIFT+SEQ: SETTINGS  TAP STEP: DONE"
    c.rect(0, H - BOTTOM_H, W, BOTTOM_H, BAR)
    if T.message and time.monotonic() < T.message_until:
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, T.message[:44], ACC)
    else:
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, hint, DIM)


def knobs_lane(ms):
    return ms.knob_list()



# ------------------------------------------------------------------ the sound pages

_touched = []                                                    # knob-mode pads held (knob numbers 0-7), the last one wins
MENU_KINDS = ("menu", "onoff", "voice", "vel_target", "lfo_target")


def set_touch(knob, down):
    """Called from the board for the touch notes the bridge sends in knob mode (a pad held = that knob touched)."""
    if knob in _touched:
        _touched.remove(knob)
    if down:
        _touched.append(knob)


def draw_sound(T):
    """An instrument's sound page: its settings as eight cards in knob order, the page names as tabs. A touched knob
    (a pad held in knob mode) or one being turned gets its card lit and its name and value large along the bottom."""
    c = canvas
    c.clear()
    e = T.engine
    d = e.drums
    pages = T.drum_pages()
    T.drum_tab = min(T.drum_tab, len(pages) - 1)
    page_name, params = pages[T.drum_tab]
    names = getattr(d, "names", None) or []
    voice = T.drum_voice
    vname = names[voice] if voice < len(names) else ""
    octave = getattr(T, "octave", 0)
    c.rect(0, 0, W, TOP_H, BAR)
    c.text_in(4, 0, TOP_H, vname[:14], ACC)
    right = ("OCT %+d   " % octave if octave else "") + "%d / %d" % (T.drum_tab + 1, len(pages))
    c.text_in(W - 4 - c.width(right), 0, TOP_H, right, MID)
    # the page names as tabs (scrolled so the shown one is always in view)
    first = max(0, T.drum_tab - 2)
    x = 4
    for i in range(first, len(pages)):
        nm = str(pages[i][0]).upper()[:10]
        w = c.width(nm) + 12
        if x + w > W - 4 and i > T.drum_tab:
            break
        here = i == T.drum_tab
        c.rect(x, 20, w, 16, ACC if here else CELL)
        c.text_in(x + 6, 20, 16, nm, BG if here else MID)
        x += w + 4
    # who is being touched / turned
    now = time.monotonic()
    active = _touched[-1] if _touched else None
    if active is None:
        newest = 0.0
        for i, _p in enumerate(params[:8]):
            when = T.drumpage.edited.get(i + 1, 0.0)
            if now - when < 1.0 and when > newest:
                active, newest = i, when
    # the eight cards
    cw, ch = 73, 62
    for i, p in enumerate(params[:8]):
        col, row = i % 4, i // 4
        x, y = 4 + col * (cw + 6), 42 + row * (ch + 6)
        hot = i == active
        c.rect(x, y, cw, ch, SEL_FILL if hot else CELL)
        c.frame(x, y, cw, ch, ACC if hot else CELL_LINE)
        c.text(x + 6, y + 6, ("%d %s" % (i + 1, d.label(p)))[:11], ACC if hot else MID)
        v = str(d.value_text(p))
        big = len(v) <= 4
        c.text_in(x + 6, y + 18, 28, v[:9], FG, 3 if big else 2)
        if d.kind(p) not in MENU_KINDS:
            frac = max(0.0, min(1.0, d.fraction(p)))
            c.rect(x + 6, y + ch - 10, cw - 12, 4, CELL_LINE)
            c.rect(x + 6, y + ch - 10, int((cw - 12) * frac), 4, ACC if hot else FG)
    c.rect(0, H - BOTTOM_H, W, BOTTOM_H, BAR)
    if active is not None and active < len(params):
        p = params[active]
        py = 174
        c.rect(0, py, W, H - BOTTOM_H - py, (12, 14, 18))
        c.rect(0, py, W, 1, ACC)
        c.text(10, py + 5, "KNOB %d" % (active + 1), MID)
        label = str(d.label(p)).upper()
        value = str(d.value_text(p))
        c.text(10, py + 13, label[:18], ACC, 3 if len(label) <= 9 else 2)
        c.text(W - 10 - c.width(value[:8], 3), py + 13, value[:8], FG, 3)
        if d.kind(p) not in MENU_KINDS:
            frac = max(0.0, min(1.0, d.fraction(p)))
            c.rect(10, py + 42, W - 20, 4, CELL_LINE)
            c.rect(10, py + 42, int((W - 20) * frac), 4, ACC)
    if T.message and time.monotonic() < T.message_until:
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, T.message[:44], ACC)
    else:
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, "< > OR WHEEL: PAGES   PAD + ENCODER: KNOB", DIM)


def on_sound_page(T, menu):
    """True when pages.draw would draw sound_page itself (not the sample browser, LFO / insert / arp pages or presets)."""
    if menu is not None and (menu.open or menu.kits.open):
        return False
    if T.fx_page or T.seq_page or not T.drum_page:
        return False
    try:
        if T.punch.active() or T.auto.active() or T.sbrowse.active or T.mlfo.active():
            return False
        if getattr(T, "presets", None) is not None and T.presets.on_page():
            return False
        return T.engine is not None and T.engine.drums is not None
    except Exception:
        return False


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


# ------------------------------------------------------------------ the mixer

def on_mixer_page(T, menu):
    if menu is not None and (menu.open or menu.kits.open):
        return False
    return T.fx_page == "mixer" and T.engine is not None


def draw_mixer(T):
    """MIXER: 8 strips with the instrument, level fader, level number, pan and a MUTE tag."""
    from console import mix_pan_text
    c = canvas
    c.clear()
    e = T.engine
    c.rect(0, 0, W, TOP_H, BAR)
    c.text_in(4, 0, TOP_H, "MIXER", ACC)
    c.text_in(W - 4 - c.width("SHIFT: PAN"), 0, TOP_H, "SHIFT: PAN", MID)
    for i in range(8):
        x, y, w, h = 4 + i * 39, 22, 35, 172
        mid = e.slots[i]
        muted = bool(mid) and i in e.slot_mutes
        c.rect(x, y, w, h, CELL)
        c.frame(x, y, w, h, CELL_LINE)
        c.text(x + 3, y + 4, str(i + 1), ACC if mid else DIM)
        if not mid:
            c.text(x + 3, y + 14, "-", DIM)
            continue
        c.text(x + 3, y + 14, str(T.instp.title(mid)).upper()[:5], MID)
        lvl = max(0.0, min(1.0, float(e.inst_levels[i])))
        fx, fy, fh = x + 5, y + 30, 92
        top = int(fh * (1 - lvl))
        c.rect(fx, fy, 10, fh, CELL_LINE)
        c.rect(fx, fy + top, 10, fh - top, DIM if muted else ACC)
        c.text(x + 3, y + 128, "%d" % round(lvl * 100), DIM if muted else FG)
        c.text(x + 3, y + 142, mix_pan_text(e.inst_pans[i]), MID)
        if muted:
            c.rect(x + 3, y + 156, 29, 10, (60, 30, 30))
            c.text(x + 6, y + 157, "MUTE", FG)
        else:
            c.rect(x + 3, y + 156, 29, 10, CELL_LINE)
    c.rect(0, H - BOTTOM_H, W, BOTTOM_H, BAR)
    if T.message and time.monotonic() < T.message_until:
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, T.message[:44], ACC)
    else:
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, "KNOBS: LEVEL   PAD: MUTE   SHIFT+PAD: SOLO", DIM)


# ------------------------------------------------------------------ instruments list, project menu, settings

def on_inst_list(T, menu):
    if menu is not None and (menu.open or menu.kits.open):
        return False
    if T.fx_page or T.seq_page or T.drum_page or not T.inst_page or T.engine is None:
        return False
    return T.instp.mode is None                                  # (the picker, and change / remove / show-hide: the Move screen)


def _top(title, right=""):
    c = canvas
    c.clear()
    c.rect(0, 0, W, TOP_H, BAR)
    c.text_in(4, 0, TOP_H, title, ACC)
    if right:
        c.text_in(W - 4 - c.width(right), 0, TOP_H, right, MID)


def _bottom(T, hint, msg=""):
    c = canvas
    c.rect(0, H - BOTTOM_H, W, BOTTOM_H, BAR)
    if msg:
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, msg[:44], ACC)
    elif T is not None and T.message and time.monotonic() < T.message_until:
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, T.message[:44], ACC)
    else:
        c.text_in(4, H - BOTTOM_H, BOTTOM_H, hint, DIM)


def draw_inst_list(T):
    c = canvas
    e, ip = T.engine, T.instp
    names = {}
    try:
        import instpage
        names = {m: title for m, title in instpage.machines()}
    except Exception:
        pass
    _top("INSTRUMENTS", "8 SLOTS")
    for i in range(8):
        y = 22 + i * 24
        mid = e.slots[i]
        on = i == ip.row
        name = str(names.get(mid, mid) or "-").upper() if mid else "-"
        c.rect(4, y, W - 8, 21, SEL_FILL if on else CELL)
        c.frame(4, y, W - 8, 21, ACC if on else CELL_LINE)
        c.text_in(12, y, 21, str(i + 1), ACC if on else MID)
        c.text_in(34, y, 21, name[:18], FG if mid else DIM, 2)
        if not mid:
            c.text_in(W - 12 - c.width("EMPTY"), y, 21, "EMPTY", DIM)
        elif i in e.slot_mutes:
            c.rect(W - 62, y + 4, 50, 13, (60, 30, 30))
            c.text_in(W - 57, y + 4, 13, "MUTE", FG)
    _bottom(T, "WHEEL: PICK  PUSH: OPEN  PAD: MUTE")


def on_project_menu(menu):
    return menu is not None and menu.open and getattr(menu, "mode", "") == "list"


def draw_project_menu(T, menu):
    import menu as menu_mod
    c = canvas
    shift = bool(getattr(T, "shift_held", lambda: False)())
    e = menu.engine
    _top(((e.song or "UNTITLED") if e else "DEMO").upper()[:21], "PROJECT")
    for i, (label, _) in enumerate(menu_mod.ITEMS):
        text = {"NEW": "DELETE PROJECT" if shift else "NEW PROJECT", "SAVE": "RENAME PROJECT" if shift else "SAVE PROJECT",
                "LOAD": "LOAD PROJECT", "SETTINGS": "SETTINGS"}[label]
        y = 30 + i * 44
        on = i == menu.choice
        c.rect(12, y, W - 24, 38, SEL_FILL if on else CELL)
        c.frame(12, y, W - 24, 38, ACC if on else CELL_LINE)
        c.text_in(24, y, 38, text, ACC if on else FG, 3 if len(text) <= 14 else 2)
    _bottom(T, "SHIFT + PUSH: DELETE / RENAME", str(getattr(menu, "msg", "") or "").upper())


def on_settings(menu):
    return menu is not None and menu.open and getattr(menu, "mode", "") == "settings"


def draw_settings(T, menu):
    import menu as menu_mod
    c = canvas
    names = {"TIMESIG": "TIME SIGNATURE", "FORMAT": "EXPORT FORMAT", "UPDATE": "SOFTWARE UPDATE", "SCREEN": "EXTERNAL SCREEN"}
    _top("SETTINGS", "TURN, PUSH: DONE" if menu.editing else "PUSH: CHANGE IT")
    rows = menu_mod.SETTINGS
    fit = 6
    first = max(0, min(menu.row - fit + 1, len(rows) - fit)) if len(rows) > fit else 0
    for i, what in enumerate(rows):
        if not first <= i < first + fit:
            continue
        y = 22 + (i - first) * 30
        on = i == menu.row
        full = str(menu.setting_text(what) or "")
        short = full.split("  ")[0].split(": ")[0].upper()[:14]
        label = names.get(what, menu_mod.LABELS.get(what, what))
        c.rect(4, y, W - 8, 27, SEL_FILL if on else CELL)
        c.frame(4, y, W - 8, 27, ACC if on else CELL_LINE)
        c.text_in(12, y, 27, label, ACC if on else MID)
        vx = W - 12 - c.width(short, 2)
        if on and menu.editing:
            c.rect(vx - 5, y + 3, c.width(short, 2) + 10, 21, ACC)
            c.text_in(vx, y, 27, short, BG, 2)
        else:
            c.text_in(vx, y, 27, short, FG, 2)
    full = str(menu.setting_text(rows[menu.row]) or "")
    msg = str(getattr(menu, "msg", "") or "") or (menu.update_message() if rows[menu.row] == "UPDATE" else "") or full
    c.rect(0, 206, W, 19, (12, 14, 18))
    c.text_in(6, 206, 19, msg.upper()[:44], MID)
    _bottom(None, "WHEEL: PICK ROW  PUSH: EDIT VALUE")


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
                set_mode("T")
                return
            if card is None and T.engine and on_project_menu(menu):
                draw_project_menu(T, menu)
                publish()
                set_mode("O")
                return
            if card is None and T.engine and on_settings(menu):
                draw_settings(T, menu)
                publish()
                set_mode("O")
                return
            if card is None and T.engine and on_inst_list(T, menu):
                draw_inst_list(T)
                publish()
                set_mode("T")
                return
            if card is None and T.engine and on_mixer_page(T, menu):
                draw_mixer(T)
                publish()
                set_mode("T")
                return
            if card is None and T.engine and on_sound_page(T, menu):
                draw_sound(T)
                publish()
                set_mode("O")
                return
            if card is None and T.engine and on_seq_page(T, menu):
                draw_seq(T)
                publish()
                set_mode("O")
                return
        except Exception:
            import traceback
            state["errors"] += 1
            if state["errors"] < 4:
                print("native screen error:\n" + traceback.format_exc(), flush=True)
        remove()

    pages.draw = draw
