"""The tape page, designed by Brian (his SVG): a strip of track numbers on the left, the 8 tracks as outlined boxes each in its own
green, the ruler along the top, a grey bar under the tracks, and the message / tempo along the bottom. The waveforms keep the old look
(cream on slate)."""
import numpy as np

import colour
import tape
from soundpage import text_width

G = colour.GREENS
OUTLINE = [G[2], G[4], G[5], G[3], G[4], G[5], G[3], G[5]]       # each track's outline colour (from the design)
BOX_Y = [16, 41, 66, 92, 117, 142, 167, 192]                      # the top of each track's box
BOX_H = 23
X_BOX, W_BOX = 22, 295                                           # the boxes span x 22 .. 317
BAR_Y, BAR_H = 217, 4                                            # the grey bar under the tracks
GREY = (0x95, 0x9B, 0x87)
BASE = 236                                                       # baseline of the bottom text
RULER_Y, RULER_H = 1, 10


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
    for n in range(8):
        by = BOX_Y[n]
        is_sel = n == sel
        muted = not e.audible(n)
        c.frame(X_BOX, by, W_BOX, BOX_H, nat.WHITE if is_sel else OUTLINE[n])
        c.text_px(8, 33 + 25 * n, str(n + 1), G[2] if muted else nat.WHITE, 16, 0)
        if n in e.arm_extra:
            c.rect(18, by + 3, 3, BOX_H - 6, nat.RED)
        ch = e.chans(n)[0]
        boxes = e.regions[ch]
        ink = G[1] if muted else (G[6] if is_sel else OUTLINE[n])     # recorded audio: a plain bar in the track's green
        top = by + 1
        rows_n = BOX_H - 2                                       # the 21 rows inside the outline
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
            c.rect(a, top + 6, b - a, rows_n - 12, ink)
            if spliced_after and x0 <= xb < x1:
                c.rect(xb, top - 1, 1, rows_n + 2, nat.WHITE)

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


def _reel(c, cx, cy, R, wf, rot):
    """A tape reel at (cx, cy): the flange (rim + 3 rotating spokes), and tape wound to fraction wf (0..1)."""
    hub = 9
    px = c.px
    px[_disc(cx, cy, 0, R)] = (18, 22, 16)                          # the flange face (very dark)
    diskR = hub + (R - hub - 2) * max(0.0, min(1.0, wf))
    if diskR > hub:
        px[_disc(cx, cy, hub, diskR)] = G[3]                        # the tape wound on (dark green)
    for k in range(3):                                              # three light spoke-windows, turning
        a = rot + k * 2 * np.pi / 3
        px[_disc(cx, cy, hub + 1, R - 2, a - 0.32, a + 0.32)] = G[5]
    px[_disc(cx, cy, R - 1, R + 0.6)] = G[6]                        # the rim
    px[_disc(cx, cy, 0, hub)] = G[6]                                # the hub
    px[_disc(cx, cy, 0, 2.2)] = (10, 12, 10)                        # the spindle hole


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

    # the two reels: the left empties as the right fills
    ly, R = 118, 50
    lx, rx = 82, 238
    _reel(c, lx, ly, R, 1.0 - frac, rot)
    _reel(c, rx, ly, R, frac, rot)

    # the play / pause / record glyph, between the reels
    gx, gy = 160, 104
    if T.recording:
        c.px[_disc(gx, gy, 0, 8)] = nat.RED
    elif T.playing:
        for r in range(13):
            c.rect(gx - 6, gy - 6 + r, max(1, 12 - abs(r * 2 - 12)) // 2 + 1, 1, nat.WHITE)
    else:
        c.rect(gx - 6, gy - 7, 4, 14, nat.WHITE)
        c.rect(gx + 2, gy - 7, 4, 14, nat.WHITE)

    # the tape path: from the bottom of each reel, dipping to a head in the middle
    hy = ly + R + 14
    c.rect(lx, ly + R - 1, 1, 2, G[5])
    c.rect(rx, ly + R - 1, 1, 2, G[5])
    for xa, xb in ((lx, gx), (gx, rx)):
        steps = abs(xb - xa)
        for s2 in range(steps):
            fx = s2 / steps
            x = int(round(xa + (xb - xa) * fx))
            y = int(round((ly + R) + (hy - (ly + R)) * fx)) if xa < gx else int(round(hy + ((ly + R) - hy) * fx))
            c.rect(x, y, 1, 1, G[4])
    c.px[_disc(gx, hy, 0, 5)] = G[6]                                # the capstan / head
    c.px[_disc(gx, hy, 0, 2)] = (10, 12, 10)

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
