"""Step entry on the drum sequencer page (MPC only): a box (the cursor) sits on one of the 16 steps, the wheel moves it
along the lane, and hitting a drum pad while the sequence is stopped lays that drum's step on the box's step (again: takes it off). The first tap on a different drum only switches to it.
Installed over Console's MoveBoard by mpc_app.py; Console's own files are not changed."""
import time

WHEEL = 14


def active(T):
    """Drum sequencer page, nothing selected, no popups on top: the cursor is in use."""
    try:
        ms = T.mseq
        if not T.seq_page or T.fx_page or not ms.active() or ms.held is not None:
            return False
        if T.punch.active() or T.auto.active() or T.synth_shown():
            return False
        return T.engine is not None and T.engine.drums is not None
    except Exception:
        return False


def _cursor(ms):
    c = getattr(ms, "cur", 0)
    return c if isinstance(c, int) and c >= 0 else 0


def move(T, way):
    ms, sp, e = T.mseq, T.seqp, T.engine
    lane = sp.lane
    length = e.seq.lane(lane).length
    cur = max(0, min(length - 1, _cursor(ms) + (1 if way > 0 else -1)))
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
        if num == WHEEL and val and not self.shift and active(self.T) and not self.T.engine.playing:
            step = val - 128 if val > 63 else val
            if step:
                move(self.T, step)
            return
        orig_cc(self, num, val)

    def pad(self, p, vel):
        T = self.T
        lay_it = bool(vel) and active(T) and not T.engine.playing and not self.shift
        if lay_it:
            r, c = divmod(p, 8)
            if c >= 4 or r * 4 + c != T.seqp.lane:               # another drum's first tap only switches to it
                lay_it = False
        orig_pad(self, p, vel)
        if lay_it:
            try:
                lay(T, p, pad_velocity(T, vel) if pad_velocity else vel)
            except Exception:
                import traceback
                print("step entry failed:\n" + traceback.format_exc(), flush=True)

    MoveBoard.cc, MoveBoard.pad = cc, pad
