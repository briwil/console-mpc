"""ENDLESS on the MPC: its page, its controls, and where it's picked (see endless.py for what it does).

Installed by mpc_app.py over Console's board (after stepentry and the others, before the leave menu), over pots.target (K1-K3 by
position), over the ARP pop-up's second page (SEQUENCER, a synth's) and the PADS pop-up (SEQUENCER, a drum machine's), and over
native.py's page drawing."""
import time

import endless
import knobgate
import sequencer
import arp

RIGHT, LEFT, PLUS, MINUS, RECORD, WHEEL, PUSH = 63, 62, 55, 54, 86, 14, 3
DELETE = 119
KNOB_CLICKS = range(71, 79)
STATE = {"erase_at": 0.0, "notes": {}, "seen": 0.0}


# ------------------------------------------------------------------ where we are

def shown_seq(T):
    e = T.engine
    if e is None or e.slot is None or not e.slots[e.slot]:
        return None
    return e.seq


def is_synth(T):
    try:
        return bool(T.synth_shown())
    except Exception:                                                  # noqa: BLE001
        return False


def on_page(T, menu=None):
    """The instrument's sequencer page, and the instrument plays ENDLESS."""
    try:
        if menu is not None and (menu.open or menu.kits.open):
            return False
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return False
        if not T.seq_page or T.fx_page or T.inst_page or getattr(T, "song_page", False) or T.engine is None:
            return False
        if T.punch.active() or T.auto.active() or getattr(T, "arp_pop", 0) or getattr(T, "pads_pop", 0):
            return False
        if T.guitar_shown():
            return False
        seq = shown_seq(T)
        return seq is not None and endless.active(seq)
    except Exception:                                                  # noqa: BLE001
        return False


def say(T, text):
    try:
        T.say(text, 2)
    except Exception:                                                  # noqa: BLE001
        pass


def changed(T):
    try:
        T.engine.seq_changed()
    except Exception:                                                  # noqa: BLE001
        pass


# ------------------------------------------------------------------ the settings (K1-K3, Shift + K1-K3)

def values(en):
    return [("RATE", sequencer.RATES[en.rate][0]), ("DIRECTION", endless.DIRECTIONS[en.direction]), ("SWING", "%d%%" % en.swing),
            ("STYLE", arp.STYLES[en.style]), ("HOLD", "ON" if en.hold else "OFF"), ("GATE", "%d%%" % en.gate)]


def set_by_pot(T, n, val):
    """K1-K3 (n 1-3) by position; with Shift, the second three."""
    import pots
    seq = shown_seq(T)
    en = endless.of(seq)
    shift = bool(getattr(T, "shift_held", lambda: False)())
    k = n - 1 + (3 if shift else 0)
    if k == 0:
        en.rate = pots.zone(val, len(sequencer.RATES))
    elif k == 1:
        en.direction = pots.zone(val, len(endless.DIRECTIONS))
    elif k == 2:
        en.swing = 50 + int(round(pots.frac(val) * 25))
    elif k == 3:
        en.style = pots.zone(val, len(arp.STYLES))
    elif k == 4:
        en.hold = pots.zone(val, 2)
        if not en.hold and not en.held:
            en.transpose = 0
    elif k == 5:
        en.gate = 10 + int(round(pots.frac(val) * 190))
    STATE["active"] = (k, time.monotonic())
    changed(T)
    say(T, "%s  %s" % values(en)[k])


# ------------------------------------------------------------------ the keys on its page

def _note_of(T, board, p):
    """The note a synth's pad plays (as Console's pads do), or a drum machine's drum (its left 4 x 4), or None."""
    e = T.engine
    seq = e.seq
    if is_synth(T):
        try:
            base = seq.note_row(seq.shown_notes()[0])
            note = seq.row_note(base + p)
        except Exception:                                              # noqa: BLE001
            note = 48 + p
        return max(0, min(127, note + 12 * getattr(T, "octave", 0)))
    r, c = divmod(p, 8)
    if c >= 4:
        return None
    lane = r * 4 + c
    d = e.drums
    return lane if d is not None and lane < d.lanes else None


def key(T, board, num, val):
    """A control on its page. True when used here."""
    seq = shown_seq(T)
    en = endless.of(seq)
    shift = board.shift
    if num == RECORD:
        if val:
            en.entry = not en.entry
            say(T, "ENTRY ON: THE PADS ADD NOTES" if en.entry else "ENTRY OFF")
        return True
    if num in (RIGHT, PLUS):
        if val:
            if num == PLUS or shift:
                ok = en.add(seq, ["t"])
                say(T, "LONGER" if ok else "NO NOTE TO HOLD" if not en.line(seq) else "THE LINE IS FULL")
            else:
                ok = en.add(seq, ["r"])
                say(T, "REST" if ok else "THE LINE IS FULL")
            changed(T)
        return True
    if num in (LEFT, MINUS):
        if val:
            say(T, "TAKEN OFF" if en.drop_last(seq) else "THE LINE IS EMPTY")
            changed(T)
        return True
    if num == DELETE:
        if val:
            now = time.monotonic()
            if now - STATE["erase_at"] < 2.0:
                en.clear(seq)
                STATE["erase_at"] = 0.0
                say(T, "LINE CLEARED")
                changed(T)
            else:
                STATE["erase_at"] = now
                say(T, "ERASE AGAIN TO CLEAR THE LINE")
        return True
    if num in (WHEEL,) or num in KNOB_CLICKS:
        return True                                                    # (not the step sequencer's underneath)
    return False


def pad_event(T, board, p, vel):
    """A pad, when the shown instrument plays ENDLESS. True when used here (orig not called)."""
    seq = shown_seq(T)
    if seq is None or not endless.active(seq) or board.shift:
        return False
    en = endless.of(seq)
    e = T.engine
    if on_page(T) and en.entry:
        if vel:
            v = vel
            try:
                v = board_velocity(T, vel)
            except Exception:                                          # noqa: BLE001
                pass
            n = _note_of(T, board, p)
            if n is None:
                return False
            if en.add(seq, ["n", n, max(1, min(127, int(v)))]):
                changed(T)
                say(T, "%d STEPS" % len(en.line(seq)))
            else:
                say(T, "THE LINE IS FULL")
        return False                                                   # (it plays too, so you hear what went in)
    if not e.playing or not is_synth(T) or not en.line(seq):
        return False
    if vel:
        n = _note_of(T, board, p)
        first = en.first_note(seq)
        if n is None or first is None:
            return False
        STATE["notes"][p] = n
        en.held = [x for x in en.held if x != n] + [n]
        en.transpose = n - first
    else:
        n = STATE["notes"].pop(p, None)
        if n is None:
            return False
        en.held = [x for x in en.held if x != n]
        first = en.first_note(seq)
        if en.held and first is not None:
            en.transpose = en.held[-1] - first
        elif not en.hold:
            en.transpose = 0
    return True


board_velocity = None                                                  # app.py's pad_velocity (set by install)


# ------------------------------------------------------------------ where it's picked: ARP 2 (synths), PADS (drum machines)

def _kind_text(T):
    seq = shown_seq(T)
    return endless.of(seq).kind if seq is not None else "STEP"


def _pick(T, one):
    seq = shown_seq(T)
    if seq is None:
        return
    en = endless.of(seq)
    i = max(0, min(len(endless.KINDS) - 1, endless.KINDS.index(en.kind) + one))
    _set_kind(T, endless.KINDS[i])


def _set_kind(T, kind):
    seq = shown_seq(T)
    en = endless.of(seq)
    if en.kind != kind:
        en.kind = kind
        en.transpose, en.held, en.entry = 0, [], False
        changed(T)
    say(T, "SEQUENCER  %s" % kind)


def install_pickers(movelfo, pots):
    M = movelfo.MoveLFO
    o_av, o_ak, o_pv, o_pk = M.arp_values, M.arp_knob, M.pads_values, M.pads_knob

    def arp_values(self):
        v = o_av(self)
        if self.arp_second():
            v = list(v) + [("SEQUENCER", _kind_text(self.T))]
        return v

    def arp_knob(self, number, delta, shift):
        if self.arp_second() and number == 3:
            way = knobgate.gate(("endless-kind",), delta, shift)
            if way:
                _pick(self.T, 1 if way > 0 else -1)
            return
        return o_ak(self, number, delta, shift)

    def pads_values(self):
        v = o_pv(self)
        if not self.has_arp():
            v = list(v) + [("SEQUENCER", _kind_text(self.T))]
        return v

    def pads_knob(self, number, delta, shift):
        if not self.has_arp() and number == 4:
            way = knobgate.gate(("endless-kind",), delta, shift)
            if way:
                _pick(self.T, 1 if way > 0 else -1)
            return
        return o_pk(self, number, delta, shift)

    M.arp_values, M.arp_knob, M.pads_values, M.pads_knob = arp_values, arp_knob, pads_values, pads_knob

    o_target = pots.target

    def target(T, n):
        try:
            if on_page(T) and n in (1, 2, 3):
                return lambda val, n=n: set_by_pot(T, n, val)
            ml = T.mlfo
            if n == 3 and getattr(T, "arp_pop", 0) and ml.arp_second() and is_synth(T):
                return lambda val: _set_kind(T, endless.KINDS[pots.zone(val, len(endless.KINDS))])
        except Exception:                                              # noqa: BLE001
            pass
        return o_target(T, n)

    pots.target = target


def install_board(MoveBoard, G):
    global board_velocity
    board_velocity = G.get("pad_velocity")
    o_cc, o_pad = MoveBoard.cc, MoveBoard.pad

    def cc(self, num, val):
        T = self.T
        if on_page(T):
            try:
                if key(T, self, num, val):
                    return None
            except Exception:                                          # noqa: BLE001
                import traceback
                print("endless key:", traceback.format_exc(), flush=True)
        return o_cc(self, num, val)

    def pad(self, p, vel):
        try:
            if pad_hook(self, p, vel):
                return None
        except Exception:                                              # noqa: BLE001
            import traceback
            print("endless pad:", traceback.format_exc(), flush=True)
        return o_pad(self, p, vel)

    def pad_hook(self, p, vel):
        return pad_event(self.T, self, p, vel)

    MoveBoard.cc, MoveBoard.pad = cc, pad


# ------------------------------------------------------------------ its page

def draw(T, nat):
    import colour
    import soundpage as sp
    c = nat.canvas
    e = T.engine
    seq = e.seq
    en = endless.of(seq)
    now = nat.time.monotonic()
    ln = list(en.line(seq))
    at = None
    if e.playing:
        try:
            at = en.playing_index(seq, e._heard_frame(), e.frames_per_beat())
        except Exception:                                              # noqa: BLE001
            at = None
    synth = is_synth(T)
    pat = "PAT %d" % (seq.current + 1) + (">%d" % (seq.queued + 1) if seq.queued is not None else "")
    msg = T.message if (T.message and now < T.message_until) else None
    left = ("ENTRY" if en.entry else "ENDLESS") + ("  %+d" % en.transpose if en.transpose and synth else "")

    def head(c):
        c.text_px(6, 25, left, nat.ACC if en.entry else sp.WHITE, 24, -3)
        c.text_px(314 - sp.text_width(c.pxfont(16), pat, -1), 25, pat, colour.GREENS[5], 16, -1)
        if msg:
            c.text_px(6, 6, msg[:50], nat.ACC, 8, 0)

    def under(c):
        x0, y0, w, h = 6, 34, 308, 96
        c.rect(x0, y0, w, h, colour.GREENS[0])
        n = len(ln)
        c.text_px(x0 + 4, y0 + h - 4, "%d / %d" % (n, endless.MAX), colour.GREENS[4], 8, 0)
        if not n:
            hint = "SEQ RECORD, THEN PADS" if not en.entry else "PLAY THE PADS"
            c.text_px(x0 + 10, y0 + 44, hint, colour.GREENS[5], 16, -1)
            return
        cell = max(4, min(24, w // max(1, n)))
        show = w // cell                                               # steps that fit; scroll to keep the playing one (or the end) in view
        focus = at if at is not None else n - 1
        first = 0 if n <= show else max(0, min(n - show, focus - show // 2))
        vals = [t[1] for t in ln if t[0] == "n"] or [0]
        lo, hi = min(vals), max(vals)
        span = max(1, hi - lo)
        prev = None
        for i in range(first, min(n, first + show)):
            t = ln[i]
            x = x0 + (i - first) * cell
            if t[0] == "n":
                prev = t
            elif t[0] == "t" and prev is None:
                for j in range(i - 1, -1, -1):
                    if ln[j][0] == "n":
                        prev = ln[j]
                        break
            if t[0] == "r":
                c.rect(x + cell // 2 - 1, y0 + h - 14, 2, 4, colour.GREENS[3])
                continue
            if prev is None:
                continue
            val = prev[1]
            frac = (val - lo) / span if synth else (val / 15.0)
            bh = 10
            y = int(y0 + 6 + (1.0 - frac) * (h - 28))
            colr = colour.BODIES[val % len(colour.BODIES)]
            if t[0] == "t":
                colr = colour.mix(colr, (0, 0, 0), 0.35)
            c.rect(x + (0 if t[0] == "t" else 1), y, cell - (1 if t[0] == "t" else 2), bh, colr)
            if i == at:
                c.frame(x - 1, y - 3, cell + 1, bh + 6, sp.WHITE)
        if en.entry and n < endless.MAX and n - first < show:
            x = x0 + (n - first) * cell
            if int(now * 3) % 2 == 0:
                c.rect(x + 1, y0 + 4, 2, h - 8, nat.ACC)

    v = values(en)                                                     # K1-K3 in the bottom row (as pads 1-3 sit), Shift + K1-K3 above
    items = [(a, b, 1.0) for a, b in v[:3]] + [("", "", 0.0)] + [(a, b, 1.0) for a, b in v[3:]] + [("", "", 0.0)]
    act = STATE.get("active")
    active = (act[0] if act[0] < 3 else act[0] + 1) if act and now - act[1] < 1.0 else None
    items, active = sp.by_pad_rows(items, active)
    sp.grid(nat, ("endless", e.slot, seq.current), "", "", items, active, now, None, head=head, under=under)
