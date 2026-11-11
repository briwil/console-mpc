"""Step entry on the drum sequencer page (MPC only): turn the wheel and a box (the cursor) appears on the steps; the wheel
moves it along the lane and a push puts the selected drum's step there (again: takes it off). Shift + push selects the step for
its settings. The pads only play / pick the drums (SEQ RECORD, in the bridge, turns them into the 16 steps).
Installed over Console's MoveBoard by mpc_app.py; Console's own files are not changed."""
import time

WHEEL = 14
PUSH = 3                                                         # the wheel's push (the MPC encoder push)
BACK = 51


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
        return T.engine is not None and T.engine.drums is not None
    except Exception:
        return False


def click(T, add):
    """The wheel was pushed: select the box's step (it blinks and the pads become its settings). Shift: add it to the
    selection. Pushed on a step that is already selected: take just that one out again."""
    import sequencer
    ms, e = T.mseq, T.engine
    lane = T.seqp.lane
    length = e.seq.lane(lane).length
    i = _cursor(ms)
    if i >= length:
        T.say("STEP %d IS PAST THE END (LENGTH %d: KNOB 1)" % (i + 1, length), 2)
        return
    if sequencer.dark(i, sequencer.TRIPLETS):
        return
    if not add and not ms.selected:                              # a plain push: the step on / off
        if not getattr(ms, "cur_on", False):
            return                                               # (no box yet: turn the wheel first)
        sp = T.seqp
        sp._edit(("toggle", time.monotonic()))                   # (undo works as for a step button)
        with e.seq.lock:
            st = e.seq.step(lane, i)
            st.on = not st.on
        e.seq_changed()
        return
    if i in ms.selected:
        ms.selected.remove(i)
        ms.sel = None
        return
    if not ms.selected:
        ms.knob_page = getattr(T, "drum_tab", 0)                 # (the knobs start on the sound page you were on)
    if not add:
        ms.selected = []
    ms.selected.append(i)
    ms.sel = None


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
    orig_cc, orig_pad = MoveBoard.cc, MoveBoard.pad

    def cc(self, num, val):
        T = self.T
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

    def pad(self, p, vel):
        orig_pad(self, p, vel)                                   # the pads play and pick the drums; they never lay steps here

    MoveBoard.cc, MoveBoard.pad = cc, pad
