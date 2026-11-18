"""K1-K3 and the FADER are pots (an end stop each side). Where a setting used to count their clicks (a full turn only came to ~30 of them),
its value now follows the pot's position: a number goes from its lowest to its highest value end to end (0-127 -> 0-100 %), a short
list gets an equal zone of the travel for each name (127 / 5 for five names).

The bridge sends a pot's position first (CC 115 K1, 116 K2, 117 K3, 122 the FADER = knob 8), then its clicks (CC 71-73, 78). The clicks
of a pot that was used by position are not used again (_pot_abs_at); a wheel turn on a held KNOB FX pad has no position before it
and keeps working as before."""
import time

POT_KNOB = {115: 1, 116: 2, 117: 3, 122: 8}              # a pot's position message -> the knob number it is
CLICK_KNOB = {71: 1, 72: 2, 73: 3, 78: 8}                # ... and its clicks


def frac(val):
    return max(0, min(127, int(val))) / 127.0


def zone(val, n):
    """A pot position -> the place (0 .. n-1) in a list of n names, an equal part of the travel each."""
    return max(0, min(n - 1, int(val) * n // 128))


def param_value(d, key, val):
    """A drum machine / synth setting (drums.*) from a pot position: a mode or switch by zone, a number end to end."""
    top = d.stepped(key, 0, 100000)
    try:
        import knobgate
        if knobgate.is_choice(d, key):
            return zone(val, top + 1)
    except Exception:                                      # noqa: BLE001
        pass
    return int(round(frac(val) * top))


# ------------------------------------------------------------------ what a pot is on the page now

def _sound(T, n):
    """A sound page: the setting that knob n is (a mode or a number)."""
    import stepentry
    param = stepentry.sound_k1(T, n, choices=True)
    if param is None:
        return None
    d = T.engine.drums
    is_mode = False
    try:
        import knobgate
        is_mode = knobgate.is_choice(d, param)
    except Exception:                                      # noqa: BLE001
        pass
    if n in (1, 2, 3) and not is_mode:
        return None                                        # (a number on K1-K3: stepentry.sound_k1_set does it)

    def go(val):
        d.set_param(param, param_value(d, param, val))
        with T.engine.lock:
            T.engine.dirty.add(-1)
        try:
            T.drumpage.edited[n] = time.monotonic()
        except Exception:                                  # noqa: BLE001
            pass
    return go


def _arp2(T, n):
    ml = T.mlfo
    try:
        if not ((getattr(T, "arp_pop", 0) or ml.arp_on_page()) and ml.arp_second()) or n not in (1, 2):
            return None
    except Exception:                                      # noqa: BLE001
        return None

    def go(val):
        c = ml.cfg()
        if n == 1:
            c["glide"] = int(round(frac(val) * 100))
        else:
            c["bend"] = int(round(frac(val) * 200)) - 100
            if abs(c["bend"]) < 2:
                c["bend"] = 0                              # (a rest at the middle)
        T.engine.seq_changed()
        T.say("ARP  %s  %s" % ml.arp_values()[n - 1], 2)
    return go


def _sends_fx(T, n):
    """REVERB / DELAY pages: knobs 1-8 are the tracks' sends."""
    if T.fx_page not in ("reverb", "delay") or getattr(T, "inst_sends", False):
        return None
    kind = T.fx_page

    def go(val):
        e = T.engine
        sends = e.rev_sends if kind == "reverb" else e.dly_sends
        want = round(frac(val), 2)
        v = e.change_send(kind, n, want - sends[n - 1])
        T.say("TRACK %d %s SEND: %d%%" % (n, kind.upper(), round(v * 100)), 2)
    return go


def _sends_inst(T, n):
    """The instrument's SENDS page: reverb, delay and the song inserts' amounts."""
    ml = T.mlfo
    try:
        if not (ml.active() and ml.sends_on_page()) or n not in (1, 2, 3):
            return None
    except Exception:                                      # noqa: BLE001
        return None

    def go(val):
        e = T.engine
        if n in (1, 2):
            kind = "reverb" if n == 1 else "delay"
            cur = e.inst_send(kind)
            if cur is None:
                T.say("%s SEND  OWN FX" % kind.upper(), 2)
                return
            v = e.change_inst_sends(kind, round(frac(val), 2) - cur)
            T.say("%s SEND  %s" % (kind.upper(), "%d%%" % round(v * 100) if v is not None else "OWN FX"), 2)
        else:
            if not ml._inserts():
                return
            sf = T.songfx(0)
            if not sf.index:
                T.say("SONG INSERT 1 IS EMPTY (LEFT BUTTON 3)", 2)
                return
            slot = e.slot if e.slot is not None else 0
            v = sf.set_amount(slot, int(round(frac(val) * 100)))
            T._insfx_save()
            T.say("SONG INSERT 1  %d%%" % v, 2)
    return go


def _insert_fx(T, n):
    """An INSERT page (and the song inserts): the effect's first eight settings; a pot sets one from its position."""
    ins = None
    try:
        if T.fx_page in ("insert", "insert2"):
            ins = T.insfx()
        elif T.fx_page in ("song1", "song2"):
            ins = T.songfx(0 if T.fx_page == "song1" else 1)
        elif not T.fx_page and T.mlfo.active() and T.mlfo.insert_pos() is not None:
            ins = T.insfx(None, T.mlfo.insert_pos())
    except Exception:                                      # noqa: BLE001
        return None
    if ins is None or n > 8:
        return None

    def go(val):
        slot = n - 1
        if slot >= len(ins.params) or not getattr(ins, "h", True):
            return
        key, _l, lo, hi, _d, step, opts = ins.params[slot]
        if opts:
            want = zone(val, len(opts))
        else:
            want = lo + frac(val) * (hi - lo)
        cur = ins.values.get(key, lo)
        ins.knob(slot, (want - cur) / step)                # (the effect rounds it to its own step)
        T._insfx_save()
    return go


def _steps(T, n):
    """The sequencers with steps selected: K1 is the picked setting; with none picked, K1-K3 and the FADER lock the sound page's settings."""
    try:
        if not T.seq_page or T.fx_page or T.inst_page or T.song_page or not T.engine:
            return None
        if T.punch.active() or T.auto.active() or getattr(T, "arp_pop", 0) or getattr(T, "pads_pop", 0):
            return None
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return None
        ms = T.msyn if T.synth_shown() else T.mseq
        if not ms.active() or not ms.selected:
            return None
    except Exception:                                      # noqa: BLE001
        return None
    if ms.sel is not None:
        if n == 1:
            return ms.pos_selected
        if n == 2:
            return ms.second_abs
        return None
    if n in (1, 2, 3, 8):
        return lambda val: ms.pos_lock(n, val)
    return None


def target(T, n):
    """The function (position 0-127 -> sets it) for pot knob n on the page now, or None (the pot's clicks do what they did)."""
    for f in (_steps, _arp2, _sends_inst, _insert_fx, _sends_fx, _sound):
        got = f(T, n)
        if got is not None:
            return got
    return None


def handle(T, num, val):
    """A pot's position (115 / 116 / 117 / 122) or its clicks (71-73, 78). True when used here."""
    if num in POT_KNOB:
        go = target(T, POT_KNOB[num])
        if go is None:
            return False
        seen = T.__dict__.setdefault("_pot_abs_at", {})
        seen[{1: 71, 2: 72, 3: 73, 8: 78}[POT_KNOB[num]]] = time.monotonic()
        go(val)
        return True
    if num in CLICK_KNOB and val:
        seen = T.__dict__.get("_pot_abs_at", {})
        if time.monotonic() - seen.get(num, -9.0) < 0.15 and target(T, CLICK_KNOB[num]) is not None:
            return True                                    # (its clicks follow its position: not used)
    return False
