"""Step entry on the drum sequencer page (MPC only): turn the wheel and a box (the cursor) appears on the steps; the wheel
moves it along the lane and a push puts the selected drum's step there (again: takes it off). Shift + push selects the step for
its settings. The pads only play / pick the drums (SEQ RECORD, in the bridge, turns them into the 16 steps).
Installed over Console's MoveBoard by mpc_app.py; Console's own files are not changed."""
import time

WHEEL = 14
PUSH = 3                                                         # the wheel's push (the MPC encoder push)
BACK = 51
REDO, LOOPMARK, ARMSEL, TRIPLETS, METRO = 104, 105, 106, 107, 108
INSTHOME, SETTINGSKEY = 112, 113                                  # SAMPLE (page 1 of the instrument) and Shift + SAMPLE (SETTINGS), bridge/mapping.h
PROJECT, SONGPAGE, GRIDNEXT = 109, 110, 111                     # Shift + pad 16 / 12 / 14 on the tape-style pages (as printed on the pads)
ERASE = 119                          # private CCs from the bridge: REDO, set a loop point, arm / disarm the selected track
K1 = 71                                                          # Move knob 1 (relative clicks)
K1_ABS = 115                                                     # K1's absolute position from the bridge (0-127). (Not 112: SAMPLE; not 118: CHOP = SPLICE)
MAX_LEN = 64


def length_page(T):
    """K1 sets a length: a drum lane's, or the synth pattern's (or the picked note's), no steps selected or held."""
    try:
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return False
        if not T.seq_page or T.fx_page or T.punch.active() or T.auto.active() or not T.engine:
            return False
        if T.synth_shown():
            ms = T.msyn
            return bool(ms.active() and not ms.selected and not ms.down and not (ms.kind and ms.lane is None))
        ms = T.mseq
        return bool(ms.active() and ms.held is None and not ms.selected and T.engine.drums is not None)
    except Exception:
        return False


def set_length(T, val):
    """Length from K1's position: 0 -> 1 step, 127 -> 64."""
    target = 1 + int(round(val * (MAX_LEN - 1) / 127.0))
    if T.synth_shown():
        ms = T.msyn
        cur = ms.length()
        if target != cur:
            ms.knob(1, target - cur, False)
    else:
        ms = T.mseq
        cur = T.engine.seq.lane(T.seqp.lane).length
        if target != cur:
            ms.knob(1, target - cur, False)



def active(T):
    """Drum sequencer page, nothing selected, no popups on top: the cursor is in use."""
    try:
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return False                                    # a menu (SAVE PRESET ...) is up: the wheel and push are the menu's
        ms = T.mseq
        if not T.seq_page or T.fx_page or not ms.active() or ms.held is not None:
            return False
        if T.punch.active() or T.auto.active() or T.synth_shown():
            return False
        return T.engine is not None and T.engine.drums is not None
    except Exception:
        return False


def on_tape(T):
    """The 8-track page (not zoomed, no menu on top)."""
    try:
        import native
        return bool(T.engine) and T.focus.track is None and native.on_tape_page(T, getattr(T, "_mpc_menu", None))
    except Exception:
        return False


def pos_text(T):
    try:
        return T.position_text(T.tape.pos)
    except Exception:
        return ""


def loop_mark(T):
    """Shift + LOOP: the first press marks a point (the loop is there, four bars long, until you mark the other one), the second sets the
    other end: whichever is earlier is the IN point, the later the OUT point. Both at the same spot: the points are taken away."""
    e = T.engine
    here = T.tape.pos
    mark = getattr(T, "_loop_mark", None)
    if mark is None:
        T._loop_mark = here
        e.set_loop_point("in", here)
        T.say("LOOP POINT 1 AT %s  (SHIFT + LOOP AGAIN FOR THE OTHER)" % pos_text(T), 4)
        return
    T._loop_mark = None
    a, b = (mark, here) if mark <= here else (here, mark)
    if abs(b - a) < 1e-6:
        e.clear_region()
        T.say("IN / OUT POINTS CLEARED", 2)
        return
    e.set_region(a, b, True)
    T.say("LOOP ON: IN %s  OUT %s" % (T.position_text(a), T.position_text(b)), 3)


def tape_button(board, num):
    T = board.T
    e = T.engine
    if not e:
        return
    if num == REDO:
        try:
            seqish = T.seq_page and not (T.fx_page or T.punch.active() or T.auto.active())
        except Exception:
            seqish = False
        if seqish:                                              # Shift + PLUS on a sequencer page: the pattern's redo
            sp = T.sp()
            n = sp.seq.redo()
            if n is None:
                T.say("NOTHING TO REDO", 2)
            else:
                sp._gesture = None
                e.seq_changed()
                T.say("REDONE%s" % ("" if n == sp.seq.current else " IN PATTERN %d" % (n + 1)), 2)
            return
        T.say("REDONE" if e.redo() else "NOTHING TO REDO", 2)
    elif num == LOOPMARK:
        loop_mark(T)
    elif num == ARMSEL:
        board.keys.put("ARM%d" % T.armed)
    elif num == TRIPLETS:
        e.set_triplets(not e.triplets)
        T.say("TRIPLETS ON  (STEPS 4, 8, 12, 16 OFF)" if e.triplets else "TRIPLETS OFF", 3)
    elif num == METRO:
        import metronome
        metronome.toggle(T)


def in_seq(T):
    """Drum sequencer page (steps selected or not): the wheel's box and push are in use."""
    try:
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return False
        ms = T.mseq
        if not T.seq_page or T.fx_page or not ms.active():
            return False
        if T.punch.active() or T.auto.active() or T.synth_shown():
            return False
        if T.engine is None or T.engine.drums is None:
            return False
        return hasattr(T.engine.seq, "lane")                    # (a synth's NoteSequencer has no drum lanes: not this page)
    except Exception:
        return False


def click(T, shift):
    """The wheel was pushed. On an empty step: the selected drum's step goes down. On a step that is on: it joins the selected
    steps (they blink and the pads become their settings); pushed again on a selected step: it leaves them. Shift + push does the
    same. ERASE takes steps off (see erase)."""
    import sequencer
    ms, e, sp = T.mseq, T.engine, T.seqp
    lane = sp.lane
    length = e.seq.lane(lane).length
    if not getattr(ms, "cur_on", False) and not ms.selected:
        return                                                   # no box yet: turn the wheel first
    i = _cursor(ms)
    if i >= length:
        T.say("STEP %d IS PAST THE END (LENGTH %d: KNOB 1)" % (i + 1, length), 2)
        return
    if sequencer.dark(i, sequencer.TRIPLETS):
        return
    on = bool(e.seq.step(lane, i).on)
    if not on:                                                   # an empty step: put it down
        sp._edit(("toggle", time.monotonic()))
        with e.seq.lock:
            e.seq.step(lane, i).on = True
        e.seq_changed()
        return
    if i in ms.selected:                                         # already selected: it leaves the selection
        ms.selected.remove(i)
        ms.sel = None
        return
    if not ms.selected:
        ms.knob_page = getattr(T, "drum_tab", 0)                 # (the knobs start on the sound page you were on)
    ms.selected = list(ms.selected) + [i]                        # one more selected step (BACK: none)
    ms.sel = None


def erase(T):
    """ERASE on the drum sequencer page: the selected steps come off; none selected: the step under the box."""
    ms, e, sp = T.mseq, T.engine, T.seqp
    lane = sp.lane
    length = e.seq.lane(lane).length
    which = [i for i in ms.selected if i < length]
    if not which:
        if not getattr(ms, "cur_on", False):
            return
        which = [_cursor(ms)]
    which = [i for i in which if i < length and e.seq.step(lane, i).on]
    ms.selected, ms.sel = [], None
    if not which:
        return
    sp._edit(("toggle", time.monotonic()))                       # (undo works as for a step button)
    with e.seq.lock:
        for i in which:
            e.seq.step(lane, i).on = False
    e.seq_changed()


def deselect(T):
    """Off the sequencer pages: no steps stay selected (called every frame by the screen)."""
    try:
        if T.seq_page:
            return
        for ms in (T.mseq, T.msyn):
            if getattr(ms, "selected", None):
                ms.selected = []
                if hasattr(ms, "sel"):
                    ms.sel = None
    except Exception:
        pass


def _cursor(ms):
    c = getattr(ms, "cur", 0)
    return c if isinstance(c, int) and c >= 0 else 0


def move(T, way):
    ms, sp, e = T.mseq, T.seqp, T.engine
    lane = sp.lane
    length = e.seq.lane(lane).length
    import sequencer
    if not getattr(ms, "cur_on", False):
        ms.cur_on = True                                         # the first turn only brings the box up
        ms.cur = min(_cursor(ms), max(0, length - 1))
        ms.page[lane] = ms.cur // 16
        return
    d = 1 if way > 0 else -1
    cur = _cursor(ms)
    nxt = cur + d
    while 0 <= nxt < length and sequencer.dark(nxt, sequencer.TRIPLETS):
        nxt += d                                                 # triplets: the dark steps (every 4th) don't play, the box skips them
    if 0 <= nxt < length:
        cur = nxt
    ms.cur = cur
    ms.page[lane] = cur // 16                                    # the 16 steps shown follow the box


def lay(T, p, vel=None):
    """A drum pad (Move pad number p) was hit while stopped: its step on the cursor's step is switched on (off if it was on)."""
    ms, sp, e = T.mseq, T.seqp, T.engine
    d = e.drums
    r, c = divmod(p, 8)
    if c >= 4:
        return
    lane = r * 4 + c
    if lane >= d.lanes:
        return
    cur = _cursor(ms)
    if cur >= e.seq.lane(lane).length:
        return
    sp._edit(("toggle", time.monotonic()))                       # (undo works as for a step button)
    with e.seq.lock:
        st = e.seq.step(lane, cur)
        st.on = not st.on                                        # a hit on a step that has one takes it off
        if st.on and vel:
            st.vel = max(1, min(127, int(vel)))                  # a new step takes the velocity you hit with
    e.seq_changed()
    ms.page[lane] = cur // 16


def install(MoveBoard, pad_velocity=None):
    orig_cc, orig_pad, orig_note = MoveBoard.cc, MoveBoard.pad, MoveBoard.note

    def cc(self, num, val):
        T = self.T
        if num in (REDO, LOOPMARK, ARMSEL, TRIPLETS, METRO):                    # the bridge's tape-page buttons (see bridge/mapping.h)
            if val:
                tape_button(self, num)
            return
        if num in (INSTHOME, SETTINGSKEY):
            if val:
                self.keys.put("INST_HOME" if num == INSTHOME else "SETTINGS")
            return
        if num == PUSH and T.inst_page and not T.fx_page and not self.shift:
            # the INSTRUMENTS page, a loaded slot: a short push opens it as always; holding the push for a moment (instpage.tick)
            # opens CHANGE / REMOVE, like Shift + push
            ip, e_ = T.instp, T.engine
            if val:
                if ip.mode is None and e_ and e_.drums and e_.slots[ip.row]:
                    ip.push_down, ip.push_fired = time.monotonic(), False
                    return
            elif getattr(ip, "push_down", None) is not None:
                fired = ip.push_fired
                ip.push_down = None
                if not fired:
                    orig_cc(self, PUSH, 127)                                    # (it was a short push: it happens now)
                    orig_cc(self, PUSH, 0)
                return
        if num in (PROJECT, SONGPAGE, GRIDNEXT):                                # Shift + pad 16 / 12 / 14 (bridge/mapping.h)
            if val:
                self.keys.put("FILE" if num == PROJECT else "SONG" if num == SONGPAGE else ("KNOB", 10, 1, False))
            return
        if num == ERASE and not self.shift and (in_seq(T) or getattr(self, "_erase_seq", False)):
            self._erase_seq = bool(val)                                         # (its release is swallowed too)
            if val:
                erase(T)
            return
        if 71 <= num <= 74 and on_tape(T):
            # the tape page: K1 = the selected track's volume, K2 = its pan, K3 = nothing, the fader = its volume (Shift: pan)
            if num == 73:
                return
            track = 70 + T.armed
            if num == 74:
                orig_cc(self, track, val)
                return
            shift = self.shift
            self.shift = num == 72
            try:
                orig_cc(self, track, val)
            finally:
                self.shift = shift
            return
        if num == K1_ABS or num == K1:
            if length_page(T):
                now = time.monotonic()
                if num == K1_ABS:
                    T._k1_abs_at = now
                    set_length(T, val)                          # K1 is a pot: its position IS the length (1-64)
                elif val and now - getattr(T, "_k1_abs_at", -9.0) > 0.15:
                    # clicks with no pot position before them: the wheel in KNOB FX mode (pad 1 held) acting as knob 1
                    step = val - 128 if val > 63 else val
                    if T.synth_shown():
                        T.msyn.knob(1, step, False)
                    else:
                        T.mseq.knob(1, step, False)
                return                                          # (the pot's own clicks are not used there)
            if num == K1_ABS:
                return
        if num == WHEEL and val and self.shift and on_tape(T):
            step = val - 128 if val > 63 else val
            if step:
                import tapepage
                tapepage.scroll(T, step)                        # Shift + wheel on the tape page: scroll through the 8 tracks
            return
        if num == PUSH and val and self.shift and on_tape(T):
            self.keys.put(("KNOB", 10, 1, False))               # Shift + push on the tape page: the next grid (1/4, 1/8 ...)
            return
        if num == PUSH and val and in_seq(T):
            click(T, self.shift)
            return
        if num == BACK and val and not self.shift and in_seq(T) and T.mseq.selected:
            T.mseq.selected, T.mseq.sel = [], None               # BACK: done with the selected steps
            return
        if num == WHEEL and val and not self.shift and in_seq(T) and T.mseq.selected:
            step = val - 128 if val > 63 else val
            if step:
                move(T, step)                                    # (the box keeps moving; K1 is the amount)
            return
        if num == WHEEL and val and not self.shift and active(self.T) and not self.T.engine.playing:
            step = val - 128 if val > 63 else val
            if step:
                move(self.T, step)
            return
        orig_cc(self, num, val)

    def note(self, num, val):
        T = self.T
        if (num in (17, 18) and val and self.shift and T.seq_page and T.drum_page
                and not (T.punch.active() or T.auto.active() or T.fx_page or T.inst_page or T.song_page or T.sbrowse.active)
                and (T.synth_shown() or num == 17)):
            # NOTE REPEAT / PAD FX from inside a sequencer: out to the sound page first, then on to the arp / pads page
            T.punch.leave()
            T.auto_page = T.seq_page = False
            T.seqp.held, T.synthp.held = {}, {}
            T.mlfo.tab = None
            T._from_seq = "pending"                         # (the page opens next; closing it goes back to the sequencer)
        orig_note(self, num, val)

    def pad(self, p, vel):
        orig_pad(self, p, vel)                                   # the pads play and pick the drums; they never lay steps here

    MoveBoard.cc, MoveBoard.pad, MoveBoard.note = cc, pad, note
    try:                                                         # the arp / pads page opened from a sequencer: its icon again goes back there
        import movelfo
        for name in ("goto_arp", "goto_pads"):
            orig = getattr(movelfo.MoveLFO, name)

            def wrapped(self, _orig=orig):
                T = self.T
                was_open = self.tab is not None
                _orig(self)
                state = getattr(T, "_from_seq", None)
                if not was_open and self.tab is not None:
                    T._from_seq = "armed" if state == "pending" else None
                elif was_open and self.tab is None and state == "armed":
                    T._from_seq = None
                    T.seq_page = True
                elif was_open:
                    T._from_seq = None
            setattr(movelfo.MoveLFO, name, wrapped)
    except Exception:
        import traceback
        print("arp / pads return failed:\n" + traceback.format_exc(), flush=True)
