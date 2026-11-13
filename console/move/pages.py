"""The Move's screens: what the Pi app's state looks like on 128 x 64 pixels. Each page reads the app's own
state (console.Transport, the engine, the menus) and draws it; nothing here changes anything.

    draw(frame, T, menu)      picks the page the app is on and draws it
"""
import time

import sequencer

import numpy as np

import tape
import drumparams    # noqa: F401  (the drum page's names)

from screen import W, H

TRACKS_SHOWN = 4                      # tracks on screen at once (the selected one's group of four)
LANE_H = 11                           # pixels per track


def draw(f, T, menu=None):
    f.clear()
    try:
        if menu is not None and menu.open and getattr(menu, "mode", "") == "name":
            name_page(f, menu)
        elif menu is not None and menu.open and getattr(menu, "mode", "") == "qr":
            qr_page(f)
        elif menu is not None and menu.open and getattr(menu, "mode", "") == "settings":
            settings_page(f, menu)
        elif menu is not None and menu.open and getattr(menu, "mode", "") == "load":
            delete_page(f, menu)                          # open / delete / rename: the same list
        elif menu is not None and menu.open and getattr(menu, "mode", "") == "list":
            menu_list_page(f, menu, T)
        elif menu is not None and menu.open:
            text_page(f, menu.s, getattr(menu, "msg", ""))
        elif menu is not None and menu.kits.open:
            if menu.kits.mode == "list":
                kit_list(f, menu.kits)
            elif menu.kits.mode == "name":
                name_page(f, menu.kits, "NAME THIS PRESET")
            elif menu.kits.mode == "load":
                preset_list(f, menu.kits)
            elif menu.kits.mode in ("clear_all", "clear", "paste"):
                confirm_page(f, menu.kits)
            else:
                text_page(f, menu.kits.s, getattr(menu.kits, "msg", ""))
        elif getattr(T, "input_popup", None) and time.monotonic() < T.input_popup[0] \
                and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
            input_popup(f, T)
        elif T.fx_page:                                   # left button 3: over the instrument's pages too
            fx_page(f, T)
        elif T.seq_page and getattr(T, "punch", None) is not None and T.punch.active():
            punch_page(f, T)
        elif T.seq_page and getattr(T, "auto", None) is not None and T.auto.active():
            auto_page(f, T)
        elif T.seq_page:
            seq_page(f, T)
        elif T.drum_page:
            sound_page(f, T)
        elif T.inst_page:
            inst_page(f, T)
        elif getattr(T, "song_page", False):
            song_page(f, T)
        elif T.focus.track is not None:
            focus_page(f, T)
        else:
            tape_page(f, T)
    except Exception as ex:                           # a drawing problem shouldn't stop the app
        global last_error
        import traceback
        last_error = traceback.format_exc()           # (the menu test reads it)
        f.clear()
        f.text(1, 1, "SCREEN ERROR")
        f.small(1, 12, str(ex)[:31])
    card = T.pagefx.state() if getattr(T, "pagefx", None) is not None else None
    if card is not None:                              # a page change: its name slides in over everything
        import pagefx
        pagefx.draw(f, card)
        return
    message(f, T)


def message(f, T):
    """The app's short messages (TRACK 3 ARMED...), over the bottom line."""
    pop = getattr(T, "input_popup", None)
    if pop and time.monotonic() < pop[0] and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        return                                        # the big input screen has its own bottom line
    if T.message and time.monotonic() < T.message_until:
        f.rect(0, H - 8, W, 8, 1)
        f.small(1, H - 6, T.message[:31], 0)


def header(f, title, right=""):
    f.rect(0, 0, W, 9, 1)
    f.text(1, 1, title, 0, limit=W - 2 - (Frame_width(right) + 4 if right else 0))
    if right:
        f.right(W - 2, 2, right, small=True, c=0)


def Frame_width(s):
    return len(str(s)) * 4 - 1


# ------------------------------------------------------------------ the tape

def tape_header(f, T):
    """The tape's top line: STOP / PLAY / REC / ODUB, the tempo, the position."""
    e, t = T.engine, T.tape
    state = "REC" if T.recording else "PLAY" if T.playing else "STOP"
    if e and e.rec_mode == "overdub" and T.recording:
        state = "ODUB"
    f.rect(0, 0, W, 9, 1)
    f.text(1, 1, state, 0)
    bpm = "%.0f" % (e.bpm if e else 120)
    f.small(30, 2, bpm + " BPM", 0)
    if getattr(T, "song", None) is not None and T.song.on and T.song.rows:
        f.small(61, 2, "SONG", 0)
    f.right(W - 2, 2, T.position_text(t.pos)[:12], small=True, c=0)


LANE_TOPS = (14, 24, 35, 46)            # the four tracks' rows on the tape page (boxes 7 high, a line under)


def ruler_ticks(f, T, y, x0, x1, mid, ppb):
    """Ticks hanging from row y: 3 high on the bar, 2 on the half bar, 1 on the other beats."""
    t = T.tape
    bar = tape.BEATS_PER_BAR
    k = int(t.pos - (mid - x0) / ppb) - 1
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= x1:
            break
        if x >= x0:
            in_bar = k % bar
            if abs(in_bar) < 1e-6:
                f.rect(x, y, 1, 3)
            elif ppb >= 3 and abs(in_bar - bar / 2) < 1e-6:
                f.rect(x, y, 1, 2)
            elif ppb >= 3:
                f.dot(x, y)
        k += 1


def tape_page(f, T):
    """The tape, as drawn in the screen designer: the header, a ruler of ticks, four tracks (the selected
    track's group) as solid boxes on a line, splices as a thin divider down to the line, the selected
    track's number inverted. The playhead is a dotted line in the middle (drawn so it shows on boxes too);
    the loop's span is a line under the ruler."""
    e, t = T.engine, T.tape
    tape_header(f, T)
    if not e:
        return
    fpb = e.frames_per_beat()
    beats_across = tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR
    x0, x1 = 11, 124
    mid = x0 + (x1 - x0) // 2
    ppb = (x1 - x0) / beats_across                  # pixels per beat
    first = ((T.armed - 1) // TRACKS_SHOWN) * TRACKS_SHOWN
    ruler_ticks(f, T, 10, x0, x1, mid, ppb)
    for i in range(TRACKS_SHOWN):
        n = first + i                                # 0-7
        top = LANE_TOPS[i]
        if n == T.armed - 1:
            f.rect(0, top, 9, 7)
            f.text(2, top, str(n + 1), 0)
        else:
            f.text(2, top, str(n + 1))
        if n in e.arm_extra:
            f.rect(9, top + 1, 2, 5)                 # armed (Shift + step button): a bar beside the number
        if not e.audible(n):
            f.rect(1, top + 8, 7, 1)                 # muted: a line under the number
        f.rect(x0, top + 8, x1 - x0, 1)              # the track's line
        c = e.chans(n)[0]
        boxes = e.regions[c]
        for k, r in enumerate(boxes):
            xa = int(round(mid + (r[0] / fpb - t.pos) * ppb))
            xb = int(round(mid + (r[1] / fpb - t.pos) * ppb))
            spliced_before = k > 0 and int(boxes[k - 1][1]) == int(r[0])
            spliced_after = k + 1 < len(boxes) and int(boxes[k + 1][0]) == int(r[1])
            a = xa + (2 if spliced_before else 0)
            b = xb - (1 if spliced_after else 0)     # a splice: a pixel's gap, the divider, a pixel's gap
            a, b = max(x0, a), min(x1, b)
            if b > a:
                f.rect(a, top, b - a, 7)
            if spliced_after and x0 <= xb < x1:
                f.rect(xb, top, 1, 8)
    # the loop's in and out points: a line under the ruler between them
    region = e.loop_region()
    if region:
        a = int(round(mid + (region[0] / fpb - t.pos) * ppb))
        b = int(round(mid + (region[1] / fpb - t.pos) * ppb))
        a, b = max(x0, a), min(x1 - 1, b)
        if b >= a:
            f.rect(a, 13, b - a + 1, 1, 1 if e.loop_on else 1)
            for x in (a, b):
                f.rect(x, 10, 1, 4)
    # the playhead: every other pixel, the opposite of what's under it
    for y in range(10, LANE_TOPS[-1] + 9):
        if y % 2 == 0:
            f.dot(mid, y, 0 if f.px[y, mid] else 1)
    # the bottom line: the selected track
    n = T.armed - 1
    pan = e.pans[n]
    pan_t = "C" if abs(pan) < 0.05 else ("L%d" % round(-pan * 100) if pan < 0 else "R%d" % round(pan * 100))
    info = "T%d VOL %d PAN %s %s%s" % (T.armed, round(e.volumes[n] * 100), pan_t,
                                       "LOOP" if (region and e.loop_on) else "",
                                       " ST" if n in e.stereo else "")
    f.small(1, H - 6, info)


def track_boxes(f, T, n, y, h, x0, x1, mid, ppb):
    """Track n's boxes between y and y + h, each with its ends (a splice shows as a gap), and its sound."""
    e, t = T.engine, T.tape
    fpb = e.frames_per_beat()
    for c in e.chans(n)[:1]:                         # the left side (a stereo track's right is under it)
        lv = e.levels[c] if c < len(e.levels) else None
        for r in e.regions[c]:
            a, b = r[0] / fpb, r[1] / fpb
            ra = int(round(mid + (a - t.pos) * ppb))
            rb = int(round(mid + (b - t.pos) * ppb))
            if rb < x0 or ra > x1:
                continue
            left_end, right_end = ra >= x0, rb - 1 <= x1 - 1
            ra, rb = max(x0, ra), min(x1 - 1, rb - 1)
            if rb < ra:
                continue
            f.rect(ra, y, rb - ra + 1, 1)
            f.rect(ra, y + h - 2, rb - ra + 1, 1)
            if left_end:
                f.rect(ra, y, 1, h - 1)
            if right_end:
                f.rect(rb, y, 1, h - 1)
            if lv is not None:
                for x in range(ra, rb + 1):
                    beat = t.pos + (x - mid) / ppb
                    idx = int(beat * tape.RES)
                    if 0 <= idx < len(lv):
                        v = int(min(1.0, float(lv[idx])) * (h - 4))
                        if v:
                            f.rect(x, y + 1 + (h - 3 - v) // 2, 1, max(1, v))


def bar_dots(f, T, top, bottom, x0, x1, mid, ppb):
    """Bar lines (dotted) and beat ticks along the top."""
    t = T.tape
    bar = tape.BEATS_PER_BAR
    b0 = t.pos - (mid - x0) / ppb
    k = int(b0 // bar)
    while True:
        bx = int(round(mid + (k * bar - t.pos) * ppb))
        if bx > x1:
            break
        if bx >= x0:
            for y in range(top, bottom, 2):
                f.dot(bx, y)
        k += 1
    if ppb >= 4:
        k = int(b0)
        while True:
            bx = int(round(mid + (k - t.pos) * ppb))
            if bx > x1:
                break
            if bx >= x0:
                f.dot(bx, top)
            k += 1


def input_parts(e, c):
    """A track's input channel as two lines: who and what, for the big input screen."""
    import audio
    if c is None:
        return "ALL INSTRUMENTS", "MIXED"
    if c >= audio.EXT_IN:
        return "MOVE INPUT", "LEFT" if c == audio.EXT_IN else "RIGHT"
    slot, k = divmod(c, audio.SLOT_CH)
    mid = e.slots[slot] if slot < audio.SLOTS else None
    if not mid:
        return "INSTRUMENT %d" % (slot + 1), "EMPTY"
    try:
        import instpage
        who = dict(instpage.machines()).get(mid) or mid
    except Exception:
        who = mid
    if k >= audio.DRUM_KIT and e.is_synth(mid):
        return "%d  %s" % (slot + 1, who), ("SOUND LEFT", "SOUND RIGHT", "SOUND (MONO)")[k - audio.DRUM_KIT]
    what = "KIT LEFT" if k == audio.DRUM_KIT else "KIT RIGHT" if k == audio.DRUM_KIT + 1 else \
        "KIT (ALL DRUMS)" if k == audio.DRUM_KIT + 2 else "DRUM %d ONLY" % (k + 1)
    return "%d  %s" % (slot + 1, who), what


def fit_lines(f, text, y, big=True):
    """Draws text centred at y as large as fits (double size, else normal on one or two lines). Returns the next y."""
    text = str(text).upper()
    if big and len(text) <= 10:
        f.big((W - len(text) * 12 + 2) // 2, y, text)
        return y + 17
    if len(text) <= 21:
        f.centre(W // 2, y + 3, text)
        return y + 17
    cut = text.rfind(" ", 0, 21)
    cut = cut if cut > 0 else 21
    f.centre(W // 2, y, text[:cut].strip())
    f.centre(W // 2, y + 9, text[cut:].strip()[:21])
    return y + 19


def input_popup(f, T):
    """Turning a track's input knobs: the choice on the whole screen, in big letters."""
    e = T.engine
    _until, t, side = T.input_popup
    src = e.source(t)
    stereo = t in e.stereo
    if side < 0:                                           # knob 1: mono or stereo
        header(f, "TRACK %d" % (t + 1))
        f.big((W - (6 if stereo else 4) * 12 + 2) // 2, 20, "STEREO" if stereo else "MONO")
        f.centre(W // 2, 44, "LEFT AND RIGHT INPUTS" if stereo else "ONE INPUT")
        f.small(1, 58, "TURN KNOB 1 TO CHANGE")
        return
    c = src[side] if isinstance(src, tuple) and side < len(src) else src
    who, what = input_parts(e, c)
    header(f, "TRACK %d  %s" % (t + 1, ("LEFT IN" if side == 0 else "RIGHT IN") if stereo else "INPUT"))
    y = fit_lines(f, who, 14)
    fit_lines(f, what, y + 1)
    try:
        choices = e.track_input_choices(stereo=stereo)
        pos = choices.index(c) + 1 if c in choices else 0
        f.right(W - 2, 58, "%d / %d" % (pos, len(choices)), small=True)
    except Exception:
        pass
    f.small(1, 58, "TURN TO CHANGE")


def focus_page(f, T):
    """The zoomed track (left button 4), as drawn in the screen designer: the tape's header, a ruler (long
    tick on the bar, middle one on the half bar, short ones on the beats), the track's sound as one solid
    waveform in 2-pixel columns, splices as an I-beam cutting a gap through it, a line along the bottom.
    The playhead is the notch in the ruler, in the middle. Knobs: 1 mono / stereo, 2 input (3 a stereo
    track's right), 4-6 the box under the playhead (gain, fade in, fade out); values show as they turn."""
    e, t = T.engine, T.tape
    n = T.focus.shown
    tape_header(f, T)
    x0, x1 = 11, 124                                  # the track's area, left of it the number
    mid = x0 + (x1 - x0) // 2
    ruler_y, bottom_y = 11, 58
    centre, half = 35, 16                             # the waveform's middle row and its tallest reach
    beats_across = tape.ZOOMS[t.zoom] * tape.BEATS_PER_BAR
    ppb = (x1 - x0) / beats_across
    f.text(2, 15, str(n))
    if not e.audible(n - 1):
        f.rect(1, 23, 7, 1)                           # muted: a line under the number
    if (n - 1) in e.stereo:
        f.small(1, 26, "ST")
    # the ruler
    f.rect(x0, ruler_y, x1 - x0, 1)
    bar = tape.BEATS_PER_BAR
    first = int((t.pos - (mid - x0) / ppb)) - 1
    k = first
    while True:
        x = int(round(mid + (k - t.pos) * ppb))
        if x >= x1:
            break
        if x >= x0:
            in_bar = k % bar
            if abs(in_bar) < 1e-6:
                f.rect(x, ruler_y + 1, 1, 3)          # the bar
            elif ppb >= 3 and abs(in_bar - bar / 2) < 1e-6:
                f.rect(x, ruler_y + 1, 1, 2)          # the half bar
            elif ppb >= 3:
                f.dot(x, ruler_y + 1)                 # a beat
        k += 1
    # the bottom line
    f.rect(x0, bottom_y, x1 - x0, 1)
    # the sound: each box's levels, solid, in 2-pixel columns
    fpb = e.frames_per_beat()
    c = e.chans(n - 1)[0]
    lv = e.levels[c] if c < len(e.levels) else None
    splices = []
    boxes = e.regions[c]
    for i, r in enumerate(boxes):
        a, b = r[0] / fpb, r[1] / fpb
        xa = int(round(mid + (a - t.pos) * ppb))
        xb = int(round(mid + (b - t.pos) * ppb))
        if i and int(boxes[i - 1][1]) == int(r[0]):
            splices.append(xa)                        # touching the box before: a splice
        if xb < x0 or xa >= x1 or lv is None:
            continue
        for x in range(max(x0, xa), min(x1, xb)):
            col = x0 + (x - x0) // 2 * 2                         # 2-pixel columns: both read the same level
            beat = t.pos + (col + 1 - mid) / ppb
            idx = int(beat * tape.RES)
            if 0 <= idx < len(lv):
                h = max(1, int(round(min(1.0, float(lv[idx])) * half)))
                f.rect(x, centre - h, 1, 2 * h + 1)
    for x in splices:
        if x0 <= x < x1:
            for y in range(ruler_y + 2, bottom_y - 1):          # the I-beam; where it crosses the sound, a gap
                beside = f.px[y, x - 1] if x > 0 else 0
                f.dot(x, y, 0 if beside or (x + 1 < W and f.px[y, x + 1]) else 1)
            f.rect(x - 2, ruler_y + 2, 5, 1)
            f.rect(x - 2, bottom_y - 2, 5, 1)
    # the playhead: a notch in the ruler
    f.rect(mid - 1, ruler_y, 3, 1, 0)
    f.dot(mid, ruler_y + 1)
    f.dot(mid, ruler_y + 2)


# ------------------------------------------------------------------ instruments

def inst_page(f, T):
    e, ip = T.engine, T.instp
    if ip.mode == "pick":
        carousel(f, ip)
        return
    header(f, "SHOW OR HIDE" if ip.mode == "edit" else "INSTRUMENTS")
    if ip.mode in ("menu", "edit"):
        items = [c[1] if isinstance(c, (tuple, list)) else str(c) for c in ip.choices]
        biglist(f, items, ip.pick)
        return
    names = {}
    try:
        import instpage
        names = {m: title for m, title in instpage.machines()}
    except Exception:
        pass
    rows = []
    for k in range(8):
        mid = e.slots[k] if e else None
        mute = e and k in e.slot_mutes
        rows.append("%d %s%s" % (k + 1, (names.get(mid, mid) or "-").upper(), "  MUTE" if mute else ""))
    listing(f, rows, ip.row, top=11)


last_error = None                                     # the last drawing problem's Python error (see draw)
_IMG = {}
_CAR = {"pos": None, "t": 0.0}


def instrument_image(mid, folder="instimg"):
    """The picture for an instrument (move/instimg/<id>.txt: 64 rows of 32 hex digits), or None. Effects: fximg."""
    key = mid if folder == "instimg" else folder + "/" + mid
    if key not in _IMG:
        arr = None
        try:
            import os
            rows = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), folder, "%s.txt" % mid)).read().split()
            arr = np.array([[(int(row, 16) >> (127 - x)) & 1 for x in range(128)] for row in rows[:64]], np.uint8)
        except (OSError, ValueError):
            pass
        _IMG[key] = arr
    return _IMG[key]


def carousel(f, ip):
    """Choosing an instrument: one picture at a time, sliding left and right as the wheel turns. An
    instrument without a picture yet shows its name. Past either end it wraps round, and the slide is one
    step the short way (the last one slides in from the left of the first), not a scroll through the whole list."""
    n = len(ip.choices)
    now = time.monotonic()
    st = _CAR
    if st["pos"] is None or now - st["t"] > 1.0 or st.get("n") != n:
        pos = target = float(ip.pick)                  # just opened: start on the picked one
        st["last"] = ip.pick
    else:
        pos, target = st["pos"], st["target"]
        if ip.pick != st["last"]:
            d = ip.pick - st["last"]
            if d > n / 2:
                d -= n                                 # (1st turned left: on to the last, one step back)
            elif d < -n / 2:
                d += n
            target += d
            st["last"] = ip.pick
        pos += (target - pos) * 0.45                   # ease towards it
        if abs(target - pos) < 0.02:
            pos = target = float(ip.pick)
    st.update(pos=pos, target=target, t=now, n=n)
    base = int(pos // 1)
    for i in (base, base + 1):
        k = i % n
        dx = int(round((i - pos) * W))
        mid, title = ip.choices[k][0], ip.choices[k][1]
        img = instrument_image(mid, getattr(ip, "img_dir", "instimg"))
        x0, x1 = max(0, dx), min(W, dx + W)
        if x1 <= x0:
            continue
        if img is not None:
            f.px[0:64, x0:x1] = img[:, x0 - dx:x1 - dx]
        else:                                          # no picture yet: the whole screen, just the name
            f.px[0:H, x0:x1] = 0
            f.frame(dx + 4, 4, W - 8, H - 8)
            f.centre(dx + W // 2, 26, str(title)[:19])
    if n > 1:                                          # (it wraps, so there is always another way to go)
        f.small(0, 29, "<", 1)
        f.small(W - 3, 29, ">", 1)


def fx_picker_view(f, fp):
    """The effect picker: one picture at a time, or (EDIT) the show / hide list."""
    if fp.editing:
        header(f, "SHOW OR HIDE")
        biglist(f, [c[0] for c in fp.choices], fp.pick)
    else:
        carousel(f, fp)


def biglist(f, rows, pick, fit=5, top=11):
    """A list in the larger letters (as the sample browser), the picked row inverted, scrolled to keep it on
    screen. A row too long for the big letters is drawn small instead."""
    first = max(0, min(pick - fit // 2, len(rows) - fit))
    for i in range(fit):
        k = first + i
        if k >= len(rows):
            break
        y = top + i * 9
        t = str(rows[k])
        on = k == pick
        if on:
            f.rect(0, y - 1, W, 9, 1)
        if len(t) <= 21:
            f.text(2, y, t, 0 if on else 1)
        else:
            f.small(2, y + 1, t[:31], 0 if on else 1)


def listing(f, rows, pick, top=11, line=7, fit=None):
    """A list in small letters, the picked row inverted, scrolled to keep it on screen."""
    fit = fit or (H - top) // line
    first = max(0, min(pick - fit // 2, len(rows) - fit))
    for i in range(fit):
        k = first + i
        if k >= len(rows):
            break
        y = top + i * line
        if k == pick:
            f.rect(0, y - 1, W, line, 1)
            f.small(2, y, str(rows[k])[:31], 0)
        else:
            f.small(2, y, str(rows[k])[:31])


# ------------------------------------------------------------------ an instrument's sound

def insert_page(f, T, pos):
    if T.fxpick.active:
        fx_picker_view(f, T.fxpick)
        return
    ins = T.insfx(None, pos)
    header(f, ("INSERT %d" % (ins.pos + 1)), "SLOT %d" % (ins.slot + 1))
    f.text(2, 12, ins.name()[:21])
    for i in range(8):
        label, shown = ins.text(i)
        if not label:
            continue
        col, row = divmod(i, 4)
        x, y = col * 65, 24 + row * 9
        f.small(x + 1, y, ("%d %s" % (i + 1, label))[:10])
        f.right(x + 62, y, shown[:6], small=True)
    f.small(1, 59, (ins.error or "PUSH WHEEL: CHOOSE EFFECT").upper()[:31])


def arp_page(f, T):
    """A synth's arpeggiator: knobs 1-8 are its settings, the 16 step buttons its rhythm (drawn along the bottom)."""
    ml = T.mlfo
    c = ml.cfg()
    header(f, "ARP 2" if ml.arp_second() else "ARP", "ON" if c["on"] else "OFF")
    for i, (label, shown) in enumerate(ml.arp_values()):
        col, row = divmod(i, 4)
        x, y = col * 65, 12 + row * 8
        f.small(x + 1, y, "%d %s" % (i + 1, label))
        f.right(x + 62, y, str(shown)[:9], small=True)
    for i, r in enumerate(c["rhythm"]):                   # rest: an outline, note: half full, accent: full
        x = 2 + i * 8
        f.rect(x, 47, 6, 6, 1)
        f.rect(x + 1, 48, 4, 4, 0)
        if r == 1:
            f.rect(x + 1, 50, 4, 2, 1)
        elif r == 2:
            f.rect(x + 1, 48, 4, 4, 1)
    f.small(1, 57, "STEPS: NOTE, ACCENT, REST")


def pads_page(f, T):
    """The pads' key, scale and octave (the hexagon icon on a synth's sound pages)."""
    ml = T.mlfo
    header(f, "PADS", "SLOT %d" % (T.engine.slot + 1))
    for i, (label, shown) in enumerate(ml.pads_values()):
        col, row = divmod(i, 3)
        x, y = col * 65, 13 + row * 14
        f.small(x + 1, y, "%d %s" % (i + 1, label))
        f.text(x + 1, y + 6, str(shown)[:10])
    f.small(1, 57, "KEY, SCALE, OCTAVE, PAD FEEL" if ml.has_arp() else "OCTAVE, PAD FEEL")


def sends_page(f, T):
    """SENDS (after INSERT 2): this instrument's reverb and delay sends, and how much of the song inserts it hears."""
    ml = T.mlfo
    header(f, "SENDS", "SLOT %d" % (T.engine.slot + 1))
    for i, (label, shown) in enumerate(ml.sends_values()):
        col, row = divmod(i, 2)
        x, y = col * 65, 13 + row * 20
        f.small(x + 1, y, "%d %s" % (i + 1, label))
        f.text(x + 1, y + 7, str(shown)[:10])


def lfo_page(f, T):
    ml = T.mlfo
    e = T.engine
    if ml.sends_on_page():
        sends_page(f, T)
        return
    if ml.pads_on_page():
        pads_page(f, T)
        return
    if ml.arp_on_page():
        arp_page(f, T)
        return
    if ml.insert_pos() is not None:
        insert_page(f, T, ml.insert_pos())
        return
    header(f, "LFO %d" % (ml.tab + 1), "PAT %d" % (e.seq.current + 1))
    for i, (label, value) in enumerate(ml.values()):
        col, row = divmod(i, 3)
        x, y = col * 65, 13 + row * 11
        f.small(x + 1, y, "%d %s" % (i + 1, label))
        f.right(x + 62, y, str(value)[:9], small=True)
    f.small(1, 50, "STEPS: TAP = REST, HOLD + 2/4")
    f.small(1, 57, "< >: PAGES   BACK: INSTRUMENTS")


def sample_page(f, sb):
    header(f, sb.title())
    rows = [r[0] for r in sb.entries] or ["EMPTY"]
    fit = 5
    first = max(0, min(sb.pick - fit // 2, len(rows) - fit))
    for i in range(fit):
        k = first + i
        if k >= len(rows):
            break
        y = 11 + i * 9
        if k == sb.pick:
            f.rect(0, y - 1, W, 9, 1)
            f.text(2, y, rows[k], 0, limit=W - 4)
        else:
            f.text(2, y, rows[k], 1, limit=W - 4)
    f.small(1, H - 6, "PUSH: CHOOSE  DEL+PUSH: REMOVE" if sb.stage == "which" else "PUSH: OPEN/CHOOSE  BACK: UP")


def sound_page(f, T):
    if T.sbrowse.active:
        sample_page(f, T.sbrowse)
        return
    if T.mlfo.active():
        lfo_page(f, T)
        return
    if getattr(T, "presets", None) is not None and T.presets.on_page():
        presets_page(f, T)
        return
    e = T.engine
    d = e.drums
    pages = T.drum_pages()
    T.drum_tab = min(T.drum_tab, len(pages) - 1)
    page_name, params = pages[T.drum_tab]
    voice = T.drum_voice
    names = getattr(d, "names", None) or []
    vname = names[voice] if voice < len(names) else ""
    octave = getattr(T, "octave", 0)
    header(f, ("%s %s" % (vname, page_name)).strip()[:15 if octave else 18],
           ("OCT %+d  " % octave if octave else "") + "%d/%d" % (T.drum_tab + 1, len(pages)))
    now = time.monotonic()
    turning = None
    for i, _p in enumerate(params):
        when = T.drumpage.edited.get(i + 1, 0.0)
        if now - when < 1.0 and (turning is None or when > T.drumpage.edited.get(turning + 1, 0.0)):
            turning = i
    if turning is not None:                           # a knob turning: that one setting, big
        p = params[turning]
        if d.kind(p) in ("menu", "onoff", "voice", "vel_target", "lfo_target"):
            f.centre(W // 2, 26, d.value_text(p)[:20])
        else:
            f.bar_lines(W // 2, 31, d.fraction(p))
        f.text(1, 55, "%d %s" % (turning + 1, d.label(p))[:13])
        f.right(W - 1, 55, d.value_text(p)[:7])
        return
    for i, p in enumerate(params[:8]):              # the page's settings in knob order: 1-4 left, 5-8 right
        col, row = divmod(i, 4)
        x, y = col * 65, 11 + row * 11
        f.small(x + 1, y, ("%d %s" % (i + 1, d.label(p)))[:9])
        if d.kind(p) in ("menu", "onoff", "voice", "vel_target", "lfo_target"):
            f.right(x + 62, y, d.value_text(p)[:6], small=True)
        else:
            frac = max(0.0, min(1.0, d.fraction(p)))
            f.rect(x + 1, y + 7, 60, 1)
            f.rect(x + 1 + int(frac * 59), y + 6, 2, 3)


def lock_knobs(f, ms):
    """Steps selected, no pad picked: knobs 1-8 are the instrument's sound page, turning one locks it on the
    steps (* a locked one; - one that can't be locked)."""
    f.rect(0, 26, W, H - 26, 0)
    pages = ms.sound_pages()
    f.small(1, 27, ("%s  %d/%d" % (ms.page_name(), ms.knob_page + 1, max(1, len(pages))))[:31])
    for i, (label, value, locked, lockable) in enumerate(ms.lock_list()):
        col, row = divmod(i, 4)
        x, y = col * 65, 34 + row * 6                  # (four rows, then the hint on the bottom line)
        f.small(x + 1, y, ("%s%d %s" % ("*" if locked else "", i + 1, label if lockable else "-"))[:10])
        if lockable:
            f.right(x + 62, y, str(value)[:5], small=True)
    f.small(1, 59, "TURN: LOCK  < >: PAGES")


def synth_seq_page(f, T):
    """The synth sequencer (see movesynth.py): the 16 steps the buttons show, and the knobs or the held step."""
    import notes
    e, ms = T.engine, T.msyn
    seq = e.seq
    first = ms.first()
    pat = "PAT %d" % (seq.current + 1) + (">%d" % (seq.queued + 1) if seq.queued is not None else "")
    rec = "REC " if T.live_rec else ""
    if ms.selected:
        header(f, ms.which(), pat)
    elif ms.lane is not None and ms.kind:
        header(f, rec + "NOTE " + notes.note_name(ms.lane), pat)
    else:
        header(f, rec + ("PER NOTE" if ms.kind else "UNIFIED"), pat)
    at = ms.playing_step()
    length = ms.length()
    for k in range(16):
        i = first + k
        x, y = 1 + k * 8, 11
        if i >= length:
            f.dot(x + 3, y + 3)
            continue
        if sequencer.dark(i, sequencer.TRIPLETS):        # TRIPLETS: an off step, a dash
            f.rect(x + 1, y + 3, 5, 1)
            continue
        on = (ms.lane in ms.notes_at(i)) if (ms.lane is not None and ms.kind) else bool(ms.notes_at(i))
        (f.rect if on else f.frame)(x, y, 7, 7)
        if i in ms.down or i in ms.selected:
            f.frame(x - 1, y - 1, 9, 9)
        if at is not None and i == at:
            f.rect(x + 2, y + 2, 3, 3, 0 if on else 1)
    f.small(1, 20, "STEPS %d-%d OF %d" % (first + 1, min(first + 16, length), length))
    if ms.selected:
        if ms.sel is None:
            lock_knobs(f, ms)
            return
        f.frame(8, 26, 112, 32)
        f.rect(9, 27, 110, 30, 0)
        key, label = ms.pad_items()[ms.sel]
        ct = ms.chance_text(key)
        f.centre(64, 28, str(label)[:16])
        f.centre(64, 38, ("KNOB 1: %s" % ms.item_value(key))[:22], small=True)
        if ct is not None:
            f.centre(64, 44, ("KNOB 2 CHANCE: %s" % ct)[:28], small=True)
        f.centre(64, 50 if ct is not None else 46, "SAME PAD AGAIN: OFF" if ms.engaged(key) else "TURN KNOB 1 TO SET IT", small=True)
        return
    if ms.down:
        f.small(1, 28, "PADS: ADD / TAKE OFF NOTES")
        f.small(1, 35, "TAP A LATER STEP: LENGTH")
        f.small(1, 42, "KNOB 1: LENGTH")
        return
    for i, (label, value, _x) in enumerate(ms.knob_list()):
        col, row = divmod(i, 4)
        x, y = col * 65, 28 + row * 7
        f.small(x + 1, y, ("%d %s" % (i + 1, label))[:10])
        f.right(x + 62, y, str(value)[:5], small=True)


def auto_page(f, T):
    """AUTOMATION (left button 1 after the sequencer): one locked setting at a time (knob 1), the steps that
    have it, a held step's value."""
    a = T.auto
    e = T.engine
    d = e.drums
    synth = T.synth_shown()
    if synth:
        name = (e.slots[e.slot] or "").upper() if e.slot is not None else ""
    else:
        names = getattr(d, "lane_names", None) or []
        lane = T.seqp.lane
        name = names[lane] if lane < len(names) else "LANE %d" % (lane + 1)
        if name == "EMPTY":
            name = "DRUM %d" % (lane + 1)
    header(f, "AUTOMATION", str(name)[:12])
    keys = a.keys()
    key = a.key()
    if key is None:
        f.centre(64, 24, "NO AUTOMATION")
        f.centre(64, 36, "RECORD + KNOBS WHILE PLAYING", small=True)
        f.centre(64, 44, "OR SHIFT+STEPS ON THE SEQUENCER", small=True)
        return
    on = a.steps_with(key)
    f.text(1, 12, ("1 %s" % a.label(key))[:16])
    f.right(W - 2, 13, "%d/%d" % (a.pick + 1, len(keys)), small=True)
    length, now = a.length(key), a.playing_step()
    for k in range(16):
        i = a.page * 16 + k
        x, y = 1 + k * 8, 23
        if i >= length:
            f.dot(x + 3, y + 3)
            continue
        if sequencer.dark(i, sequencer.TRIPLETS):
            f.rect(x + 1, y + 3, 5, 1)
            continue
        (f.rect if i in on else f.frame)(x, y, 7, 7)
        if i == a.held:
            f.frame(x - 1, y - 1, 9, 9)
        if now is not None and i == now:
            f.rect(x + 2, y + 2, 3, 3, 0 if i in on else 1)
    f.small(1, 33, "STEPS %d-%d OF %d   %d SET" % (a.page * 16 + 1, min(a.page * 16 + 16, length), length, len(on)))
    if a.confirming():
        f.frame(4, 40, 120, 17)
        f.centre(64, 43, "TAKE %s OFF %d STEPS?" % (a.label(key)[:10], len(on)), small=True)
        f.centre(64, 50, "SHIFT + DELETE AGAIN: YES", small=True)
    elif a.held is not None and a.held in on:
        f.frame(8, 40, 112, 17)
        f.centre(64, 44, "STEP %d  %s" % (a.held + 1, a.value_text(a.held, key)))
    else:
        f.small(1, 43, "KNOB 2: LENGTH  HOLD: KNOB 1" if a.rec(key) else "HOLD A LIT STEP: KNOB 1 SETS IT")
        f.small(1, 50, "DEL+STEP: OFF  SHIFT+DEL: ALL")


def punch_page(f, T):
    """PUNCH FX (left button 1 after AUTOMATION): the punch pattern, the picked effect's lane (its steps, length,
    rate), the time scale, what plays now (see movepunch.py)."""
    import punch
    pu = T.punch
    st = pu.st()
    ln = pu.ln()
    head = "FX%d" % (st.current + 1) + (">%d" % (st.queued + 1) if st.queued is not None else "")
    header(f, "PUNCH FX", head)
    f.text(1, 11, punch.NAMES[pu.lane])
    now = pu.now() or pu.held_mask()
    f.right(127, 12, punch.label(now, short=True)[:10] if now else "", small=True)
    trip, at = pu.trip(), pu.playing_step()
    tails = punch.covered(ln, trip)
    for k in range(16):
        i = pu.page * 16 + k
        x, y = 1 + k * 8, 21
        if i >= ln.length:
            continue
        if sequencer.dark(i, trip):
            f.dot(x + 3, y + 3)
            continue
        on = i in ln.steps
        if i in tails and not on:
            f.rect(x - 1, y + 2, 9, 3)                   # a long step going on through here
        else:
            (f.rect if on else f.frame)(x, y, 7, 7)
        if on and ln.lens.get(i, 1) > 1:
            f.rect(x + 7, y + 2, 1, 3)
        if i == pu.held:
            f.frame(x - 1, y - 1, 9, 9)
        if at is not None and i == at:
            f.rect(x + 2, y + 2, 3, 3, 0 if on else 1)
    f.small(1, 31, "STEPS %d-%d OF %d" % (pu.page * 16 + 1, min(pu.page * 16 + 16, ln.length), ln.length))
    f.right(127, 31, "%d ON" % len(ln.steps), small=True)
    if pu.confirming():
        f.frame(4, 38, 120, 17)
        f.centre(64, 41, "CLEAR PUNCH PATTERN %d?" % (st.current + 1), small=True)
        f.centre(64, 48, "SHIFT + DELETE AGAIN: YES", small=True)
    elif pu.held is not None and pu.held in ln.steps:
        f.frame(4, 37, 120, 18)
        L = ln.lens.get(pu.held, 1)
        f.centre(64, 39, "STEP %d" % (pu.held + 1) + ("  %d LONG" % L if L > 1 else ""))
        f.centre(64, 48, "KNOB 1 CHANCE: %s" % sequencer.CHANCES[ln.steps[pu.held]], small=True)
    else:
        f.small(1, 39, "1 LENGTH %d" % ln.length)
        f.small(1, 46, "2 RATE %s" % pu.rate_name())
        f.small(66, 39, "8 SCALE X%d" % punch.SCALES[st.pattern.scale])
        f.small(66, 46, "SHIFT+PAD:PAT")
        f.small(1, 53, "PAD: LANE  HOLD: PLAY IT")


def seq_page(f, T):
    """The drum sequencer: the picked lane's 16 steps on the buttons (drawn small at the top), and what the
    knobs do: the lane's settings, or while a step button is held, that step's (see moveseq.py)."""
    e = T.engine
    synth = T.synth_shown()
    if synth:
        synth_seq_page(f, T)
        return
    ms = T.mseq
    sp, seq = T.seqp, e.seq
    lane = sp.lane
    ln = seq.lane(lane)
    first = ms.first()
    names = getattr(e.drums, "lane_names", None) or []
    name = names[lane] if lane < len(names) else "LANE %d" % (lane + 1)
    pat = "PAT %d" % (seq.current + 1) + (">%d" % (seq.queued + 1) if seq.queued is not None else "")
    if ms.held is None:
        header(f, name[:13], pat)
    else:
        header(f, ms.which(), name[:12])
    # the 16 steps the buttons show
    at = ms.playing_step()
    for k in range(16):
        i = first + k
        x, y = 1 + k * 8, 11
        if i >= ln.length:
            f.dot(x + 3, y + 3)
            continue
        if sequencer.dark(i, sequencer.TRIPLETS):        # TRIPLETS: an off step, a dash
            f.rect(x + 1, y + 3, 5, 1)
            continue
        on = ln.steps[i].on
        (f.rect if on else f.frame)(x, y, 7, 7)
        if i == ms.held:
            f.frame(x - 1, y - 1, 9, 9)
        if at is not None and i == at:
            f.rect(x + 2, y + 2, 3, 3, 0 if on else 1)
    f.small(1, 20, "STEPS %d-%d OF %d" % (first + 1, min(first + 16, ln.length), ln.length))
    if ms.held is not None:
        # holding a step: its settings are on the pads; the picked one on knob 1 (OP-XY style)
        knobs = ms.knob_list()
        if not knobs:
            lock_knobs(f, ms)
            return
        f.frame(8, 26, 112, 32)
        f.rect(9, 27, 110, 30, 0)
        if True:
            label, value, on = knobs[0]
            key = ms.pad_items()[ms.sel][0]
            ct = ms.chance_text(key)
            f.centre(64, 28, str(label)[:16])
            f.centre(64, 38, ("KNOB 1: %s" % value)[:22], small=True)
            if ct is not None:
                f.centre(64, 44, ("KNOB 2 CHANCE: %s" % ct)[:28], small=True)
            f.centre(64, 50 if ct is not None else 46, "SAME PAD AGAIN: OFF" if on else "TURN KNOB 1 TO SET IT", small=True)
        return
    # the knobs
    knobs = ms.knob_list()
    for i, (label, value, locked) in enumerate(knobs[:8]):
        col, row = divmod(i, 4)
        x, y = col * 65, 28 + row * 7
        f.small(x + 1, y, ("%d %s" % (i + 1, label))[:10])
        if locked:
            f.rect(x + 62 - Frame_width(str(value)[:5]) - 2, y - 1, Frame_width(str(value)[:5]) + 3, 7, 1)
            f.right(x + 62, y, str(value)[:5], small=True, c=0)
        else:
            f.right(x + 62, y, str(value)[:5], small=True)


# ------------------------------------------------------------------ song mode

def song_page(f, T):
    """Song mode: the picked row's pattern for each instrument (knobs 1-7) and how many times it plays (8)."""
    sg = T.song
    sg.check_song()
    header(f, "SONG " + ("ON" if sg.on else "OFF"),
           "ROW %d/%d" % (sg.pick + 1, len(sg.rows)) if sg.rows else "NO ROWS")
    if not sg.rows:
        f.small(1, 14, "STEP BUTTON 1: ADD A ROW")
        f.small(1, 21, "EACH ROW: A PATTERN FOR")
        f.small(1, 28, "EVERY INSTRUMENT, PLAYED")
        f.small(1, 35, "SO MANY TIMES (KNOB 8)")
        f.small(1, 46, "+ / -: SONG MODE ON / OFF")
        return
    row = sg.rows[sg.pick]
    slots = sg.slots()
    shift = bool(getattr(T, "shift_held", lambda: False)())    # Shift held: the punch FX patterns instead
    for i, slot in enumerate(slots):
        col, r = divmod(i, 4)
        x, y = col * 65, 13 + r * 8
        v = row.get("punch", {}).get(slot) if shift else row["pats"].get(slot)
        f.small(x + 1, y, "%d %s" % (i + 1, sg.short(slot)))
        f.right(x + 62, y, "-" if v is None else ("FX%d" if shift else "P%d") % (v + 1), small=True)
    if shift:
        f.small(1, 48, "SHIFT: PUNCH FX PATTERNS")
    col, r = divmod(7, 4)
    f.small(66, 13 + r * 8, "8 PLAYS")
    f.right(W - 2, 13 + r * 8, "x%d" % row["repeat"], small=True)
    if sg.playing_row is not None and not shift:
        f.small(1, 48, "PLAYING ROW %d" % (sg.playing_row + 1))
    f.small(1, 56, "STEPS: ROWS  DEL+STEP: OUT")


# ------------------------------------------------------------------ effects

def song_insert_page(f, T, p):
    """SONG INSERT 1 / 2 (left button 3): the song's effect, on every instrument (a copy each), and its settings."""
    if T.fxpick.active:
        fx_picker_view(f, T.fxpick)
        return
    sf = T.songfx(p)
    header(f, "SONG INSERT %d" % (p + 1))
    f.text(2, 12, sf.name()[:21])
    if not sf.params:
        f.small(2, 24, "ON EVERY INSTRUMENT, A COPY")
        f.small(2, 31, "EACH, RECORDED WITH IT")
    for i in range(8):
        label, shown = sf.text(i)
        if not label:
            continue
        col, row = divmod(i, 4)
        x, y = col * 65, 24 + row * 9
        f.small(x + 1, y, ("%d %s" % (i + 1, label))[:10])
        f.right(x + 62, y, shown[:6], small=True)
    f.small(1, 59, (sf.error or "PUSH WHEEL: CHOOSE EFFECT").upper()[:31])


def mixer_page(f, T):
    """MIXER (left button 3, the first page): the 8 instruments' volume and pan; knobs 1-8 turn the volume, Shift + a
    knob the pan."""
    from console import mix_pan_text
    e = T.engine
    header(f, "MIXER", "SHIFT: PAN")      # (the step buttons: mute, Shift: solo)
    for i in range(8):
        y = 12 + i * 6
        mid = e.slots[i] if e else None
        f.small(1, y, ("%d %s" % (i + 1, T.instp.title(mid) if mid else "-"))[:14])
        if mid and i in e.slot_mutes:
            f.right(W - 2, y, "MUTED", small=True)
        elif mid:
            f.right(88, y, "%d%%" % round(e.inst_levels[i] * 100), small=True)
            f.right(W - 2, y, mix_pan_text(e.inst_pans[i]), small=True)


def fx_page(f, T):
    e = T.engine
    which = T.fx_page
    if which in ("song1", "song2"):
        song_insert_page(f, T, 0 if which == "song1" else 1)
        return
    if which == "mixer":
        mixer_page(f, T)
        return
    header(f, which.upper())
    for i, (k, name) in enumerate(T.FX_KNOBS[which]):
        y = 13 + i * 10
        f.small(1, y, "%d %s" % (i + 1, name))
        f.right(W - 2, y, T.fx_value_text(k)[:10], small=True)


# ------------------------------------------------------------------ the menus (any of the Pi's menu screens)

def kit_list(f, k):
    """The instrument menu (File on a sound page): its choices and the project's, in one list (the wheel stops at
    the ends). DRUM MACHINE isn't shown: instruments are chosen on the instruments page."""
    import kitmenu
    rows = [kitmenu.TEXTS[key].upper() for key, _ in kitmenu.ITEMS] + \
           [kitmenu.MAIN_TEXTS[key].upper() for key, _ in kitmenu.MAIN]
    rows = rows[1:]
    f.rect(0, 0, W, 9, 1)
    f.text(1, 1, "INSTRUMENT MENU", 0)
    f.right(W - 2, 2, "%d/%d" % (max(1, k.choice), len(rows)), small=True, c=0)
    biglist(f, rows, max(0, k.choice - 1), fit=5)            # (the bottom line is for messages)
    msg = getattr(k, "msg", "")
    if msg:
        f.rect(0, H - 8, W, 8, 1)
        f.small(1, H - 6, str(msg).upper()[:31], 0)


def confirm_page(f, k):
    """Clear pattern / clear locks / paste: a question, what it affects, PLAY or BACK."""
    import notes as notes_mod
    synth = isinstance(k.seq, notes_mod.NoteSequencer)
    n = k.seq.current + 1
    if k.mode == "clear_all":
        on = k.on_count()
        header(f, "CLEAR PATTERN %d?" % n)
        f.text(2, 16, "%d %s ON" % (on, ("NOTE" if on == 1 else "NOTES") if synth else ("STEP" if on == 1 else "STEPS")))
        f.small(2, 30, "STEPS, LOCKS, LENGTHS, RATES")
        f.small(2, 37, "ALL BACK TO A NEW PATTERN")
    elif k.mode == "clear":
        locks, steps = k.lock_count()
        header(f, "CLEAR LOCKS?  PATTERN %d" % n)
        f.text(2, 16, "%d LOCK%s" % (locks, "" if locks == 1 else "S"))
        f.small(2, 30, "ON %d %s" % (steps, "NOTES" if synth else "STEPS"))
        f.small(2, 37, "NOTES STAY, SETTINGS RESET")
    else:
        header(f, "PASTE PATTERN %d?" % (k.pattern_clip[1] + 1))
        f.text(2, 16, "ONTO PATTERN %d" % n)
        f.small(2, 30, "IT HAS NOTES OR STEPS:")
        f.small(2, 37, "PASTING REPLACES THEM")
    f.small(1, 51, "PLAY: YES")
    f.small(1, 58, "BACK: NO, KEEP IT")


def presets_page(f, T):
    """A synth's PRESETS page: yours (*) then its own; the one you're on in the middle."""
    pr = T.presets
    pr.sync()
    n = pr.total()
    pages = T.drum_pages()
    header(f, "PRESETS", ("%d/%d" % (pr.pos + 1, n)) if n else "")
    bank = pr.bank_label()
    if bank:
        f.small(1, 11, ("1 BANK: " + bank.upper())[:31])
    if not n:
        f.centre(W // 2, 28, "NO PRESETS YET", small=True)
        f.centre(W // 2, 38, "MENU > SAVE PRESET", small=True)
        return
    first = max(0, min(pr.pos - 2, n - 4))
    rows = [pr.label(i).upper()[:21] if first <= i < first + 4 else "" for i in range(n)]   # (only the ones shown)
    biglist(f, rows, pr.pos, fit=4, top=20 if bank else 13)
    f.small(1, 58, ("PUSH: KEEP   BACK: UNDO" if pr.orig is not None else "WHEEL: BROWSE")[:31])


def preset_list(f, k):
    """LOAD PRESET: this instrument's saved presets, one per line."""
    header(f, "LOAD PRESET", "%d" % len(k.kits))
    biglist(f, [str(n).upper() for n in k.kits], k.pick, fit=4)
    msg = str(getattr(k, "msg", "") or "")
    f.small(1, 58, (msg or "PLAY: LOAD IT   BACK: CANCEL").upper()[:31])


def menu_list_page(f, menu, T):
    """The project menu: NEW, SAVE, LOAD, SETTINGS. Holding Shift turns NEW PROJECT into DELETE PROJECT."""
    import menu as menu_mod
    shift = bool(getattr(T, "shift_held", lambda: False)())
    e = menu.engine
    header(f, ((e.song or "UNTITLED") if e else "DEMO").upper()[:21])
    rows = []
    for label, _ in menu_mod.ITEMS:
        rows.append({"NEW": "DELETE PROJECT" if shift else "NEW PROJECT", "SAVE": "RENAME PROJECT" if shift else "SAVE PROJECT",
                     "LOAD": "LOAD PROJECT", "SETTINGS": "SETTINGS"}[label])
    biglist(f, rows, menu.choice, fit=4)
    msg = str(getattr(menu, "msg", "") or "")
    f.small(1, 58, (msg or ("SHIFT + PUSH: DELETE / RENAME" if shift else "")).upper()[:31])


def delete_page(f, menu):
    """Deleting a project: the list, then a full-screen "are you sure?"."""
    if menu.confirm and menu.confirm[0] == "open":     # opening another song over an unsaved one
        header(f, "OPEN PROJECT")
        f.text(2, 16, "THIS SONG ISN'T SAVED")
        f.text(2, 30, ("OPEN " + str(menu.confirm[1]).upper())[:21])
        f.small(2, 42, "THE UNSAVED SONG IS LOST")
        f.small(1, 52, "PLAY: OPEN IT ANYWAY")
        f.small(1, 58, "BACK: NO, SAVE MINE FIRST")
        return
    if menu.confirm and menu.confirm[0] == "delete":
        header(f, "DELETE PROJECT")
        name = str(menu.confirm[1]).upper()
        f.text(2, 16, "ARE YOU SURE?")
        f.text(2, 30, name[:21])
        f.small(2, 42, "IT IS GONE FOR GOOD")
        f.small(1, 52, "PLAY: YES, DELETE IT")
        f.small(1, 58, "BACK: NO, KEEP IT")
        return
    renaming = getattr(menu, "rename_pick", False)
    deleting = getattr(menu, "deleting", False)
    title = "RENAME WHICH PROJECT?" if renaming else "DELETE WHICH PROJECT?" if deleting else "OPEN PROJECT"
    header(f, title, "%d" % len(menu.songs))
    if not menu.songs:
        f.text(2, 24, "NO SAVED PROJECTS")
    rows = [(s + ("  OPEN" if menu.engine and s == menu.engine.song else "")) for s in menu.songs]
    biglist(f, [r.upper() for r in rows], menu.pick, fit=4)
    msg = str(getattr(menu, "msg", "") or "")
    hint = "PLAY: RENAME   BACK: CANCEL" if renaming else "PLAY: DELETE   BACK: CANCEL" if deleting else \
        "PLAY: OPEN   BACK: CANCEL"
    f.small(1, 58, (msg or hint).upper()[:31])


def settings_page(f, menu):
    """The settings, one row each: the row you're on is a white bar. Push the wheel: the value goes black inside a
    white box and the wheel changes it; push again: back to the rows."""
    import menu as menu_mod
    names = {"TIMESIG": "TIME SIG", "FORMAT": "FORMAT", "UPDATE": "UPDATE", "SYNC": "SYNC", "TEMPO": "TEMPO",
             "SCREEN": "EXTERNAL SCREEN", "TRIPLETS": "TRIPLETS"}
    header(f, "SETTINGS", "TURN, PUSH: DONE" if menu.editing else "PUSH: CHANGE IT")
    rows = menu_mod.SETTINGS
    pitch = 9 if len(rows) <= 5 else 8                 # (six rows: a little closer together)
    fit = 5 if pitch == 9 else 6                       # more than six: the list scrolls with the picked row
    first = max(0, min(menu.row - fit + 1, len(rows) - fit)) if len(rows) > fit else 0
    for i, what in enumerate(rows):
        if not first <= i < first + fit:
            continue
        j = i - first
        y = 12 + j * 9 if pitch == 9 else 11 + j * 8
        full = str(menu.setting_text(what) or "")
        short = full.split("  ")[0].split(": ")[0].upper()[:14]
        label = names.get(what, menu_mod.LABELS.get(what, what))
        on = i == menu.row
        if on and not menu.editing:
            f.rect(0, y - 1, W, 9, 1)
            f.text(2, y, label, 0)
            f.right(W - 3, y, short, c=0)
        else:
            f.text(2, y, label)
            if on:                                            # editing: the value in a white box
                w = len(short) * 6 + 3
                f.rect(W - 3 - w + 1, y - 1, w + 1, 9, 1)
                f.right(W - 3, y, short, c=0)
            else:
                f.right(W - 3, y, short)
    full = str(menu.setting_text(rows[menu.row]) or "")
    msg = str(getattr(menu, "msg", "") or "") or (menu.update_message() if rows[menu.row] == "UPDATE" else "") or full
    f.small(1, 58 if pitch == 9 else 59, msg.upper()[:31])


def qr_page(f):
    """MENU > SETTINGS > EXTERNAL SCREEN: the page's address as a QR code (the phone's camera opens it), and
    written out. Any button: back."""
    import screenview
    url = screenview.address()
    if not url:
        f.centre(64, 20, "NO NETWORK")
        f.centre(64, 34, "JOIN WI-FI OR A HOTSPOT", small=True)
        return
    try:
        import qr
        m = qr.matrix(url)
    except Exception:                                 # noqa: BLE001
        m = None
    if m:
        n = len(m)
        s = 2 if n * 2 + 8 <= H else 1
        side = n * s + 4 * s                          # (a light edge of 2 modules round it)
        f.rect(0, (H - side) // 2, side, side, 1)
        y0 = (H - side) // 2 + 2 * s
        for r, row in enumerate(m):
            for c, v in enumerate(row):
                if v:
                    f.rect(2 * s + c * s, y0 + r * s, s, s, 0)
        x = side + 4
    else:
        x = 2
    host = url.split("//", 1)[-1]
    ip, _, port = host.partition(":")
    f.text(x, 2, "EXTERNAL")
    f.text(x, 11, "SCREEN")
    f.text(x, 28, "SCAN")
    f.small(x, 46, ip[:16])
    f.small(x, 53, ":" + port if port else "")


def name_page(f, menu, prompt=None):
    """Naming (a project, a Wi-Fi password): the name in big letters, the letter under the cursor inverted in a
    white box (at the end: an empty box, the next letter)."""
    title = {"new": "NAME THE NEW PROJECT", "rename": "RENAME %s" % getattr(menu, "renaming", ""),
              "wifi": "PASSWORD FOR %s" % getattr(menu, "joining", "")}.get(menu.naming, "NAME THIS PROJECT")
    header(f, (prompt or title).upper()[:21])
    name = "".join(menu.name)
    per = 20
    cur = menu.cursor
    row = cur // per
    rows = max(row + 1, (len(name) + per - 1) // per, 1)
    first = max(0, min(row - 1, rows - 3))
    for r in range(first, min(rows, first + 3)):
        y = 16 + (r - first) * 11
        for k, ch in enumerate(name[r * per:(r + 1) * per]):
            x = 2 + k * 6
            if r * per + k == cur:
                f.rect(x - 1, y - 1, 7, 9, 1)
                f.text(x, y, ch, 0)
            else:
                f.text(x, y, ch)
        if r == row and cur >= len(name):                  # the cursor after the last letter
            x = 2 + (cur - r * per) * 6
            f.rect(x - 1, y - 1, 7, 9, 1)
    msg = str(getattr(menu, "msg", "") or "")
    if msg:
        f.small(1, 44, msg.upper()[:31])
    f.small(1, 51, "WHEEL: LETTER   < >: MOVE")
    f.small(1, 58, "DELETE:ERASE PLAY:OK BACK:CANCEL")


def text_page(f, s, msg=""):
    """A Pi menu screen: its texts, row by row (from top to bottom), the highlighted row inverted."""
    bar = s.get("menu_bar")
    bar_y = (bar["y"], bar["y"] + bar["h"]) if bar and bar.get("h") else None
    rows = {}
    for it in s.items:
        if it.get("type") != "text" or not it.get("t"):
            continue
        y = int(it["y"]) // 12 * 12
        rows.setdefault(y, []).append(it)
    lines, pick = [], 0
    for y in sorted(rows):
        items = sorted(rows[y], key=lambda it: it["x"])
        text = "  ".join(str(it["t"]) for it in items)
        if bar_y and any(bar_y[0] - 4 <= it["y"] <= bar_y[1] for it in items):
            pick = len(lines)
        lines.append(text.upper())
    if not lines:
        lines = ["MENU"]
    f.rect(0, 0, W, 9, 1)
    f.text(1, 1, lines[0][:21], 0)
    rest = lines[1:]
    biglist(f, rest, max(0, pick - 1), fit=5)
