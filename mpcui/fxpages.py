"""Native 320x240 pages for the instrument's other screens, in the sound page's look: LFO 1 / 2, INSERT 1 / 2, SENDS (the green frame with
the settings as a grid), PRESETS (the list), AUTOMATION and PUNCH FX (the steps above the grid, like the sequencer)."""
import colour
import soundpage as sp
from soundpage import WHITE, c_w, text_width

G = colour.GREENS
SEEN = {}


def _active(T, nat, key, vals):
    """The setting being turned: the one a knob pad is held on, or the one that changed in the last second."""
    now = nat.time.monotonic()
    prev = SEEN.get("prev")
    if prev is not None and prev[0] == key:
        for i, v in enumerate(vals):
            if i < len(prev[1]) and v != prev[1][i]:
                SEEN.setdefault("when", {})[i] = now
    else:
        SEEN["when"] = {}
    SEEN["prev"] = (key, list(vals))
    active = nat._touched[-1] if nat._touched else None
    if active is None:
        newest = 0.0
        for i in range(len(vals)):
            w = SEEN["when"].get(i, -9.0)
            if nat.recent(w, now) and w > newest:
                active, newest = i, w
    if active is not None and active >= len(vals):
        active = None
    return active


def _guitar(T):
    """True while the shown instrument is GUITAR (no patterns there)."""
    try:
        e = T.engine
        return bool(getattr(e.drums.get(e.slots[e.slot]), "live_input", False))
    except Exception:                                    # noqa: BLE001
        return False


def _msg(T, now):
    return T.message if (T.message and now < T.message_until) else None


def knob_page(T, nat, key, top, title, pairs):
    """pairs = [(label, value)] for up to 8 knobs."""
    now = nat.time.monotonic()
    items = [(str(a), str(b), 1.0) for a, b in pairs[:8]]
    active = _active(T, nat, key, [it[1] for it in items])
    items, active = sp.by_pad_rows(items, active)
    sp.grid(nat, key, top, title, items, active, now, _msg(T, now))


# ------------------------------------------------------------------ LFO / INSERT / SENDS

def draw_lfo(T, nat):
    ml, e = T.mlfo, T.engine
    if ml.sends_on_page():
        pairs = [(a.replace("SONG ", ""), b) for a, b in ml.sends_values()]
        knob_page(T, nat, ("sends", e.slot), "REVERB, DELAY, SONG INSERTS", "SENDS", pairs)
        return
    if ml.pads_on_page():
        knob_page(T, nat, ("pads", e.slot), "SLOT %d" % (e.slot + 1), "PADS", [(a, b) for a, b in ml.pads_values()])
        return
    if ml.arp_on_page():
        cfg = ml.cfg()

        def rhythm(c):                                  # the 16 steps: rest dark, note half, accent full
            for k, r in enumerate(cfg["rhythm"][:16]):
                x = 8 + k * 19
                c.rect(x, 32, 17, 40, G[1] if (k // 4) % 2 == 0 else G[0])
                if r == 1:
                    c.rect(x, 52, 17, 20, G[5])
                elif r == 2:
                    c.rect(x, 32, 17, 40, WHITE)
                num = str(k + 1)
                c.text_px(x + 8 - c_w(c, 8, num) // 2, 86, num, WHITE if k % 4 == 0 else G[4], 8, 0)
        msg = _msg(T, nat.time.monotonic())
        _steps_page(T, nat, ("arp", ml.arp_second()), "ARP 2" if ml.arp_second() else "ARP", "ON" if cfg["on"] else "OFF",
                    msg, rhythm, [(a, b) for a, b in ml.arp_values()])
        return
    pos = ml.insert_pos()
    if pos is not None:
        ins = T.insfx(None, pos)
        pairs = []
        for i in range(8):
            label, shown = ins.text(i)
            pairs.append((label, shown if label else ""))
        top = "INSERT %d" % (pos + 1)
        if ins.error:
            top = str(ins.error)[:24]
        knob_page(T, nat, ("insert", pos, ins.name()), top, ins.name().upper()[:14] or "NO EFFECT", pairs)
        return
    pairs = [(a, b) for a, b in ml.values()]
    knob_page(T, nat, ("lfo", ml.tab), "GUITAR" if _guitar(T) else "PAT %d" % (e.seq.current + 1), "LFO %d" % (ml.tab + 1), pairs)


POP = {"key": None, "t": 0.0, "state": None}
POP_COLS = [38.0, 100.0, 162.0, 224.0]               # the panel's four columns
POP_LABEL = [118.0, 166.0]                            # label baselines of the two rows
POP_VALUE = [136.0, 184.0]                            # the middle of a 16 px value in each row


def _pop_targets(n, active):
    """The instrument settings page's easing, in the panel: each setting's place; the one being turned grows and pushes the rest aside."""
    out = []
    ra, ca = (active // 4, active % 4) if active is not None else (None, None)
    for i in range(n):
        r, c = i // 4, i % 4
        cx = POP_COLS[c]
        if active is None:
            out.append(dict(cx=cx, lb=POP_LABEL[r], vm=POP_VALUE[r], ls=8, vs=16, t=1.0))
        elif i == active:
            out.append(dict(cx=cx + 12.0, lb=POP_VALUE[r] - 14.0, vm=POP_VALUE[r] + 8.0, ls=16, vs=32, t=1.0))
        else:
            if c < ca:
                cx -= 4.0
            elif r == ra and c > ca:
                cx += 22.0
            elif r != ra and ra == 1 and c >= ca:
                cx += 40.0
            out.append(dict(cx=cx, lb=POP_LABEL[r], vm=POP_VALUE[r], ls=8, vs=16, t=0.0))
    return out


def _pop_settings(T, nat, key, vals):
    """The settings of a pop-up, as on an instrument's settings page: in the pads' order, and the one you turn grows."""
    c = nat.canvas
    now = nat.time.monotonic()
    active = _active(T, nat, key, [str(v[1]) for v in vals])
    items, active = sp.by_pad_rows([(str(a_).upper(), str(b_).upper(), 1.0) for a_, b_ in vals], active)
    n = len(items)
    goal = _pop_targets(n, active)
    snap = POP["key"] != key or now - POP["t"] > 0.4 or POP["state"] is None or len(POP["state"]) != n
    if snap:
        POP["state"] = [dict() for _ in range(n)]
    dt = min(0.12, max(0.0, now - POP["t"])) if not snap else 0.0
    sp.step(POP["state"], goal, dt, snap, active is None)
    POP["key"], POP["t"] = key, now
    for i in sorted(range(n), key=lambda i: i == active):                       # the big one last
        label, value, _idle = items[i]
        if not label:
            continue
        st = POP["state"][i]
        col = sp.colour.mix(sp.DARK, WHITE, max(0.0, min(1.0, st["t"])))
        room = 78 if active == i else 56
        ls = sp.fit_size(c.pxfont, label, [px for px in (16, 8) if px <= max(8, int(round(st["ls"] / 8.0)) * 8)], room, lambda px: 0)
        if text_width(c.pxfont(ls), label, 0) > room:
            label = label[:max(2, room // 6)]
        vs = sp.fit_size(c.pxfont, value, [px for px in (32, 24, 16, 8) if px <= max(8, int(round(st["vs"] / 8.0)) * 8)], room,
                         lambda px: -px // 8)
        c.text_px(int(round(st["cx"] - text_width(c.pxfont(ls), label, 0) / 2.0)), int(round(st["lb"])), label, col, ls, 0)
        vtr = -(vs // 8)
        c.text_px(int(round(st["cx"] - text_width(c.pxfont(vs), value, vtr) / 2.0)), int(round(st["vm"] + 0.3125 * vs)), value, col, vs, vtr)


def draw_pads_popup(T, nat):
    """The PADS pop-up (PAD FX): a small panel over the page you are on, with the pads' settings (a synth: key, scale, octave, velocity,
    curve; a drum machine: octave, velocity, curve). PLUS / MINUS and knob 3 change the octave."""
    c = nat.canvas
    ml = T.mlfo
    x0, y0, w, h = 8, 68, 304, 152
    c.rect(x0 - 2, y0 - 2, w + 4, h + 4, WHITE)
    c.rect(x0, y0, w, h, (14, 16, 14))
    c.text_px(x0 + 10, y0 + 28, "PADS", WHITE, 24, -3)
    _pop_settings(T, nat, ("pads-pop", ml.has_arp()), ml.pads_values())
    msg = _msg(T, nat.time.monotonic())
    if msg:
        c.text_px(x0 + 10, y0 + 8, msg[:44], nat.ACC, 8, 0)


def draw_arp_popup(T, nat):
    """The ARP pop-up: a panel over the page you are on (not a page of its own). The 16 steps of the rhythm on top, the settings below
    as on an instrument's settings page: in the pads' order (settings 1-4 in the bottom row, 5-8 above), and the one you turn grows."""
    c = nat.canvas
    ml = T.mlfo
    cfg = ml.cfg()
    second = ml.arp_second()
    now = nat.time.monotonic()
    x0, y0, w, h = 8, 20, 304, 200
    c.rect(x0 - 2, y0 - 2, w + 4, h + 4, WHITE)
    c.rect(x0, y0, w, h, (14, 16, 14))
    on = "ON" if cfg["on"] else "OFF"
    c.text_px(x0 + 10, y0 + 28, "ARP 2" if second else "ARP", WHITE, 24, -3)
    c.text_px(x0 + w - 10 - text_width(c.pxfont(16), on, -1), y0 + 26, on, WHITE if cfg["on"] else G[3], 16, -1)
    for k, r in enumerate(cfg["rhythm"][:16]):                                 # the 16 steps: rest dark, note half, accent full
        x = x0 + 10 + k * 18
        c.rect(x, y0 + 38, 16, 30, G[1] if (k // 4) % 2 == 0 else G[0])
        if r == 1:
            c.rect(x, y0 + 53, 16, 15, G[5])
        elif r == 2:
            c.rect(x, y0 + 38, 16, 30, WHITE)
        num = str(k + 1)
        c.text_px(x + 8 - c_w(c, 8, num) // 2, y0 + 80, num, WHITE if k % 4 == 0 else G[4], 8, 0)
    _pop_settings(T, nat, ("arp-pop", second), ml.arp_values())
    msg = _msg(T, now)
    if msg:
        c.text_px(x0 + 10, y0 + 8, msg[:44], nat.ACC, 8, 0)


def on_fx_page(T, menu):
    """REVERB, DELAY and SONG INSERT 1 / 2 (not the mixer, and not while the effect picker is up)."""
    if menu is not None and (menu.open or menu.kits.open):
        return False
    try:
        if T.engine is None or T.fx_page not in ("reverb", "delay", "song1", "song2"):
            return False
        return not (T.fx_page in ("song1", "song2") and T.fxpick.active)
    except Exception:
        return False


def draw_fx(T, nat):
    which = T.fx_page
    if which in ("song1", "song2"):
        p = 0 if which == "song1" else 1
        sf = T.songfx(p)
        pairs = []
        for i in range(8):
            label, shown = sf.text(i)
            pairs.append((label, shown if label else ""))
        top = str(sf.error).upper()[:24] if sf.error else "SONG INSERT %d" % (p + 1)
        knob_page(T, nat, ("songfx", p, sf.name()), top, str(sf.name()).upper()[:14] or "NONE", pairs)
        return
    pairs = [(name, str(T.fx_value_text(key)).upper()) for key, name in T.FX_KNOBS[which]]
    knob_page(T, nat, ("fx", which), "SEND FX", which.upper(), pairs)


def on_lfo_page(T, menu):
    """LFO 1 / 2, INSERT 1 / 2, SENDS, ARP and PADS (not the effect picker or the sample browser)."""
    if menu is not None and (menu.open or menu.kits.open):
        return False
    try:
        if T.fx_page or T.seq_page or not T.drum_page or T.sbrowse.active:
            return False
        ml = T.mlfo
        if not ml.active():
            return False
        if ml.insert_pos() is not None and T.fxpick.active:
            return False
        return T.engine is not None and T.engine.drums is not None
    except Exception:
        return False


# ------------------------------------------------------------------ PRESETS

def _fit(c, s, sizes, room):
    """(px, text): the largest of sizes at which s fits in room px (cut short at the smallest if it never does)."""
    for px in sizes:
        if text_width(c.pxfont(px), s, -(px // 8)) <= room:
            return px, s
    px = sizes[-1]
    while len(s) > 1 and text_width(c.pxfont(px), s, -(px // 8)) > room:
        s = s[:-1]
    return px, s


def _preset_name(pr, i):
    lab = str(pr.label(i)).upper()
    mine = lab.startswith("*")
    lab = lab.lstrip("*+ ")
    return (lab if not lab.isdigit() else "PRESET " + lab), mine


def draw_presets(T, nat):
    """A box with the preset you're on; with the list open (mpcui/presetpop.py) the list over it."""
    import presetpop
    pr = T.presets
    pr.sync()
    n = pr.total()
    now = nat.time.monotonic()
    bank = pr.bank_label()
    msg = _msg(T, now)
    c = nat.canvas
    c.clear((0, 0, 0))
    c.px[:] = sp.bands()
    top = ("BANK " + str(bank).upper())[:24] if bank else "SLOT %d" % (T.engine.slot + 1)
    c.text_px(6, 19, msg[:24] if msg else top, nat.ACC if msg else WHITE, 16, -1)
    sp.title_line(c, "PRESETS")
    name, mine = _preset_name(pr, pr.pos) if n else ("NONE", False)
    c.text_px(8, 108, "PRESET", G[5], 8, 0)
    count = "%d/%d" % (pr.pos + 1, n) if n else ""
    c.text_px(284 - c_w(c, 8, count), 108, count, G[5], 8, 0)
    c.rect(8, 114, 304, 44, (0, 0, 0))
    c.frame(8, 114, 304, 44, WHITE)
    px, shown = _fit(c, name, (24, 16), 288)
    c.text_px(16, 136 + int(0.3125 * px) + 1, shown, WHITE, px, -(px // 8))
    if mine:
        c.text_px(284 - c_w(c, 8, "MINE"), 170, "MINE", G[5], 8, 0)
    if not (presetpop.is_open() and n):
        return
    # the list, over the page
    c.rect(12, 24, 296, 190, (0, 0, 0))
    c.frame(12, 24, 296, 190, WHITE)
    c.text_px(20, 44, "PRESETS", WHITE, 16, -1)
    c.text_px(300 - text_width(c.pxfont(16), count, -1), 44, count, G[5], 16, -1)
    c.rect(12, 50, 296, 1, WHITE)
    shown_n = 7
    first = max(0, min(pr.pos - shown_n // 2, n - shown_n))
    for k, i in enumerate(range(first, min(n, first + shown_n))):
        y = 54 + k * 22
        nm, mn = _preset_name(pr, i)
        tag = "MINE" if mn else ""
        room = 272 - (c_w(c, 8, tag) + 8 if tag else 0)
        _px, nm = _fit(c, nm, (16,), room)
        on = i == pr.pos
        if on:
            c.rect(16, y, 288, 20, WHITE)
        col = (0, 0, 0) if on else G[6]
        c.text_px(22, y + 16, nm, col, 16, -2)
        if tag:
            c.text_px(298 - c_w(c, 8, tag), y + 13, tag, col, 8, 0)


def on_presets_page(T, menu):
    if menu is not None and (menu.open or menu.kits.open):
        return False
    try:
        if T.fx_page or T.seq_page or not T.drum_page or T.sbrowse.active:
            return False
        if T.punch.active() or T.auto.active() or T.mlfo.active():
            return False
        return T.presets.on_page() and T.engine is not None
    except Exception:
        return False


# ------------------------------------------------------------------ steps (AUTOMATION, PUNCH FX)

def _strip(c, first, length, on, at, held, dark, tails=(), long_=(), x0=8, pitch=19, wd=17, y=32, hh=40, bar_y=91, bar_x=8, bar_w=None, fracs=None):
    hl = set(held) if isinstance(held, (set, list, tuple)) else {held}
    for k in range(16):
        i = first + k
        x = x0 + k * pitch
        if i >= length or dark(i):
            c.rect(x + wd // 2 - 1, y + hh // 2, 3, 3, G[2])
            continue
        c.rect(x, y, wd, hh, G[1] if (k // 4) % 2 == 0 else G[0])
        if i in on and fracs is not None:                       # a bar as high as the step's value
            bh = max(3, int(round(hh * max(0.0, min(1.0, fracs.get(i, 1.0))))))
            c.rect(x, y + hh - bh, wd, bh, WHITE if i in hl else G[5])
        elif i in on:
            c.rect(x, y + 6, wd, hh - 6, WHITE if i in hl else G[5])
            if i in long_:
                c.rect(x + wd, y + hh // 2 - 2, 2, 8, G[5])
        elif i in tails:
            c.rect(x - 2, y + hh // 2 - 2, wd + 4, 8, G[3])
        if i in hl:
            c.frame(x - 1, y - 1, wd + 2, hh + 2, WHITE)
        if at is not None and i == at:
            c.rect(x, y + hh + 2, wd, 3, WHITE)
        num = str(i + 1)
        c.text_px(x + wd // 2 - c_w(c, 8, num) // 2, y + hh + 14, num, WHITE if k % 4 == 0 else G[4], 8, 0)
    npages = max(1, (length + 15) // 16)
    bar_w = bar_w or (sp.W - 16)
    seg = (bar_w - 4 * (npages - 1)) // npages
    for p in range(npages):
        c.rect(bar_x + p * (seg + 4), bar_y, seg, 3, WHITE if p == first // 16 else G[1])


def _steps_page(T, nat, key, left, right, msg, strip_args, pairs):
    c = nat.canvas
    now = nat.time.monotonic()

    def head(c):
        px = 24 if text_width(c.pxfont(24), left, -3) <= 200 else 16
        c.text_px(6, 25, left, WHITE, px, -3 if px == 24 else -1)
        if right:
            c.text_px(314 - text_width(c.pxfont(16), right, -1), 25, G[5], 16, -1) if False else \
                c.text_px(314 - text_width(c.pxfont(16), right, -1), 25, right, G[5], 16, -1)
        if msg:
            c.text_px(6, 6, msg[:50], nat.ACC, 8, 0)
        if callable(strip_args):
            strip_args(c)
        elif strip_args is not None:
            _strip(c, **strip_args)

    items = [(str(a), str(b), 1.0) for a, b in pairs]
    active = _active(T, nat, key, [it[1] for it in items])
    if active is not None and active < len(items) and not items[active][0]:
        active = None                                   # a pad with no setting on it: nothing grows, nothing fades
    items, active = sp.by_pad_rows(items, active)
    sp.grid(nat, key, "", "", items, active, now, None, head=head, band_dy=sp.SEQ_DY)


def _auto_list(T, nat, a, key, view, focus, first, title, msg):
    sp.listview(nat, key, "", title, view, focus, nat.time.monotonic(), msg, first)


def draw_auto(T, nat):
    """AUTOMATION: a list of the settings that have steps (8 rows to start: EMPTY ones open a picker of everything that can be set); a
    setting opens as a pop-up with its steps and the value to change."""
    import sequencer
    a = T.auto
    now = nat.time.monotonic()
    msg = _msg(T, now)
    if a.mode == "pick":
        n = len(a.items)
        first = max(0, min(a.prow - 3, n - 8))
        view = [(str(lbl).upper(), "", 0.6) for _k, lbl in a.items[first:first + 8]]
        _auto_list(T, nat, a, "auto-pick", view, a.prow - first, first, "PICK A SETTING", msg)
        return
    rows = a.rows()
    shown = a.shown()
    first = max(0, min(a.row - 3, shown - 8))
    view = []
    for idx in range(first, min(shown, first + 8)):
        if idx < len(rows):
            k = rows[idx]
            view.append((str(a.label(k)).upper(), "%d STEPS" % len(a.steps_with(k)), 0.6))
        else:
            view.append(("EMPTY", "", 0.3))
    if a.mode == "list":
        title = "AUTOMATION"
        if a.confirming():
            msg = "TAKE IT OFF EVERY STEP?  SHIFT + DELETE AGAIN"
        _auto_list(T, nat, a, "auto-list", view, a.row - first, first, title, msg)
        return
    _auto_list(T, nat, a, "auto-list", view, a.row - first, first, "AUTOMATION", None)      # (the list stays under the pop-up)
    c = nat.canvas
    key = a.key()
    if key is None:
        return
    x0, y0, w, h = 8, 20, 304, 200
    c.rect(x0 - 2, y0 - 2, w + 4, h + 4, WHITE)
    c.rect(x0, y0, w, h, (14, 16, 14))
    label = str(a.label(key)).upper()
    px = 24 if text_width(c.pxfont(24), label, -3) <= 200 else 16
    c.text_px(x0 + 10, y0 + 28, label, WHITE, px, -3 if px == 24 else -1)
    length = a.length(key)
    on = a.steps_with(key)
    pg = "%d/%d" % (a.page + 1, max(1, (length + 15) // 16))
    c.text_px(x0 + w - 10 - text_width(c.pxfont(16), pg, -1), y0 + 26, pg, G[5], 16, -1)
    hl = set(a.selected)
    if a.held is not None:
        hl.add(a.held)
    if a.cur is not None:
        hl.add(a.cur)
    _strip(c, a.page * 16, length, on, a.playing_step(), hl, lambda i: sequencer.dark(i, sequencer.TRIPLETS),
           x0=x0 + 10, pitch=18, wd=16, y=y0 + 40, hh=32, bar_y=y0 + 96, bar_x=x0 + 10, bar_w=w - 20,
           fracs={i: a.fraction(i, key) for i in on})
    targets = a.targets()
    value = str(a.value_text(targets[0], key)).upper() if targets else "-"
    if len(targets) > 1:
        value = value + " (%d)" % len(targets)
    lane = "%d" % length if a.rec(key) else "-"
    _pop_settings(T, nat, ("auto-pop", key), [("VALUE", value), ("LENGTH", lane)])          # pad 1 and pad 2, as in the other pop-ups
    if msg:
        c.text_px(x0 + 10, y0 + 8, msg[:44], nat.ACC, 8, 0)


def draw_punch(T, nat):
    import punch
    import sequencer
    pu = T.punch
    st, ln = pu.st(), pu.ln()
    head = "FX%d" % (st.current + 1) + (">%d" % (st.queued + 1) if st.queued is not None else "")
    now_fx = pu.now() or pu.held_mask()
    msg = _msg(T, nat.time.monotonic())
    if pu.confirming():
        msg = "CLEAR PUNCH PATTERN %d?  SHIFT + DELETE AGAIN" % (st.current + 1)
    trip = pu.trip()
    ca = pu.chance_all(ln)
    chance = ("CHANCE", str(sequencer.CHANCES[ca]) if ca is not None else ("MIXED" if ln.steps else "-"))
    pairs = [("LENGTH", str(ln.length)), ("RATE", str(pu.rate_name())), chance] + [("", "")] * 4 + [("SCALE", "X%d" % punch.SCALES[st.pattern.scale])]
    if pu.held is not None and pu.held in ln.steps:
        L = ln.lens.get(pu.held, 1)
        pairs[0] = ("CHANCE", str(sequencer.CHANCES[ln.steps[pu.held]]))
        pairs[1] = ("STEP %d" % (pu.held + 1), "%d LONG" % L if L > 1 else "1 STEP")
        pairs[2] = ("", "")
    args = dict(first=pu.page * 16, length=ln.length, on=set(ln.steps), at=pu.playing_step(), held=pu.held,
                dark=lambda i: sequencer.dark(i, trip), tails=punch.covered(ln, trip),
                long_={i for i in ln.steps if ln.lens.get(i, 1) > 1})
    right = head if not now_fx else str(punch.label(now_fx, short=True))[:8]
    _steps_page(T, nat, ("punch", pu.lane), str(punch.NAMES[pu.lane]).upper()[:14], right, msg, args, pairs)


def on_auto_page(T, menu):
    if menu is not None and (menu.open or menu.kits.open):
        return False
    try:
        return not T.fx_page and T.seq_page and T.auto.active() and not T.punch.active() and T.engine is not None
    except Exception:
        return False


def on_punch_page(T, menu):
    if menu is not None and (menu.open or menu.kits.open):
        return False
    try:
        return not T.fx_page and T.seq_page and T.punch.active() and T.engine is not None
    except Exception:
        return False
