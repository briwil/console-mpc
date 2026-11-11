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
        lv = e.levels[ch] if ch < len(e.levels) else None
        lv = np.asarray(lv) if lv is not None and len(lv) else None
        body = nat.BOX if not muted else (36, 42, 48)
        ink = nat.FG if not muted else nat.DIM
        top = by + 1
        rows_n = BOX_H - 2                                       # the 21 rows inside the outline
        half = (rows_n - 2) // 2
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
            c.rect(a, top, b - a, rows_n, body)
            if lv is not None:
                xs = np.arange(a, b)
                idx = ((t.pos + (xs - mid) / ppb) * tape.RES).astype(int)
                ok = (idx >= 0) & (idx < len(lv))
                h = np.zeros(len(xs), int)
                h[ok] = np.maximum(1, np.rint(np.minimum(1.0, lv[idx[ok]].astype(float)) * half).astype(int))
                rows = np.arange(rows_n - 2)[:, None]
                mask = (np.abs(rows - half) <= h[None, :]) & (h[None, :] > 0)
                sub = c.px[top + 1:top + rows_n - 1, a:b]
                sub[mask[:sub.shape[0], :sub.shape[1]]] = ink
            if xa >= x0 and not spliced_before:
                c.rect(xa, top, 1, rows_n, nat.FG)
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


def draw_focus(T, nat):
    """The zoomed track: one big box in the same style."""
    c = nat.canvas
    c.clear((0, 0, 0))
    e, t = T.engine, T.tape
    n = T.focus.shown
    now = nat.time.monotonic()
    if not e:
        return
    fpb = e.frames_per_beat()
    BX, BW = 32, 285                                             # the big box: x 32 .. 317
    top, bot = 16, 156
    x0, x1 = BX + 1, BX + BW - 1
    mid = x0 + (x1 - x0) // 3
    ppb = (x1 - x0) / (tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR)
    _ruler(c, nat, e, t, x0, x1, mid, ppb, fpb)
    muted = not e.audible(n - 1)
    c.text_px(4, 52, str(n), G[2] if muted else nat.WHITE, 24, 0)
    if T.recording:
        c.rect(6, 2, 9, 9, nat.RED)
    elif T.playing:
        for r in range(9):
            c.rect(6, 2 + r, max(1, 9 - abs(r * 2 - 8)), 1, nat.WHITE)
    else:
        c.frame(6, 2, 9, 9, G[4])
    c.frame(BX, top, BW, bot - top, OUTLINE[n - 1])
    rows_n = bot - top - 2
    centre = rows_n // 2
    half = centre - 3
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
        c.rect(a, top + 1, b - a, rows_n, nat.BOX)
        if lv is not None:
            xs = np.arange(a, b)
            idx = ((t.pos + (xs - mid) / ppb) * tape.RES).astype(int)
            ok = (idx >= 0) & (idx < len(lv))
            h = np.zeros(len(xs), int)
            h[ok] = np.maximum(1, np.rint(np.minimum(1.0, lv[idx[ok]].astype(float)) * half).astype(int))
            rows = np.arange(rows_n)[:, None]
            mask = (np.abs(rows - centre) <= h[None, :]) & (h[None, :] > 0)
            sub = c.px[top + 1:top + 1 + rows_n, a:b]
            sub[mask[:sub.shape[0], :sub.shape[1]]] = nat.DIM if muted else nat.FG
        if xa >= x0:
            c.rect(xa, top + 1, 1, rows_n, nat.FG)
    # light lines down through the box: the grid (thin and dark), the beats, the bars (lightest); they pass behind the waveform
    ink = np.array(nat.DIM if muted else nat.FG, dtype=c.px.dtype)
    marks = {}
    for size, col in ((t.step, (72, 82, 90)), (1.0, (100, 110, 112)), (float(tape.BEATS_PER_BAR), (150, 156, 160))):
        if size * ppb < 4 and size < tape.BEATS_PER_BAR:
            continue                                             # too close together at this zoom
        k = int((t.pos - (mid - x0) / ppb) / size) - 1
        while True:
            x = int(round(mid + (k * size - t.pos) * ppb))
            if x >= x1:
                break
            if x > x0 and k >= 0:
                marks[x] = col
            k += 1
    for x, col in marks.items():
        colm = c.px[top + 1:top + 1 + rows_n, x]
        colm[~(colm == ink).all(axis=1)] = col
        if col[0] < 150:
            c.rect(x, RULER_Y + 7, 1, 3, nat.DIM)                # ... and a tick for it in the ruler at the very top
    for i, r in enumerate(boxes):                                # a splice: an I-beam where two boxes touch
        if i and int(boxes[i - 1][1]) == int(r[0]):
            x = int(round(mid + (r[0] / fpb - t.pos) * ppb))
            if x0 <= x < x1:
                c.rect(x, top, 1, rows_n + 2, nat.WHITE)
                c.rect(x - 3, top, 7, 1, nat.WHITE)
                c.rect(x - 3, bot - 1, 7, 1, nat.WHITE)
    c.rect(mid, RULER_Y, 1, bot - RULER_Y, nat.WHITE)            # the playhead
    # what knobs 1, 2 and the pads change
    stereo = (n - 1) in e.stereo
    try:
        src = str(e.input_text(n - 1))
    except Exception:
        src = "?"
    c.text_px(8, 182, "STEREO" if stereo else "MONO", nat.WHITE, 16, -1)
    c.text_px(130, 182, src[:14], nat.WHITE, 16, -1)
    if here is None:
        c.text_px(8, 208, "NO BOX HERE", G[3], 16, -1)
    else:
        gain = here[3] if len(here) > 3 else 0.0
        fin = (here[4] if len(here) > 4 else 0) / 44100.0
        fout = (here[5] if len(here) > 5 else 0) / 44100.0

        def fade(sec):
            return "OFF" if sec <= 0 else ("%d MS" % round(sec * 1000) if sec < 1 else "%.2g S" % sec)
        c.text_px(8, 208, "GAIN %+.1f" % gain, nat.WHITE, 16, -1)
        c.text_px(130, 208, "IN " + fade(fin), nat.WHITE, 16, -1)
        c.text_px(230, 208, "OUT " + fade(fout), nat.WHITE, 16, -1)
    bpm = "%.0f BPM" % e.bpm
    c.text_px(317 - text_width(c.pxfont(16), bpm, -1), 236, bpm, nat.WHITE, 16, -1)
    if T.message and now < T.message_until:
        c.text_px(8, 236, T.message.upper()[:20], nat.WHITE, 16, -1)
    else:
        c.text_px(8, 236, T.position_text(t.pos)[:14].upper(), nat.WHITE, 16, -1)
