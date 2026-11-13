"""Punch-in effects (OP-XY style): a sequencer of their own on each instrument, one lane per effect.

Each instrument's sequencer has 16 punch patterns of its own (state(seq)), apart from its note patterns: you pick
them with Shift + pad on the PUNCH FX page, and song mode picks them per row. A punch pattern has 16 lanes, one
per effect (NAMES): each with its own length and rate (RATES, as the drum lanes; TRIPLETS too), its steps on or
off with a chance each. The pattern's time scale (SCALES) makes all its lanes' steps that many times longer, for
long sweeps.

The effects stack, one from each group (a lane of the same group playing at the same time: the one whose step
started last wins it, then the higher lane):
    TIME    1-8   REPEAT 1/4, 1/8, 1/16, 1/32, 1/8T, REVERSE, TAPE STOP, HALF SPEED
    FILTER  9-11  LOW PASS, HIGH PASS, RESO PEAK
    CRUSH   12    BITCRUSH          GATE  13  GATE 1/16          PAN   14  PAN SWING
    ECHO    15    ECHO THROW        KILL  16  KILL
A set of effects is a mask: bit (fx - 1) for each. The sound work is in fx/fx.c (punch_process), one stage for
each of TIME, FILTER, CRUSH, GATE and KILL; PAN SWING and ECHO THROW are done with the pans and sends.

Timing: lanes count from the punch anchor: the start (PLAY) or the moment a queued punch pattern took over (at
the instrument's pattern's end, as its own patterns change), so a long scaled pattern isn't cut short by the
instrument's shorter one going round.
"""
import copy
import math
import random

import sequencer

NAMES = ["REPEAT 1/4", "REPEAT 1/8", "REPEAT 1/16", "REPEAT 1/32", "REPEAT 1/8T", "REVERSE", "TAPE STOP",
         "HALF SPEED", "LOW PASS", "HIGH PASS", "RESO PEAK", "BITCRUSH", "GATE 1/16", "PAN SWING", "ECHO THROW",
         "KILL"]
SHORT = ["RP1/4", "RP1/8", "RP16", "RP32", "RP8T", "REV", "STOP", "HALF", "LP", "HP", "RESO", "CRUSH", "GATE",
         "PAN", "ECHO", "KILL"]
PAN_SWING, ECHO_THROW = 14, 15
LANES = len(NAMES)
PATTERNS = 16
SCALES = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32]         # the time scale: each step this many times longer
GROUPS = [range(1, 9), range(9, 12), (12,), (13,), (14,), (15,), (16,)]
STAGES = [0, 1, 2, 3, 6]                            # the groups punch_process does, in order


# ------------------------------------------------------------------ masks

def bit(fx):
    return 1 << (fx - 1)


def group(fx):
    return next(g for g, fxs in enumerate(GROUPS) if fx in fxs)


def effects(mask):
    """The effects (1-16) in a mask, lowest first."""
    return [fx for fx in range(1, 17) if mask & bit(fx)]


def in_group(mask, g):
    """The effect of group g in the mask (0: none)."""
    for fx in GROUPS[g]:
        if mask & bit(fx):
            return fx
    return 0


def with_fx(mask, fx):
    """The mask with fx in it, taking out any other of its group."""
    for other in GROUPS[group(fx)]:
        mask &= ~bit(other)
    return mask | bit(fx)


def over(base, top):
    """top's effects win their groups; base's others stay."""
    for fx in effects(top):
        base = with_fx(base, fx)
    return base


def label(mask, short=False):
    names = SHORT if short or len(effects(mask)) > 1 else NAMES
    return "+".join(names[fx - 1] for fx in effects(mask))


def name(fx):
    return NAMES[fx - 1] if 1 <= fx <= len(NAMES) else ""


# ------------------------------------------------------------------ the patterns

class Lane:
    def __init__(self, length=16):
        self.length = length
        self.rate = 0                       # a place in sequencer.RATES
        self.steps = {}                     # step -> chance (a place in sequencer.CHANCES): the steps that are on
        self.lens = {}                      # step -> how many steps it lasts (hold a step, tap a later one); 1 if not here


class Pattern:
    def __init__(self, length=16):
        self.lanes = [Lane(length) for _ in range(LANES)]
        self.scale = 0                      # a place in SCALES

    def empty(self):
        return not any(ln.steps for ln in self.lanes)


class State:
    def __init__(self, length=16):
        self.patterns = [Pattern(length) for _ in range(PATTERNS)]
        self.current = 0
        self.queued = None
        self.anchor = 0.0
        self.decided = {}

    @property
    def pattern(self):
        return self.patterns[self.current]


def _bar_length(seq):
    try:
        return seq.new_length()
    except Exception:                                   # noqa: BLE001
        return 16


def state(seq):
    """The instrument's punch patterns (made the first time)."""
    st = getattr(seq, "punch_state", None)
    if st is None:
        st = seq.punch_state = State(_bar_length(seq))
    return st


def step_frames(seq, ln, pat, fpb):
    """How long one of the lane's steps is, in frames (its rate, triplets, the pattern's time scale)."""
    trip = getattr(seq, "trip", False)
    spb = sequencer.RATES[ln.rate][1] * (sequencer.TRIP_SPEED if trip else 1.0)
    return fpb / spb * SCALES[pat.scale]


def lane_pos(seq, li, frame, fpb):
    """(slot k counted from the anchor, step number) of lane li at sequencer time frame; (None, None) before it."""
    st = state(seq)
    pat = st.pattern
    ln = pat.lanes[li]
    sf = step_frames(seq, ln, pat, fpb)
    k = math.floor((frame - st.anchor) / sf + 1e-9)
    if k < 0:
        return None, None
    trip = getattr(seq, "trip", False)
    n = sequencer.live_len(ln.length, trip)
    return k, sequencer.phys(k % max(1, n), trip)


def _passes(seq, st, li, k, ch, n):
    if not ch:
        return True
    key = (st.current, li, k)
    if key in st.decided:
        return st.decided[key]
    c = sequencer.CHANCES[ch]
    if c.endswith("%"):
        ok = random.Random(hash((getattr(seq, "seed", 0), "punch", li, k))).random() * 100 < int(c[:-1])
    else:
        a, b = (int(x) for x in c.split(":"))
        ok = (k // max(1, n)) % b == a - 1
    if len(st.decided) > 1024:
        st.decided.clear()
    st.decided[key] = ok
    return ok


def covered(ln, trip):
    """The steps a long step lasts over (not its first)."""
    n = max(1, sequencer.live_len(ln.length, trip))
    out = set()
    for i, L in getattr(ln, "lens", {}).items():
        if i in ln.steps and not sequencer.dark(i, trip):
            a = sequencer.played(i, trip)
            for d in range(1, min(L, n)):
                out.add(sequencer.phys((a + d) % n, trip))
    return out


def mask_at(seq, frame, fpb):
    """The effects the punch lanes play at sequencer time frame (a mask)."""
    st = state(seq)
    pat = st.pattern
    trip = getattr(seq, "trip", False)
    best = {}                                       # group -> (step start, lane)
    for li, ln in enumerate(pat.lanes):
        if not ln.steps:
            continue
        k, _i = lane_pos(seq, li, frame, fpb)
        if k is None:
            continue
        n = max(1, sequencer.live_len(ln.length, trip))
        lens = getattr(ln, "lens", {})
        reach = min(n, max(lens.values(), default=1))
        hit = None
        for d in range(reach):                      # this step, or a long step before it still going (a later step on ends it)
            kk = k - d
            if kk < 0:
                break
            i = sequencer.phys(kk % n, trip)
            if i not in ln.steps or not _passes(seq, st, li, kk, ln.steps[i], n):
                continue
            if lens.get(i, 1) > d:
                hit = kk
            break
        if hit is None:
            continue
        start = st.anchor + hit * step_frames(seq, ln, pat, fpb)
        g = group(li + 1)
        if g not in best or (start, li) > best[g]:
            best[g] = (start, li)
    m = 0
    for _start, li in best.values():
        m |= bit(li + 1)
    return m


def next_change(seq, frame, fpb):
    """The next sequencer time after frame where a lane with steps moves to its next step (None: no steps)."""
    st = state(seq)
    pat = st.pattern
    nxt = None
    for ln in pat.lanes:
        if not ln.steps:
            continue
        sf = step_frames(seq, ln, pat, fpb)
        t = st.anchor + (math.floor((frame - st.anchor) / sf + 1e-9) + 1) * sf
        if nxt is None or t < nxt:
            nxt = t
    return nxt


# ------------------------------------------------------------------ choosing patterns (as the note patterns do)

def choose(seq, n, playing):
    """Pick punch pattern n: straight away when stopped, else when the instrument's pattern next comes round."""
    with seq.lock:
        st = state(seq)
        n = max(0, min(PATTERNS - 1, n))
        if not playing or n == st.current:
            st.current, st.queued = n, None
        else:
            st.queued = n


def pending(seq):
    st = getattr(seq, "punch_state", None)
    return st is not None and st.queued is not None


def take_queued(seq, boundary):
    """The instrument's pattern came round at boundary: a queued punch pattern starts there (from its step 1)."""
    st = getattr(seq, "punch_state", None)
    if st is not None and st.queued is not None:
        st.current, st.queued = st.queued, None
        st.anchor = boundary
        st.decided.clear()


def stop(seq):
    st = getattr(seq, "punch_state", None)
    if st is not None:
        if st.queued is not None:
            st.current, st.queued = st.queued, None
        st.anchor = 0.0
        st.decided.clear()


# ------------------------------------------------------------------ undo (in the sequencer's own undo list)

def snapshot(seq):
    """Keep the current punch pattern as it is (Undo puts it back)."""
    with seq.lock:
        st = state(seq)
        seq.undo_stack.append((("punch", st.current), copy.deepcopy(st.pattern)))
        del seq.undo_stack[:-sequencer.UNDO_STEPS]


def undo_entry(seq, n, pattern):
    """Sequencer.undo found a punch entry: put it back. Returns True if it was one."""
    if isinstance(n, tuple) and n and n[0] == "punch":
        state(seq).patterns[n[1]] = pattern
        return True
    return False


# ------------------------------------------------------------------ saving

def to_json(seq):
    st = getattr(seq, "punch_state", None)
    if st is None:
        return None
    pats = {}
    for n, p in enumerate(st.patterns):
        if p.empty() and not p.scale:
            continue
        lanes = {}
        for li, ln in enumerate(p.lanes):
            if ln.steps or ln.length != 16 or ln.rate:
                lanes[str(li)] = {"length": ln.length, "rate": ln.rate,
                                  "steps": {str(i): sequencer.CHANCES[c] for i, c in ln.steps.items()},
                                  "lens": {str(i): v for i, v in getattr(ln, "lens", {}).items()
                                           if i in ln.steps and v > 1}}
        pats[str(n)] = {"scale": p.scale, "lanes": lanes}
    if not pats and not st.current:
        return None
    return {"current": st.current, "patterns": pats}


def from_json(seq, data, old=None):
    """data: what to_json wrote (or None). old: [(pattern number, its length, the first version's steps)] from
    songs saved when the punch steps were in the note patterns: those become lanes of the same punch pattern."""
    st = seq.punch_state = State(_bar_length(seq))
    if isinstance(data, dict):
        try:
            st.current = max(0, min(PATTERNS - 1, int(data.get("current", 0))))
            for n, pd in (data.get("patterns") or {}).items():
                n = int(n)
                if not 0 <= n < PATTERNS:
                    continue
                p = st.patterns[n]
                p.scale = max(0, min(len(SCALES) - 1, int(pd.get("scale", 0))))
                for li, ld in (pd.get("lanes") or {}).items():
                    li = int(li)
                    if not 0 <= li < LANES:
                        continue
                    ln = p.lanes[li]
                    ln.length = max(1, min(sequencer.MAX_STEPS, int(ld.get("length", 16))))
                    ln.rate = max(0, min(len(sequencer.RATES) - 1, int(ld.get("rate", 0))))
                    ln.steps = {int(i): sequencer.chance_index(c) for i, c in (ld.get("steps") or {}).items()
                                if 0 <= int(i) < sequencer.MAX_STEPS}
                    ln.lens = {int(i): max(1, min(sequencer.MAX_STEPS, int(v))) for i, v in (ld.get("lens") or {}).items()
                               if int(i) in ln.steps}
        except (TypeError, ValueError, AttributeError):
            pass
    for n, length, steps in old or []:
        if not (0 <= n < PATTERNS and isinstance(steps, dict)):
            continue
        p = st.patterns[n]
        for k, v in steps.items():
            try:
                fxs = v[0] if isinstance(v[0], list) else [v[0]]
                for fx in fxs:
                    fx = int(fx)
                    if 1 <= fx <= LANES:
                        ln = p.lanes[fx - 1]
                        ln.length = max(1, min(sequencer.MAX_STEPS, int(length)))
                        ln.steps[int(k)] = sequencer.chance_index(v[1])
            except (TypeError, ValueError, IndexError):
                pass
