"""The tape page, designed by Brian (his SVG): a strip of track numbers on the left, the 8 tracks as outlined boxes each in its own
green, the ruler along the top, a grey bar under the tracks, and the message / tempo along the bottom. The waveforms keep the old look
(cream on slate)."""
import numpy as np

import colour
import tape
from soundpage import text_width

G = colour.GREENS
OUTLINE = [G[2], G[4], G[5], G[3], G[4], G[5], G[3], G[5]]       # each track's outline colour (from the design)
SHOWN = 4                                                         # tracks on screen at once (Shift + the wheel scrolls through the 8)
BOX_Y = [14, 64, 114, 164]                                        # the top of each row's box
BOX_H = 47
X_BOX, W_BOX = 22, 295                                           # the boxes span x 22 .. 317
BAR_Y, BAR_H = 217, 4                                            # the grey bar under the tracks
GREY = (0x95, 0x9B, 0x87)
BASE = 236                                                       # baseline of the bottom text
RULER_Y, RULER_H = 1, 10


def top_row(T):
    """The first track on screen: it follows the selected track when that changes, Shift + the wheel moves it."""
    sel = T.armed - 1
    top = getattr(T, "_tape_top", 0)
    if getattr(T, "_tape_last", None) != sel:
        if sel < top:
            top = sel
        elif sel > top + SHOWN - 1:
            top = sel - SHOWN + 1
        T._tape_last = sel
    top = max(0, min(8 - SHOWN, top))
    T._tape_top = top
    return top


def scroll(T, d):
    """Shift + the wheel: the view moves a track a click."""
    T._tape_last = T.armed - 1
    T._tape_top = max(0, min(8 - SHOWN, getattr(T, "_tape_top", 0) + (1 if d > 0 else -1)))


def draw(T, nat):
    c = nat.canvas
    c.clear((0, 0, 0))
    e, t = T.engine, T.tape
    now = nat.time.monotonic()
    if not e:
        return
    W = nat.W
    sel = T.armed - 1
    fpb = e.frames_per_beat()
    x0, x1 = X_BOX + 1, X_BOX + W_BOX - 1
    mid = x0 + (x1 - x0) // 3                                    # the playhead: a third of the way in
    ppb = (x1 - x0) / (tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR)

    # what the tape is doing (top left, above the track numbers)
    if T.recording:
        c.rect(6, 2, 9, 9, nat.RED)
    elif T.playing:
        for r in range(9):
            w = 9 - abs(2 * r - 8)
            c.rect(6, 2 + r, max(1, w), 1, nat.WHITE)
    else:
        c.frame(6, 2, 9, 9, G[4])

    # the ruler
    c.rect(x0, RULER_Y, x1 - x0, RULER_H, nat.BOX)
    bar = tape.BEATS_PER_BAR
    k = int(t.pos - (mid - x0) / ppb) - 1
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= x1:
            break
        if x >= x0:
            in_bar = k % bar
            if abs(in_bar) < 1e-6:
                c.rect(x, RULER_Y + 2, 1, RULER_H - 2, nat.MID)
                c.text_px(x + 3, RULER_Y + 8, str(int(k // bar) + 1), nat.MID, 8, 0)
            elif ppb >= 6:
                c.rect(x, RULER_Y + 7, 1, 3, nat.DIM)
        k += 1
    region = e.loop_region()
    if region:                                                   # the loop: a bar along the top of the ruler
        a = int(round(mid + (region[0] / fpb - t.pos) * ppb))
        b = int(round(mid + (region[1] / fpb - t.pos) * ppb))
        c.rect(max(x0, a), RULER_Y, max(0, min(x1, b) - max(x0, a)), 2, G[6] if e.loop_on else G[3])

    # the tracks
    top_n = top_row(T)
    for row in range(SHOWN):
        n = top_n + row
        by = BOX_Y[row]
        is_sel = n == sel
        muted = not e.audible(n)
        c.frame(X_BOX, by, W_BOX, BOX_H, nat.WHITE if is_sel else OUTLINE[n])
        c.text_px(2, by + BOX_H // 2 + 9, str(n + 1), G[2] if muted else nat.WHITE, 24, 0)
        if n in e.arm_extra:
            c.rect(18, by + 6, 3, BOX_H - 12, nat.RED)
        ch = e.chans(n)[0]
        boxes = e.regions[ch]
        ink = G[1] if muted else (G[6] if is_sel else OUTLINE[n])     # recorded audio: a plain bar in the track's green
        top = by + 1
        rows_n = BOX_H - 2                                       # the rows inside the outline
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
            c.rect(a, top + 11, b - a, rows_n - 22, ink)
            if spliced_after and x0 <= xb < x1:
                c.rect(xb, top - 1, 1, rows_n + 2, nat.WHITE)

    # the scroll bar (right edge): which 4 of the 8 tracks are showing
    c.rect(318, BOX_Y[0], 2, BOX_Y[-1] + BOX_H - BOX_Y[0], G[1])
    span = BOX_Y[-1] + BOX_H - BOX_Y[0]
    c.rect(318, BOX_Y[0] + span * top_n // 8, 2, span * SHOWN // 8, G[5])

    # the playhead
    c.rect(mid, RULER_Y, 1, BAR_Y - RULER_Y - 1, nat.WHITE)
    # the grey bar under the tracks
    c.rect(X_BOX, BAR_Y, W_BOX + 2, BAR_H, GREY)

    # the bottom line: the message (or the selected track), and the tempo
    bpm = "%.0f BPM" % e.bpm
    c.text_px(317 - text_width(c.pxfont(16), bpm, -1), BASE, bpm, nat.WHITE, 16, -1)
    room = 317 - text_width(c.pxfont(16), bpm, -1) - 20 - 8
    if T.message and now < T.message_until:
        txt, col = T.message.upper(), nat.WHITE
    else:
        pan = e.pans[sel]
        pan_t = "C" if abs(pan) < 0.05 else ("L%d" % round(-pan * 100) if pan < 0 else "R%d" % round(pan * 100))
        txt, col = "T%d  VOL %d  PAN %s" % (T.armed, round(e.volumes[sel] * 100), pan_t), nat.WHITE
        if getattr(T, "song", None) is not None and T.song.on and T.song.rows:
            txt = "SONG  " + txt
    px = 16 if text_width(c.pxfont(16), txt, -1) <= room else 8
    c.text_px(20, BASE, txt[:60 if px == 8 else 40], col, px, -1 if px == 16 else 0)


def _ruler(c, nat, e, t, x0, x1, mid, ppb, fpb):
    c.rect(x0, RULER_Y, x1 - x0, RULER_H, nat.BOX)
    bar = tape.BEATS_PER_BAR
    k = int(t.pos - (mid - x0) / ppb) - 1
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= x1:
            break
        if x >= x0:
            in_bar = k % bar
            if abs(in_bar) < 1e-6:
                c.rect(x, RULER_Y + 2, 1, RULER_H - 2, nat.MID)
                c.text_px(x + 3, RULER_Y + 8, str(int(k // bar) + 1), nat.MID, 8, 0)
            elif ppb >= 6:
                c.rect(x, RULER_Y + 7, 1, 3, nat.DIM)
        k += 1
    region = e.loop_region()
    if region:
        a = int(round(mid + (region[0] / fpb - t.pos) * ppb))
        b = int(round(mid + (region[1] / fpb - t.pos) * ppb))
        c.rect(max(x0, a), RULER_Y, max(0, min(x1, b) - max(x0, a)), 2, G[6] if e.loop_on else G[3])


_GY = None
_GX = None


def _grids():
    global _GY, _GX
    if _GY is None:
        import numpy as _np
        _GY, _GX = _np.ogrid[0:240, 0:320]
    return _GY, _GX


def _disc(cx, cy, r0, r1, a0=None, a1=None):
    """A boolean mask: the ring r0..r1 around (cx, cy), optionally only the wedge of angle a0..a1 (radians)."""
    gy, gx = _grids()
    dy = gy - cy
    dx = gx - cx
    d2 = dx * dx + dy * dy
    m = (d2 >= r0 * r0) & (d2 <= r1 * r1)
    if a0 is not None:
        ang = np.arctan2(dy, dx) % (2 * np.pi)
        a0 %= 2 * np.pi
        a1 %= 2 * np.pi
        m &= (ang >= a0) & (ang <= a1) if a0 <= a1 else ((ang >= a0) | (ang <= a1))
    return m


OLIVE = (0x67, 0x6F, 0x58)                                      # from Brian's reel drawing


def _line(c, xa, ya, xb, yb, col):
    n = int(max(abs(xb - xa), abs(yb - ya))) + 1
    xs = np.rint(np.linspace(xa, xb, n)).astype(int)
    ys = np.rint(np.linspace(ya, yb, n)).astype(int)
    ok = (xs >= 0) & (xs < 320) & (ys >= 0) & (ys < 240)
    c.px[ys[ok], xs[ok]] = col


def _reel(c, cx, cy, wf, rot):
    """A reel as Brian drew it: a thin white ring, the tape as a white disc (it shrinks as the tape runs off: wf 0..1), three olive
    windows (they turn), an olive ring round the white hub. Returns the radius of the tape pack."""
    px = c.px
    white = (255, 255, 255)
    pack = 17 + (36.3 - 17) * max(0.0, min(1.0, wf))
    px[_disc(cx, cy, 41.2, 42.3)] = white                           # the outer ring
    px[_disc(cx, cy, 0, pack)] = white                              # the tape
    for k in range(3):                                              # the three windows
        a = rot - np.pi / 2 + k * 2 * np.pi / 3
        px[_disc(cx, cy, 17.5, 33, a - 0.24, a + 0.24)] = OLIVE
    px[_disc(cx, cy, 0, 14.7)] = OLIVE                              # the hub: an olive ring, white inside, an olive dot
    px[_disc(cx, cy, 0, 12.3)] = white
    px[_disc(cx, cy, 0, 1.5)] = OLIVE
    return pack


def _time(beats, bpm):
    sec = beats / max(1e-6, bpm) * 60.0
    m = int(sec // 60)
    s2 = int(sec % 60)
    cc = int((sec - int(sec)) * 100)
    return "%d:%02d:%02d" % (m, s2, cc)


def draw_focus(T, nat):
    """The zoomed track as a reel-to-reel tape deck, in Console's own look (greens, Silkscreen)."""
    global nat_white
    nat_white = nat.WHITE
    c = nat.canvas
    c.clear((0, 0, 0))
    e, t = T.engine, T.tape
    n = T.focus.shown
    now = nat.time.monotonic()
    if not e:
        return
    fpb = e.frames_per_beat()
    muted = not e.audible(n - 1)
    frac = max(0.0, min(1.0, t.pos / t.total_beats)) if t.total_beats else 0.0
    rot = t.pos * 1.7                                               # the reels turn as the tape moves (still when stopped)

    # the track number, big, top-left
    c.text_px(6, 40, str(n), G[2] if muted else nat.WHITE, 32, 0)
    # the time counter, top-centre
    tc = _time(t.pos, e.bpm)
    c.text_px(160 - text_width(c.pxfont(24), tc, -2) // 2, 36, tc, nat.WHITE, 24, -2)

    # the two reels (Brian's drawing): the left empties as the right fills
    ly, lx, rx = 104, 87, 233
    pl = _reel(c, lx, ly, 1.0 - frac, rot)
    pr = _reel(c, rx, ly, frac, rot)

    # the play / pause / record glyph, between the reels
    gx, gy = 160, 100
    if T.recording:
        c.px[_disc(gx, gy, 0, 7)] = nat.RED
    elif T.playing:
        for r in range(13):
            c.rect(gx - 5, gy - 6 + r, 7 - abs(r - 6), 1, nat.WHITE)
    else:
        c.rect(gx - 6, gy - 7, 4, 14, nat.WHITE)
        c.rect(gx + 2, gy - 7, 4, 14, nat.WHITE)

    # the tape path, as drawn: off each reel's pack, down under a white guide, over a roller, sagging to the middle
    white = (255, 255, 255)
    gyd, ryr = ly + 54, ly + 52                                     # the guides (dots) and the rollers (rings)
    for side, cx, pk in ((-1, lx, pl), (1, rx, pr)):
        dotx, rolx = cx - side * 1, cx - side * 27
        _line(c, cx + side * pk * 0.75, ly + pk * 0.66, dotx + side * 2, gyd + 2, white)
        _line(c, dotx + side * 2, gyd + 2, dotx - side * 2, gyd + 3, white)
        _line(c, dotx - side * 2, gyd + 3, rolx, ryr - 6, white)
        _line(c, rolx, ryr - 6, rolx - side * 14, ryr - 6, white)
        _line(c, rolx - side * 14, ryr - 6, gx, ryr + 3, white)
        c.px[_disc(dotx, gyd, 0, 4)] = white
        c.px[_disc(rolx, ryr, 0, 5.5)] = (0, 0, 0)
        c.px[_disc(rolx, ryr, 4.9, 5.9)] = white

    # the bottom strip: this track's recording as a bar, with a ruler and the playhead
    sx0, sx1, sy = 8, 312, 196
    mid = sx0 + (sx1 - sx0) // 3
    ppb = (sx1 - sx0) / (tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR)
    bar = tape.BEATS_PER_BAR                                        # bar numbers just above the strip
    k = int(t.pos - (mid - sx0) / ppb) - 1
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= sx1:
            break
        if x >= sx0 and k % bar == 0 and k >= 0:
            c.rect(x, sy - 6, 1, 4, G[4])
            c.text_px(x + 3, sy - 3, str(int(k // bar) + 1), G[4], 8, 0)
        k += 1
    bar_col = G[1] if muted else OUTLINE[n - 1]
    ch = e.chans(n - 1)[0]
    boxes = e.regions[ch]
    here = None
    c.frame(sx0, sy, sx1 - sx0, 20, G[3])
    for r in boxes:
        xa = int(round(mid + (r[0] / fpb - t.pos) * ppb))
        xb = int(round(mid + (r[1] / fpb - t.pos) * ppb))
        if r[0] / fpb <= t.pos < r[1] / fpb:
            here = r
        if xb <= sx0 or xa >= sx1:
            continue
        a, b = max(sx0 + 1, xa), min(sx1 - 1, xb)
        if b > a:
            c.rect(a, sy + 5, b - a, 10, bar_col)
    c.rect(mid, sy - 1, 1, 22, nat.WHITE)                           # the playhead

    # one compact line of the box's settings (what knobs 4-6 edit)
    stereo = (n - 1) in e.stereo
    try:
        src = str(e.input_text(n - 1))
    except Exception:
        src = "?"
    c.text_px(8, 232, ("STEREO" if stereo else "MONO") + "  " + src[:10], G[5], 16, -1)
    if here is not None:
        gain = here[3] if len(here) > 3 else 0.0
        fin = (here[4] if len(here) > 4 else 0) / 44100.0
        fout = (here[5] if len(here) > 5 else 0) / 44100.0

        def fade(sec):
            return "OFF" if sec <= 0 else ("%dMS" % round(sec * 1000) if sec < 1 else "%.2gS" % sec)
        txt = "G%+.1f  I%s O%s" % (gain, fade(fin), fade(fout))
        c.text_px(312 - text_width(c.pxfont(16), txt, -1), 232, txt, nat.WHITE, 16, -1)
    if T.message and now < T.message_until:
        c.rect(0, 220, 320, 20, (0, 0, 0))
        c.text_px(8, 236, T.message.upper()[:22], nat.WHITE, 16, -1)
