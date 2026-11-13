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
TAU_BACK = 0.035                             # ... and how quickly they go back when nothing is being turned any more
LAST = {"key": None, "t": 0.0, "state": None}

_bands = {}


def _band_stroke(mask, y, xend, r, w):
    yy, xx = np.mgrid[0:H, 0:W]
    yy, xx = yy + 0.5, xx + 0.5
    cy = y + r
    d = np.sqrt((xx - xend) ** 2 + (yy - cy) ** 2)
    mask |= (abs(yy - y) <= w / 2) & (xx <= xend)                      # the run from the left edge
    mask |= (abs(d - r) <= w / 2) & (xx >= xend) & (yy <= cy)           # the rounded corner
    mask |= (abs(xx - (xend + r)) <= w / 2) & (yy >= cy)                # and down the right side


def bands(dy=0):
    """The two green bands as a picture (built once per offset): the lighter one outside, the darker one inside. dy: moved down."""
    img = _bands.get(dy)
    if img is None:
        img = np.zeros((H, W, 3), np.uint8)
        outer = np.zeros((H, W), bool)
        inner = np.zeros((H, W), bool)
        _band_stroke(outer, 72.4 + dy, 248.6, 59.5, 10.5)
        _band_stroke(inner, 85.4 + dy, 248.7, 46.4, 10.5)
        img[outer] = colour.GREENS[3]
        img[inner] = colour.GREENS[2]
        _bands[dy] = img
    return img


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


def step(state, goal, dt, snap=False, back=False):
    """Eases the settings' current values (state) toward the targets (goal)."""
    k = 1.0 if snap else 1.0 - math.exp(-dt / (TAU_BACK if back else TAU))
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


def title_line(c, title, y=45):
    """The page's name as large as fits (48 px, then 32, 24, 16), its capitals centred on y."""
    for px, tr in ((48, -6), (32, -4), (24, -3), (16, -2)):
        if text_width(c.pxfont(px), title, tr) <= W - 6 or px == 16:
            cap = c.pxfont(px).cap_h
            c.text_px(3, y + cap // 2, title, WHITE, px, tr)
            return


def by_pad_rows(items, active):
    """The first four settings go in the bottom row on screen and the next four in the top row, as the pads sit on the MPC (pads 1-4 are
    the bottom row of pads). Returns the 8 places (empty ones blank) and where `active` went."""
    out = [("", "", 0.0)] * 8
    for i, it in enumerate(items[:8]):
        out[i + 4 if i < 4 else i - 4] = it
    if active is not None:
        active = active + 4 if active < 4 else active - 4
    return out, active


def grid(nat, key, top, title, items, active, now, message=None, head=None, band_dy=0):
    """One page in this style. items = [(label, value, idle)] for up to 8 settings (two rows of four); idle = how bright (0..1) a
    setting is while none is being turned. active = the index being turned / touched, or None. key: a change of it (another page,
    another instrument) snaps everything to its place instead of easing."""
    c = nat.canvas
    c.clear((0, 0, 0))
    c.px[:] = bands(band_dy)
    n = len(items)
    if head is not None:
        head(c)
    else:
        colr = WHITE
        if message:
            top, colr = message[:24], nat.ACC
        c.text_px(6, 19, top, colr, 16, -1)
        title_line(c, title)
    texts = [(str(a).upper(), str(b).upper()) for a, b, _i in items]
    goal = targets(n, active, texts)
    for g, (_a, _b, idle) in zip(goal, items):
        if active is None:
            g["t"] = idle
    snap = LAST["key"] != key or now - LAST["t"] > 0.4 or LAST["state"] is None or len(LAST["state"]) != n
    if snap:
        LAST["state"] = [dict() for _ in range(n)]
    dt = min(0.12, max(0.0, now - LAST["t"])) if not snap else 0.0
    step(LAST["state"], goal, dt, snap, active is None)
    LAST["key"], LAST["t"] = key, now
    order = sorted(range(n), key=lambda i: i == active)             # the big one last, so nothing runs over it
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
        c.text_px(int(round(s["cx"] - text_width(c.pxfont(vs), value, vtr) / 2.0)), int(round(s["vm"] + 0.3125 * vs)), value, col, vs, vtr)


def draw(T, nat):
    """An instrument's sound page."""
    e = T.engine
    d = e.drums
    pages = T.drum_pages()
    T.drum_tab = min(T.drum_tab, len(pages) - 1)
    page_name, params = pages[T.drum_tab]
    params = params[:8]
    names = getattr(d, "names", None) or []
    voice = T.drum_voice
    vname = (names[voice] if voice < len(names) else "") or str(getattr(d, "title", ""))
    if vname == "EMPTY":
        vname = "EMPTY - PAD %d" % (voice + 1)                     # (so the screen changes as you hit pads with nothing loaded yet)
    now = nat.time.monotonic()
    active = nat._touched[-1] if nat._touched else None
    if active is None:
        newest = 0.0
        for i, _p in enumerate(params):
            when = T.drumpage.edited.get(i + 1, 0.0)
            if nat.recent(when, now) and when > newest:
                active, newest = i, when
    if active is not None and active >= len(params):
        active = None
    top = "PAGE %d/%d" % (T.drum_tab + 1, len(pages))
    if len(pages) > 1:
        top += " " + str(page_name).upper()[:12]
    octave = getattr(T, "octave", 0)
    if octave:
        top += " OCT %+d" % octave
    msg = T.message if (T.message and now < T.message_until and active is None) else None   # (while a setting is turned, its name and value are on screen)
    items = [(d.label(p), d.value_text(p), 1.0) for p in params]
    items, active = by_pad_rows(items, active)
    grid(nat, (id(d), voice, page_name, len(params)), top, vname.upper(), items, active, now, msg)


MIX = {"prev": None, "when": {}, "kind": {}}


def draw_mixer(T, nat):
    """The mixer: each instrument's level (SHIFT: its pan); muted ones are dim; the one being turned / muted grows."""
    from console import mix_pan_text
    e = T.engine
    now = nat.time.monotonic()
    cur = [(round(float(e.inst_levels[i]), 3), e.inst_pans[i], i in e.slot_mutes) for i in range(8)]
    prev = MIX["prev"]
    if prev is not None:
        for i in range(8):
            if cur[i] != prev[i]:
                MIX["when"][i] = now
                MIX["kind"][i] = "pan" if cur[i][1] != prev[i][1] else "level"
    MIX["prev"] = cur
    active = nat._touched[-1] if nat._touched else None
    if active is None:
        newest = 0.0
        for i in range(8):
            w = MIX["when"].get(i, -9.0)
            if nat.recent(w, now) and w > newest:
                active, newest = i, w
    shift = False
    try:
        shift = bool(T.shift_held())
    except Exception:
        pass
    items = []
    for i in range(8):
        mid = e.slots[i]
        if not mid:
            items.append(("%d" % (i + 1), "-", 0.25))
            continue
        name = str(T.instp.title(mid)).upper()
        muted = i in e.slot_mutes
        pan_view = shift or (now - MIX["when"].get(i, -9.0) < 1.5 and MIX["kind"].get(i) == "pan")
        if muted:
            val = "MUTE"
        elif pan_view:
            val = mix_pan_text(e.inst_pans[i])
        else:
            val = "%d" % round(max(0.0, min(1.0, float(e.inst_levels[i]))) * 100)
        items.append((name, val, 0.45 if muted else 1.0))
    if active is not None and not e.slots[active]:
        active = None
    msg = T.message if (T.message and now < T.message_until and active is None) else None
    items, active = by_pad_rows(items, active)
    grid(nat, "mixer", "KNOBS: LEVEL  SHIFT: PAN", "MIXER", items, active, now, msg)


# ------------------------------------------------------------------ a list: the selected row grows, the rest dim

LST = {"key": None, "t": 0.0, "rows": None}


def listview(nat, key, top, title, rows, focus, now, message=None, first=0):
    """rows = [(name, tag, idle)]: one row each, `focus` the selected one (24 px, white; the others 16 px and dimmer, sliding out of
    its way). tag: small text at the right (MUTE...)."""
    c = nat.canvas
    c.clear((0, 0, 0))
    c.px[:] = bands()
    colr = WHITE
    if message:
        top, colr = message[:24], nat.ACC
    c.text_px(6, 19, top, colr, 16, -1)
    title_line(c, title)
    n = len(rows)
    y, goal = 97.0, []
    for i, (_name, _tag, idle) in enumerate(rows):
        f = i == focus
        goal.append(dict(y=y, size=24 if f else 16, t=1.0 if f else idle))
        y += 28 if f else 16
    snap = LST["key"] != key or now - LST["t"] > 0.4 or LST["rows"] is None or len(LST["rows"]) != n
    if snap:
        LST["rows"] = [dict() for _ in rows]
    dt = 0.0 if snap else min(0.12, max(0.0, now - LST["t"]))
    k = 1.0 if snap else 1.0 - math.exp(-dt / TAU)
    for s, g in zip(LST["rows"], goal):
        for kk in ("y", "size", "t"):
            s[kk] = g[kk] if kk not in s or snap else s[kk] + (g[kk] - s[kk]) * k
    LST["key"], LST["t"] = key, now
    for i, (name, tag, _idle) in enumerate(rows):
        s = LST["rows"][i]
        px = max(8, int(round(s["size"] / 8.0)) * 8)
        col = colour.mix(DARK, WHITE, max(0.0, min(1.0, s["t"])))
        h = 28 if i == focus else 16
        base = int(round(s["y"] + 16 / 2.0 + 0.3125 * px)) if i != focus else int(round(s["y"] + 14 + 0.3125 * px))
        nx = 8 + int(1.25 * px)                                     # the name starts after the number
        room = 285 - nx - (c_w(c, 8, tag) + 8 if tag else 0)
        while px > 8 and text_width(c.pxfont(px), name, -(px // 8)) > room:
            px -= 8
        c.text_px(8, base, str(i + 1 + first) if name else "", col, px, 0)
        c.text_px(nx, base, name, col, px, -(px // 8))
        if tag:
            c.text_px(286 - c_w(c, 8, tag), base, tag, col, 8, 0)


def c_w(c, px, s):
    return text_width(c.pxfont(px), s, 0)


def draw_inst_list(T, nat):
    e, ip = T.engine, T.instp
    names = {}
    try:
        import instpage
        names = {m: title for m, title in instpage.machines()}
    except Exception:
        pass
    now = nat.time.monotonic()
    rows = []
    for i in range(8):
        mid = e.slots[i]
        if not mid:
            rows.append(("EMPTY", "", 0.3))
        else:
            rows.append((str(names.get(mid, mid) or "-").upper(), "MUTE" if i in e.slot_mutes else "", 0.35 if i in e.slot_mutes else 0.6))
    msg = T.message if (T.message and now < T.message_until) else None
    listview(nat, "insts", "", "INSTRUMENTS", rows, ip.row, now, msg)


# ------------------------------------------------------------------ the song page

SONG = {"prev": None, "when": {}}


def draw_song(T, nat):
    c = nat.canvas
    sg = T.song
    sg.check_song()
    now = nat.time.monotonic()
    shift = False
    try:
        shift = bool(T.shift_held())
    except Exception:
        pass
    title = "SONG " + ("ON" if sg.on else "OFF")
    if not sg.rows:
        c.clear((0, 0, 0))
        c.px[:] = bands()
        c.text_px(6, 19, "NO ROWS", WHITE, 16, -1)
        title_line(c, title)
        c.text_px(8, 124, "PRESS PAD 1 TO ADD A ROW", WHITE, 16, -1)
        for i, line in enumerate(["EACH ROW: A PATTERN PER", "INSTRUMENT, PLAYED X TIMES", "(KNOB 8). + / - : SONG ON/OFF"]):
            c.text_px(8, 150 + i * 14, line, (0x6E, 0x99, 0x3F), 8, 0)
        LST["key"] = None
        LAST["key"] = None
        return
    row = sg.rows[sg.pick]
    slots = sg.slots()
    items = []
    for i in range(7):
        if i >= len(slots):
            items.append(("", "", 0.0))
            continue
        slot = slots[i]
        v = row.get("punch", {}).get(slot) if shift else row["pats"].get(slot)
        txt = "-" if v is None else ("FX%d" if shift else "P%d") % (v + 1)
        items.append((sg.short(slot), txt, 1.0))
    items.append(("PLAYS", "X%d" % row["repeat"], 1.0))
    cur = [it[1] for it in items]
    sig = (sg.pick, shift)
    prev = SONG["prev"]
    if prev is not None and prev[0] == sig:
        for i in range(8):
            if cur[i] != prev[1][i]:
                SONG["when"][i] = now
    else:
        SONG["when"] = {}
    SONG["prev"] = (sig, cur)
    active = nat._touched[-1] if nat._touched else None
    if active is None:
        newest = 0.0
        for i in range(8):
            w = SONG["when"].get(i, -9.0)
            if nat.recent(w, now) and w > newest:
                active, newest = i, w
    if active is not None and not items[active][0]:
        active = None
    items, active = by_pad_rows(items, active)

    def head(c):
        c.text_px(6, 19, "PUNCH FX PATTERNS" if shift else "ROW %d/%d" % (sg.pick + 1, len(sg.rows)), WHITE if not shift else nat.ACC, 16, -1)
        title_line(c, title)
        for i in range(16):                                         # the rows: 16 chips, as the 16 pads
            x, y = 6 + i * 17, 97
            have = i < len(sg.rows)
            c.rect(x, y, 16, 14, colour.GREENS[3] if have else colour.GREENS[0])
            num = str(i + 1)
            c.text_px(x + 8 - c_w(c, 8, num) // 2, y + 10, num, WHITE if have else colour.GREENS[2], 8, 0)
            if i == sg.playing_row:
                c.rect(x, y + 12, 16, 2, WHITE)
            if i == sg.pick:
                c.frame(x, y, 16, 14, WHITE)
    msg = T.message if (T.message and now < T.message_until and active is None) else None
    grid(nat, ("song", sg.pick, shift), "", title, items, active, now, msg, head=head)


# ------------------------------------------------------------------ the drum sequencer

SEQ = {"prev": None, "when": {}}
SEQ_DY = 30                                                         # the green frame sits lower here: the steps are above it


def draw_seq(T, nat):
    import sequencer
    c = nat.canvas
    e = T.engine
    ms, sp, seq = T.mseq, T.seqp, e.seq
    lane = sp.lane
    ln = seq.lane(lane)
    first = ms.first()
    now = nat.time.monotonic()
    names = getattr(e.drums, "lane_names", None) or []
    name = (names[lane] if lane < len(names) else "LANE %d" % (lane + 1)).upper()
    if name == "EMPTY":
        name = "EMPTY - PAD %d" % (lane + 1)
    pat = "PAT %d" % (seq.current + 1) + (">%d" % (seq.queued + 1) if seq.queued is not None else "")
    selected = ms.held is not None
    knobs = ms.knob_list() if selected else None
    sel = set(ms.selected) if selected else set()
    at = ms.playing_step()
    blink = int(now * 3) % 2 == 0
    cur = getattr(ms, "cur", None)
    if now - SEQ.get("seen", 0) > 0.5:
        ms.cur_on = False                                       # back on this page: no box until the wheel is turned
    SEQ["seen"] = now
    msg = T.message if (T.message and now < T.message_until) else None
    hint = ""

    def head(c):
        left = (ms.which() if selected else name)[:16]
        px = 24 if text_width(c.pxfont(24), left, -3) <= 190 else 16
        c.text_px(6, 25, left, WHITE, px, -3 if px == 24 else -1)
        right = (("PAD %d" % (lane + 1)) if name.startswith("EMPTY - PAD") else name[:8]) if selected else pat
        c.text_px(314 - text_width(c.pxfont(16), right, -1), 25, right, colour.GREENS[5], 16, -1)
        if msg:
            c.text_px(6, 6, msg[:50], nat.ACC, 8, 0)
        y = 32                                                      # the steps: 17 px wide at 19 px, the height is the velocity
        for k in range(16):
            i = first + k
            x = 8 + k * 19
            if i >= ln.length or sequencer.dark(i, sequencer.TRIPLETS):
                c.rect(x + 7, y + 20, 3, 3, colour.GREENS[2])
                continue
            c.rect(x, y, 17, 40, colour.GREENS[1] if (k // 4) % 2 == 0 else colour.GREENS[0])
            st = ln.steps[i]
            is_sel = i in sel
            if st.on:
                v = st.vel if st.vel else sequencer.DEFAULT_VELOCITY
                h = max(4, int(40 * min(127, v) / 127.0))
                c.rect(x, y + 40 - h, 17, h, WHITE if is_sel else colour.GREENS[5])
            if is_sel and blink:
                c.rect(x, y, 17, 40, WHITE)
            if at is not None and i == at:
                c.rect(x, y + 42, 17, 3, WHITE)
            if not e.playing:                                       # while it plays the numbers go: less to draw, the bar moves smoother
                num = str(i + 1)
                c.text_px(x + 8 - c_w(c, 8, num) // 2, y + 54, num, WHITE if k % 4 == 0 else colour.GREENS[4], 8, 0)
        if cur is not None and getattr(ms, "cur_on", False) and first <= cur < first + 16 and cur < ln.length:
            x = 8 + (cur - first) * 19
            c.frame(x - 1, y - 1, 19, 42, WHITE)
        npages = max(1, (ln.length + 15) // 16)
        seg = (W - 16 - 4 * (npages - 1)) // npages
        for p in range(npages):
            c.rect(8 + p * (seg + 4), 91, seg, 3, WHITE if p == first // 16 else colour.GREENS[1])

    if selected and not knobs:                                      # the step settings as a grid, like the pads
        c.clear((0, 0, 0))
        c.px[:] = bands(SEQ_DY)
        head(c)
        items = ms.pad_items()
        key_lane = colour.GREENS
        for p in range(16):
            col, row = p % 4, 3 - p // 4
            x, y = 6 + col * 70, 124 + row * 29
            if p >= len(items):
                continue
            key, label = items[p]
            on = ms.engaged(key)
            c.rect(x, y, 68, 27, colour.GREENS[3] if on else colour.GREENS[0])
            c.text_px(x + 4, y + 10, str(label)[:11], WHITE if on else colour.GREENS[4], 8, 0)
            if on:
                c.text_px(x + 4, y + 22, str(ms.item_value(key))[:11], WHITE, 8, 0)
        LAST["key"] = None
        return
    if selected:
        label, value, on = knobs[0]
        key = ms.pad_items()[ms.sel][0]
        ct = ms.chance_text(key)
        items = [("K1 " + str(label)[:10], str(value), 1.0)]
        if ct is not None:
            items.append(("K2 CHANCE", ct[:9], 1.0))
        active = 0
        gkey = ("seqsel", lane, key, ct is not None)
    else:
        items = [(str(lb), str(v), 1.0) for lb, v, _l in ms.knob_list()[:4]]
        cur_vals = [it[1] for it in items]
        prev = SEQ["prev"]
        if prev is not None and prev[0] == lane:
            for i in range(len(items)):
                if i < len(prev[1]) and cur_vals[i] != prev[1][i]:
                    SEQ["when"][i] = now
        else:
            SEQ["when"] = {}
        SEQ["prev"] = (lane, cur_vals)
        active = nat._touched[-1] if nat._touched else None
        if active is None:
            newest = 0.0
            for i in range(len(items)):
                w = SEQ["when"].get(i, -9.0)
                if nat.recent(w, now) and w > newest:
                    active, newest = i, w
        if active is not None and active >= len(items):
            active = None
        gkey = ("seqlane", lane)
    if e.playing and not selected and active is None:                # playing and nothing being turned: no knob text
        items = [("", "", 1.0) for _ in items]
        gkey = gkey + ("playing",)
    items, active = by_pad_rows(items, active)
    grid(nat, gkey, "", "", items, active, now, None, head=head, band_dy=SEQ_DY)


SYN = {"prev": None, "when": {}}


def draw_synth_seq(T, nat):
    """A synth's sequencer in the drum sequencer's look: the 16 steps on top, the pattern's knobs (or the selected steps'
    settings) in the green frame."""
    import sequencer
    import notes
    c = nat.canvas
    e = T.engine
    ms, seq = T.msyn, e.seq
    first = ms.first()
    length = ms.length()
    now = nat.time.monotonic()
    pat = "PAT %d" % (seq.current + 1) + (">%d" % (seq.queued + 1) if seq.queued is not None else "")
    selected = bool(ms.selected)
    sel = set(ms.selected)
    at = ms.playing_step()
    blink = int(now * 3) % 2 == 0
    msg = T.message if (T.message and now < T.message_until) else None
    per_note = ms.lane is not None and ms.kind
    if selected:
        left = str(ms.which())
    elif per_note:
        left = "NOTE " + notes.note_name(ms.lane)
    else:
        left = "PER NOTE" if ms.kind else "UNIFIED"
    if T.live_rec and not selected:
        left = "REC " + left

    def head(c):
        px = 24 if text_width(c.pxfont(24), left[:16], -3) <= 190 else 16
        c.text_px(6, 25, left[:16].upper(), WHITE, px, -3 if px == 24 else -1)
        c.text_px(314 - text_width(c.pxfont(16), pat, -1), 25, pat, colour.GREENS[5], 16, -1)
        if msg:
            c.text_px(6, 6, msg[:50], nat.ACC, 8, 0)
        y = 32
        for k in range(16):
            i = first + k
            x = 8 + k * 19
            if i >= length or sequencer.dark(i, sequencer.TRIPLETS):
                c.rect(x + 7, y + 20, 3, 3, colour.GREENS[2])
                continue
            c.rect(x, y, 17, 40, colour.GREENS[1] if (k // 4) % 2 == 0 else colour.GREENS[0])
            here = ms.notes_at(i)
            on = (ms.lane in here) if per_note else bool(here)
            is_sel = i in sel
            if on:
                h = 40 if per_note else min(40, 16 + 8 * (len(here) - 1))   # a chord stands taller than one note
                c.rect(x, y + 40 - h, 17, h, WHITE if is_sel else colour.GREENS[5])
            if is_sel and blink:
                c.rect(x, y, 17, 40, WHITE)
            if i in ms.down:
                c.frame(x - 1, y - 1, 19, 42, WHITE)
            if at is not None and i == at:
                c.rect(x, y + 42, 17, 3, WHITE)
            if not e.playing:
                num = str(i + 1)
                c.text_px(x + 8 - c_w(c, 8, num) // 2, y + 54, num, WHITE if k % 4 == 0 else colour.GREENS[4], 8, 0)
        npages = max(1, (length + 15) // 16)
        seg = (W - 16 - 4 * (npages - 1)) // npages
        for p in range(npages):
            c.rect(8 + p * (seg + 4), 91, seg, 3, WHITE if p == first // 16 else colour.GREENS[1])

    if selected and ms.sel is None:                                 # the step settings as a grid, like the pads
        c.clear((0, 0, 0))
        c.px[:] = bands(SEQ_DY)
        head(c)
        items = ms.pad_items()
        for p in range(16):
            col, row = p % 4, 3 - p // 4
            x, y = 6 + col * 70, 124 + row * 29
            if p >= len(items):
                continue
            key, label = items[p]
            on = ms.engaged(key)
            c.rect(x, y, 68, 27, colour.GREENS[3] if on else colour.GREENS[0])
            c.text_px(x + 4, y + 10, str(label)[:11], WHITE if on else colour.GREENS[4], 8, 0)
            if on:
                c.text_px(x + 4, y + 22, str(ms.item_value(key))[:11], WHITE, 8, 0)
        LAST["key"] = None
        return
    if selected:
        key, label = ms.pad_items()[ms.sel]
        ct = ms.chance_text(key)
        items = [("K1 " + str(label)[:10], str(ms.item_value(key)), 1.0)]
        if ct is not None:
            items.append(("K2 CHANCE", str(ct)[:9], 1.0))
        active = 0
        gkey = ("synsel", key, ct is not None)
    else:
        items = [(str(lb), str(v), 1.0) for lb, v, _x in ms.knob_list()[:8]]
        cur_vals = [it[1] for it in items]
        prev = SYN["prev"]
        if prev is not None and len(prev) == len(cur_vals):
            for i in range(len(items)):
                if cur_vals[i] != prev[i]:
                    SYN["when"][i] = now
        else:
            SYN["when"] = {}
        SYN["prev"] = cur_vals
        active = nat._touched[-1] if nat._touched else None
        if active is None:
            newest = 0.0
            for i in range(len(items)):
                w = SYN["when"].get(i, -9.0)
                if nat.recent(w, now) and w > newest:
                    active, newest = i, w
        if active is not None and active >= len(items):
            active = None
        gkey = ("synlane", len(items))
    items, active = by_pad_rows(items, active)
    grid(nat, gkey, "", "", items, active, now, None, head=head, band_dy=SEQ_DY)
