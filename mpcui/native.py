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

    def text(self, x, y, s, c=FG, scale=1):
        for ch in str(s).upper():
            g = _glyph(ch)
            if scale > 1:
                g = np.kron(g, np.ones((scale, scale), bool))
            gh, gw = g.shape
            if 0 <= x and x + gw <= W and 0 <= y and y + gh <= H:
                self.px[y:y + gh, x:x + gw][g] = c
            x += 6 * scale

    @staticmethod
    def width(s, scale=1):
        return len(str(s)) * 6 * scale

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
            c.text(12, top + 16, "M", DIM)
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


def on_tape_page(T, menu):
    """True when Console's own pages.draw would be drawing the tape page (see the end of its if / elif chain)."""
    if menu is not None and (menu.open or menu.kits.open):
        return False
    pop = getattr(T, "input_popup", None)
    if pop and time.monotonic() < pop[0] and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        return False
    if T.fx_page or T.seq_page or T.drum_page or T.inst_page or getattr(T, "song_page", False):
        return False
    return T.focus.track is None


def install(pages):
    """Wraps pages.draw: the original always runs (it draws the Move screen); then, on the tape page, ours replaces it."""
    original = pages.draw
    state = {"errors": 0}

    def draw(f, T, menu=None):
        original(f, T, menu)
        try:
            card = T.pagefx.state() if getattr(T, "pagefx", None) is not None else None
            if card is None and on_tape_page(T, menu) and T.engine:
                draw_tape(T)
                publish()
                return
        except Exception:
            import traceback
            state["errors"] += 1
            if state["errors"] < 4:
                print("native screen error:\n" + traceback.format_exc(), flush=True)
        remove()

    pages.draw = draw
