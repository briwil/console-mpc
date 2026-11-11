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
    c.rect(x0, RULER_Y, x1 - x0, RULER_H, G[0])
    bar = tape.BEATS_PER_BAR
    k = int(t.pos - (mid - x0) / ppb) - 1
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= x1:
            break
        if x >= x0:
            in_bar = k % bar
            if abs(in_bar) < 1e-6:
                c.rect(x, RULER_Y + 2, 1, RULER_H - 2, nat.WHITE)
                c.text_px(x + 3, RULER_Y + 8, str(int(k // bar) + 1), G[6], 8, 0)
            elif ppb >= 6:
                c.rect(x, RULER_Y + 7, 1, 3, G[4])
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
        body = (nat.BOX_SEL if is_sel else nat.BOX) if not muted else (36, 42, 48)
        ink = (G[6] if is_sel else nat.FG) if not muted else nat.DIM
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
        txt, col = T.message.upper(), nat.ACC
    else:
        pan = e.pans[sel]
        pan_t = "C" if abs(pan) < 0.05 else ("L%d" % round(-pan * 100) if pan < 0 else "R%d" % round(pan * 100))
        txt, col = "T%d  VOL %d  PAN %s" % (T.armed, round(e.volumes[sel] * 100), pan_t), nat.WHITE
        if getattr(T, "song", None) is not None and T.song.on and T.song.rows:
            txt = "SONG  " + txt
    px = 16 if text_width(c.pxfont(16), txt, -1) <= room else 8
    c.text_px(20, BASE, txt[:60 if px == 8 else 40], col, px, -1 if px == 16 else 0)
