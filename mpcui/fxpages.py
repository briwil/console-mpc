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
            if now - w < 1.0 and w > newest:
                active, newest = i, w
    if active is not None and active >= len(vals):
        active = None
    return active


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
        knob_page(T, nat, ("sends", e.slot), "SLOT %d" % (e.slot + 1), "SENDS", pairs)
        return
    pos = ml.insert_pos()
    if pos is not None:
        ins = T.insfx(None, pos)
        pairs = []
        for i in range(8):
            label, shown = ins.text(i)
            pairs.append((label, shown if label else ""))
        top = "SLOT %d" % (ins.slot + 1)
        if ins.error:
            top = str(ins.error)[:24]
        knob_page(T, nat, ("insert", pos, ins.name()), top, ins.name().upper()[:14] or "INSERT %d" % (pos + 1), pairs)
        return
    pairs = [(a, b) for a, b in ml.values()]
    knob_page(T, nat, ("lfo", ml.tab), "PAT %d" % (e.seq.current + 1), "LFO %d" % (ml.tab + 1), pairs)


def on_lfo_page(T, menu):
    """LFO 1 / 2, INSERT 1 / 2 and SENDS (not the arp or pads pages, the effect picker or the sample browser)."""
    if menu is not None and (menu.open or menu.kits.open):
        return False
    try:
        if T.fx_page or T.seq_page or not T.drum_page or T.sbrowse.active:
            return False
        ml = T.mlfo
        if not ml.active() or ml.arp_on_page() or ml.pads_on_page():
            return False
        if ml.insert_pos() is not None and T.fxpick.active:
            return False
        return T.engine is not None and T.engine.drums is not None
    except Exception:
        return False


# ------------------------------------------------------------------ PRESETS

def draw_presets(T, nat):
    pr = T.presets
    pr.sync()
    n = pr.total()
    now = nat.time.monotonic()
    bank = pr.bank_label()
    top = ("BANK " + str(bank).upper())[:24] if bank else ""
    right = "%d/%d" % (pr.pos + 1, n) if n else ""
    msg = _msg(T, now)
    if not n:
        rows = [("NO PRESETS YET", "", 0.45), ("MENU > SAVE PRESET", "", 0.3)]
        sp.listview(nat, "presets-none", top, "PRESETS", rows, 0, now, msg)
        return
    shown = 7
    first = max(0, min(pr.pos - shown // 2, n - shown))
    rows = []
    for i in range(first, min(n, first + shown)):
        lab = str(pr.label(i)).upper()
        tag = ""
        if lab.startswith("*"):                       # yours: a star in front
            lab, tag = lab.lstrip("* "), "MINE"
        rows.append((lab[:24], tag, 0.55))
    if not msg and pr.orig is not None:
        msg = "KEPT? PUSH: YES  BACK: UNDO"
    sp.listview(nat, ("presets", bank), top or right, "PRESETS", rows, pr.pos - first, now, msg, first)
    c = nat.canvas
    if top and right:
        c.text_px(314 - text_width(c.pxfont(16), right, -1), 19, right, G[5], 16, -1)


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

def _strip(c, first, length, on, at, held, dark, tails=(), long_=()):
    y = 32
    for k in range(16):
        i = first + k
        x = 8 + k * 19
        if i >= length or dark(i):
            c.rect(x + 7, y + 20, 3, 3, G[2])
            continue
        c.rect(x, y, 17, 40, G[1] if (k // 4) % 2 == 0 else G[0])
        if i in on:
            c.rect(x, y + 6, 17, 34, WHITE if i == held else G[5])
            if i in long_:
                c.rect(x + 17, y + 18, 2, 8, G[5])
        elif i in tails:
            c.rect(x - 2, y + 18, 21, 8, G[3])
        if i == held:
            c.frame(x - 1, y - 1, 19, 42, WHITE)
        if at is not None and i == at:
            c.rect(x, y + 42, 17, 3, WHITE)
        num = str(i + 1)
        c.text_px(x + 8 - c_w(c, 8, num) // 2, y + 54, num, WHITE if k % 4 == 0 else G[4], 8, 0)
    npages = max(1, (length + 15) // 16)
    seg = (sp.W - 16 - 4 * (npages - 1)) // npages
    for p in range(npages):
        c.rect(8 + p * (seg + 4), 91, seg, 3, WHITE if p == first // 16 else G[1])


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
        if strip_args is not None:
            _strip(c, **strip_args)

    items = [(str(a), str(b), 1.0) for a, b in pairs]
    active = _active(T, nat, key, [it[1] for it in items])
    items, active = sp.by_pad_rows(items, active)
    sp.grid(nat, key, "", "", items, active, now, None, head=head, band_dy=sp.SEQ_DY)


def draw_auto(T, nat):
    a, e = T.auto, T.engine
    if T.synth_shown():
        name = (e.slots[e.slot] or "").upper() if e.slot is not None else ""
    else:
        names = getattr(e.drums, "lane_names", None) or []
        lane = T.seqp.lane
        name = names[lane] if lane < len(names) else "LANE %d" % (lane + 1)
        if name == "EMPTY":
            name = "DRUM %d" % (lane + 1)
    name = str(name).upper()[:10]
    key = a.key()
    msg = _msg(T, nat.time.monotonic())
    if key is None:
        _steps_page(T, nat, ("auto-none",), "NO AUTOMATION", name,
                    msg or "RECORD + KNOBS WHILE PLAYING, OR SHIFT + STEPS", None, [])
        return
    import sequencer
    on = a.steps_with(key)
    length = a.length(key)
    first = a.page * 16
    if a.confirming():
        msg = "TAKE %s OFF %d STEPS?  SHIFT + DELETE AGAIN" % (a.label(key)[:10].upper(), len(on))
    pairs = [("SETTING", a.label(key).upper()[:12]), ("LENGTH", str(length))]
    if a.held is not None and a.held in on:
        pairs[0] = ("STEP %d" % (a.held + 1), a.value_text(a.held, key))
    args = dict(first=first, length=length, on=on, at=a.playing_step(), held=a.held,
                dark=lambda i: sequencer.dark(i, sequencer.TRIPLETS))
    _steps_page(T, nat, ("auto", key), a.label(key).upper()[:14], "%d/%d" % (a.pick + 1, len(a.keys())), msg, args, pairs)


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
    pairs = [("LENGTH", str(ln.length)), ("RATE", str(pu.rate_name()))] + [("", "")] * 5 + [("SCALE", "X%d" % punch.SCALES[st.pattern.scale])]
    if pu.held is not None and pu.held in ln.steps:
        L = ln.lens.get(pu.held, 1)
        pairs[0] = ("CHANCE", str(sequencer.CHANCES[ln.steps[pu.held]]))
        pairs[1] = ("STEP %d" % (pu.held + 1), "%d LONG" % L if L > 1 else "1 STEP")
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
