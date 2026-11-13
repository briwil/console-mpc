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
        if callable(strip_args):
            strip_args(c)
        elif strip_args is not None:
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
