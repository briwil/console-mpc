"""The drum sequencer: 16 patterns, each with 7 lanes (the drum synth's voices, with the hi-hat's open
and closed sounds as two lanes) of up to 64 steps.

Each step: on/off, velocity, chance, ratchets (quick repeats inside the step) and parameter locks
(drum settings that change for that step only). Each lane: its own length (1-64, looping on its own),
rate (1/16, triplets...) and a Euclidean fill.

Timing runs on the sequencer's own clock, not the tape's: frames since PLAY (engine.seq_clock), so every
PLAY starts the pattern from step 1 and tape loops or moving the playhead don't touch it (Brian: they're
separate things). Step k of a lane starts at anchor + k * (frames per step) on that clock. The audio
thread asks events() for each block it plays. The screen and keys change things through the methods here; one lock keeps the
two threads apart.
"""
import copy
import math
import random
import threading

MAX_LANES = 16          # lanes kept in every pattern: the drum machine uses its own number of them
LANES = MAX_LANES       #   (LXR 7, 606 8, 808 16: drums.Drums().lanes)
MAX_STEPS = 64
PATTERNS = 16
LANE_NAMES = ["DRUM 1", "DRUM 2", "DRUM 3", "SNARE", "CYMBAL", "CLOSED HAT", "OPEN HAT"]
LANE_VOICE = [0, 1, 2, 3, 4, 5, 5]          # the drum synth voice each lane plays (its settings)
# (name, steps per beat). The first five keep their places (saved songs store the place); RATE_ORDER is the order
# the knob steps through them: slowest to fastest.
RATES = [("1/16", 4), ("1/16T", 6), ("1/8", 2), ("1/8T", 3), ("1/32", 8),
         ("1/4", 1), ("1/4T", 1.5), ("1/2", 0.5), ("1/2T", 0.75), ("1/1", 0.25)]
RATE_ORDER = sorted(range(len(RATES)), key=lambda i: RATES[i][1])


# TRIPLETS (SETTINGS, saved with the song): every 4th step is dark (steps 4, 8, 12, 16 don't play and can't be
# set) and the others play 3 in the time of 4, so 1/16 sounds as 1/8T, 1/8 as 1/4T, 1/32 as 1/16T. The steps on
# the dark buttons are kept (they come back when it's off). TRIPLETS is what was asked for; each sequencer's own
# .trip follows it when its pattern next comes round (or at once while stopped).
TRIPLETS = False
TRIP_SPEED = 0.75
STEP_IDLE = 119                                      # the Move: an empty step's light (119: dark grey, the dimmest white). console/stepdim
                                                     # can hold another colour number to try (read while Console runs)                                    # 3 steps in the time of 4


def dark(i, trip):
    """A dark step (every 4th) while triplets are on."""
    return bool(trip) and i % 4 == 3


def live_len(length, trip):
    """How many of a lane's steps play: all of them, or (triplets) all but every 4th."""
    return length - length // 4 if trip else length


def phys(a, trip):
    """The a-th step that plays -> its step number (triplets: past the dark ones)."""
    return a + a // 3 if trip else a


def played(i, trip):
    """A step number -> how many steps play before it (the inverse of phys, for a step that isn't dark)."""
    return i - i // 4 if trip else i


STRAIGHT = [i for i in RATE_ORDER if not RATES[i][0].endswith("T")]    # (the step sequencer's RATE choices)


def next_straight_rate(rate, delta):
    """The sequencer's RATE knob: straight rates only (TRIPLETS makes them triplets); a lane still on an old
    triplet rate goes to the straight one next to it."""
    if rate in STRAIGHT:
        at = STRAIGHT.index(rate)
        return STRAIGHT[max(0, min(len(STRAIGHT) - 1, at + (1 if delta > 0 else -1)))]
    spb = RATES[rate][1]
    if delta > 0:
        faster = [i for i in STRAIGHT if RATES[i][1] > spb]
        return faster[0] if faster else STRAIGHT[-1]
    slower = [i for i in STRAIGHT if RATES[i][1] < spb]
    return slower[-1] if slower else STRAIGHT[0]


def next_rate(rate, delta):
    """The rate one step slower (delta < 0) or faster (delta > 0) than this one (an index into RATES)."""
    at = RATE_ORDER.index(rate) if rate in RATE_ORDER else RATE_ORDER.index(0)
    return RATE_ORDER[max(0, min(len(RATE_ORDER) - 1, at + (1 if delta > 0 else -1)))]
# chance: a percentage, or "A:B": plays on the A-th time round the lane out of every B
CHANCES = ["%d%%" % p for p in range(100, -1, -10)] + ["1:2", "2:2", "1:3", "2:3", "3:3", "1:4", "2:4", "3:4", "4:4"]
# songs saved before October 2026 stored chance as a place in this older list
OLD_CHANCES = ["100%", "90%", "75%", "50%", "25%", "10%", "1:2", "2:2", "1:3", "2:3", "3:3", "1:4", "2:4", "3:4", "4:4"]


def chance_index(saved):
    """A saved chance (its text now; a number in the old list before) -> its place in CHANCES."""
    if isinstance(saved, (int, float)) and not isinstance(saved, bool):
        saved = OLD_CHANCES[max(0, min(len(OLD_CHANCES) - 1, int(saved)))]
    saved = str(saved)
    if saved in CHANCES:
        return CHANCES.index(saved)
    if saved.endswith("%"):                          # 75% and 25% went: the nearest ten, rounding up
        try:
            p = min(100, max(0, int(-(-int(saved[:-1]) // 10) * 10)))
            return CHANCES.index("%d%%" % p)
        except ValueError:
            pass
    return 0
MAX_RATCHET = 8         # MULTIPLY: 1-8 hits in the step (0: a random number of them)
UNDO_STEPS = 10
DEFAULT_VELOCITY = 100  # (velocity 0: random)

# Step components (OP-XY style, set on the Move): name -> its options (a step stores the option's place)
#   pulse  play the step again this many times before moving on    hold   wait this many steps, silent
#   jump   then go to this step (once round the lane)                rand / rup / rdown  the drum's pitch:
#   random, or a ramp up / down, over N steps of 1 or 3 octaves (each time round the lane)
_N9 = [str(n) for n in range(1, 10)] + ["RND"]
_PITCH = ["%d/%dOCT" % (n, o) for o in (1, 3) for n in range(2, 7)]
COMPONENTS = {"pulse": _N9, "hold": _N9, "jump": ["1", "5", "9", "13", "+1", "-1", "+/-", "RND"],
              "rand": _PITCH, "rup": _PITCH, "rdown": _PITCH,
              "nudge": ["%+d%%" % n for n in (-50, -40, -30, -20, -10, 10, 20, 30, 40, 50)]}   # a step early / late
PITCH = None            # set by the Move app: PITCH(lane, locks, semitones) -> locks with the pitch moved


def cpass(comp, name, cycle, rng):
    """Does a step component happen this time? Its chance is kept in the same dict, as comp[name + "_c"]
    (a place in CHANCES; missing: 100%). rng: a random.Random, so the answer is the same for the same slot."""
    idx = comp.get(name + "_c", 0)
    if not idx:
        return True
    c = CHANCES[idx]
    if c.endswith("%"):
        return rng.random() * 100 < int(c[:-1])
    a, b = (int(v) for v in c.split(":"))
    return cycle % b == a - 1


def comp_ok(key, x):
    """Is this a saved component (or its chance, "pulse_c") with a place that exists?"""
    if key.endswith("_c") and key[:-2] in COMPONENTS or key == "ratchet_c":
        return 0 <= x < len(CHANCES)
    return key in COMPONENTS and 0 <= x < len(COMPONENTS[key])


def comp_keys(comp):
    """The step's components only (without their chances)."""
    return {k for k in comp if k in COMPONENTS}


class Step:
    __slots__ = ("on", "vel", "chance", "ratchet", "locks", "comp")

    def __init__(self):
        self.on = False
        self.vel = DEFAULT_VELOCITY
        self.chance = 0
        self.ratchet = 1
        self.locks = {}                      # drum parameter number -> value, for this step only
        self.comp = {}                       # step components: name -> option (see COMPONENTS)

    def blank(self):
        return not self.on and not self.locks and self.vel == DEFAULT_VELOCITY and not self.chance and \
            self.ratchet == 1 and not self.comp


def bar_steps(steps_per_beat, bar_beats):
    """Steps in one bar at this rate (bar_beats: quarter notes in a bar), or None if it isn't whole."""
    n = steps_per_beat * bar_beats
    return int(round(n)) if abs(n - round(n)) < 1e-6 and 1 <= round(n) <= MAX_STEPS else None


def group_steps(steps_per_beat, time_sig):
    """How many steps between the grey lines on the grid: one beat of the time signature at this rate
    (a quarter in x/4, a dotted quarter in 6/8, 9/8, 12/8, an eighth in 5/8, 7/8); a bar, or a quarter
    note, when a beat isn't a whole number of steps or is just one."""
    num, den = time_sig
    beat = 1.5 if (den == 8 and num % 3 == 0) else 4.0 / den
    n = steps_per_beat * beat
    if abs(n - round(n)) < 1e-6 and round(n) >= 2:
        return int(round(n))
    return bar_steps(steps_per_beat, num * 4.0 / den) or max(1, int(round(steps_per_beat)))


class Lane:
    def __init__(self, length=16):
        self.length = length
        self.rate = 0                        # index into RATES
        self.hits = 0                        # Euclidean fill: hits spread over the length (0: off)
        self.rotate = 0
        self.steps = [Step() for _ in range(MAX_STEPS)]

    def steps_per_beat(self):
        return RATES[self.rate][1]


class Pattern:
    def __init__(self, length=16):
        self.lanes = [Lane(length) for _ in range(LANES)]

    def empty(self):
        return not any(s.on or s.locks for lane in self.lanes for s in lane.steps)


def euclid(hits, length, rotate=0):
    """hits spread as evenly as possible over length steps, starting on the first step (then rotated)."""
    if length <= 0:
        return []
    hits = max(0, min(length, hits))
    on = [hits and (i * hits) % length < hits for i in range(length)]
    rotate %= length
    return on[-rotate:] + on[:-rotate] if rotate else on


def chance_passes(chance, loop_count):
    c = CHANCES[chance]
    if c.endswith("%"):
        p = int(c[:-1])
        return p >= 100 or random.random() * 100 < p
    a, b = (int(v) for v in c.split(":"))
    return loop_count % b == a - 1


class Sequencer:
    def __init__(self):
        self.lock = threading.RLock()
        self.bar_beats = 4.0                 # quarter notes in a bar (the song's time signature)
        self.patterns = [Pattern(self.new_length()) for _ in range(PATTERNS)]
        self.current = 0
        self.queued = None                   # the pattern to switch to at the end of this one
        self.anchor = 0.0                    # tape frame where the current pattern's step 0 falls
        self._decided = {}                   # (lane, k) -> chance result, so ratchets agree across blocks
        self._skip = set()                   # (lane, k): a step recorded live just before it came round
        self.undo_stack = []                 # (pattern number, copy of it before an edit), newest last
        self._cyc = {}                       # lane -> [time round, its first slot, its path, previous start, path]
        self.seed = random.randrange(1 << 30)
        self.trip = TRIPLETS                 # triplets as this sequencer plays them now (see TRIPLETS)

    @property
    def pattern(self):
        return self.patterns[self.current]

    def spb(self, ln):
        """A lane's steps per beat as it plays (triplets: 3 in the time of 4)."""
        return ln.steps_per_beat() * (TRIP_SPEED if self.trip else 1.0)

    def follow_triplets(self, playing):
        """TRIPLETS changed: stopped, take it now (playing: events() takes it when the pattern comes round)."""
        with self.lock:
            if not playing and self.trip != TRIPLETS:
                self.trip = TRIPLETS
                self._cyc.clear()
                self._decided.clear()

    # ------------------------------------------------------------ editing (from the screen's thread)

    def new_length(self):
        """A new lane's length: one bar of the time signature at 1/16."""
        return bar_steps(RATES[0][1], self.bar_beats) or 16

    def set_bar_beats(self, bar_beats):
        """The time signature changed: empty patterns start again at one bar of it."""
        with self.lock:
            old = self.bar_beats
            self.bar_beats = bar_beats
            if abs(old - bar_beats) < 1e-9:
                return
            for p in self.patterns:
                if p.empty():
                    for ln in p.lanes:
                        ln.length = bar_steps(ln.steps_per_beat(), bar_beats) or ln.length
                        ln.hits, ln.rotate = 0, 0

    def snapshot(self):
        """Keep the current pattern as it is, for undo (call before changing it)."""
        with self.lock:
            self.undo_stack.append((self.current, copy.deepcopy(self.pattern)))
            del self.undo_stack[:-UNDO_STEPS]

    def undo(self):
        """Put back the last change. Returns the pattern number it was in, or None if there's nothing."""
        with self.lock:
            if not self.undo_stack:
                return None
            n, pattern = self.undo_stack.pop()
            import punch
            if punch.undo_entry(self, n, pattern):
                return self.current
            self.patterns[n] = pattern
            return n

    def live_place(self, lane, tape_frame, frames_per_beat):
        """A drum key pressed while recording: put a step on the lane's nearest step to when you pressed it.
        Returns the step number."""
        with self.lock:
            ln = self.lane(lane)
            step_frames = frames_per_beat / self.spb(ln)
            k = round((tape_frame - self.anchor) / step_frames)
            i = phys(k % live_len(ln.length, self.trip), self.trip)
            ln.steps[i].on = True
            if self.anchor + k * step_frames > tape_frame:
                self._skip.add((lane, k))    # it's just ahead: you've played it already, don't play it twice
            return i

    def clear_all_locks(self):
        """Every step lock in every pattern goes (they belong to one drum machine's settings)."""
        with self.lock:
            for p in self.patterns:
                for ln in p.lanes:
                    for s in ln.steps:
                        s.locks = {}

    def lane(self, i):
        return self.pattern.lanes[i]

    def step(self, lane, i):
        return self.pattern.lanes[lane].steps[i]

    def toggle(self, lane, i):
        with self.lock:
            s = self.step(lane, i)
            s.on = not s.on
            return s.on

    def set_lock(self, lane, i, param, value):
        with self.lock:
            s = self.step(lane, i)
            s.locks[param] = int(value)
            s.on = True                      # locking a step plays it
            return s

    def clear_locks(self, lane, i):
        with self.lock:
            self.step(lane, i).locks.clear()

    def change_step(self, lane, i, what, delta):
        """what: "vel", "chance" or "ratchet". Returns the new value."""
        with self.lock:
            s = self.step(lane, i)
            if what == "vel":
                s.vel = max(1, min(127, s.vel + delta))
            elif what == "chance":
                s.chance = max(0, min(len(CHANCES) - 1, s.chance + (1 if delta > 0 else -1)))
            elif what == "ratchet":
                s.ratchet = max(1, min(MAX_RATCHET, s.ratchet + (1 if delta > 0 else -1)))
            s.on = True
            return getattr(s, what)

    def change_lane(self, lane, what, delta):
        """what: "length", "hits", "rotate" or "rate". Returns the new value."""
        with self.lock:
            ln = self.lane(lane)
            if what == "length":
                ln.length = max(1, min(MAX_STEPS, ln.length + delta))
                ln.hits = min(ln.hits, ln.length)
                ln.rotate %= ln.length
                if ln.hits:
                    self._fill(ln)
            elif what == "rate":                      # a pure speed change: the steps stay as they are
                ln.rate = next_straight_rate(ln.rate, delta)
            elif what == "hits":
                ln.hits = max(0, min(ln.length, ln.hits + (1 if delta > 0 else -1)))
                self._fill(ln)
            elif what == "rotate":
                ln.rotate = (ln.rotate + (1 if delta > 0 else -1)) % ln.length
                if ln.hits:
                    self._fill(ln)
            return getattr(ln, what)

    @staticmethod
    def _fill(ln):
        """Euclidean fill: turn the lane's steps on and off (velocities and locks stay on their steps)."""
        n = live_len(ln.length, TRIPLETS)                 # (triplets: spread over the steps that play)
        for a, on in enumerate(euclid(ln.hits, n, ln.rotate)):
            ln.steps[phys(a, TRIPLETS)].on = bool(on)

    def choose_pattern(self, n, playing):
        """Pick pattern n: straight away when stopped, else at the end of the current one."""
        with self.lock:
            n = max(0, min(PATTERNS - 1, n))
            import lfo
            lfo.inherit(self, n)
            if not playing or n == self.current:
                self.current, self.queued = n, None
            else:
                self.queued = n

    def stop(self):
        """The tape stopped: a queued pattern takes over, and the next play starts from the tape's bars."""
        with self.lock:
            if self.queued is not None:
                self.current, self.queued = self.queued, None
            self.anchor = 0.0
            import punch
            punch.stop(self)
            self._decided.clear()
            self._skip.clear()
            self._cyc.clear()

    # ------------------------------------------------------------ playing (from the audio thread)

    def pattern_frames(self, frames_per_beat):
        return max(live_len(ln.length, self.trip) * frames_per_beat / self.spb(ln) for ln in self.pattern.lanes)

    def events(self, start, frames, frames_per_beat):
        """The hits whose time falls in [start, start + frames) tape frames:
        [(offset in frames, lane, velocity, locks)], in time order."""
        out = []
        with self.lock:
            end = start + frames
            import punch
            if self.queued is not None or self.trip != TRIPLETS or punch.pending(self):
                length = self.pattern_frames(frames_per_beat)
                boundary = self.anchor + math.ceil((start - self.anchor) / length - 1e-9) * length
                if boundary < end:
                    out += self._events(start, boundary, start, frames_per_beat)
                    if self.queued is not None:
                        self.current, self.queued = self.queued, None
                    punch.take_queued(self, boundary)
                    self.trip = TRIPLETS                 # (triplets on / off: from the pattern's start)
                    self.anchor = boundary
                    self._decided.clear()
                    self._cyc.clear()
                    out += self._events(boundary, end, start, frames_per_beat)
                    return out
            out += self._events(start, end, start, frames_per_beat)
            if len(self._decided) > 512:
                self._decided.clear()
        return out

    # ---- the order a lane plays its steps in (pulse, hold and jump change it)

    def _path(self, li, ln, cycle):
        """One time round the lane: [(step, plays)]. Random choices are the same for the same time round."""
        L = ln.length
        trip = getattr(self, "trip", False)
        rng = random.Random(hash((self.seed, li, cycle)))
        path, i, used = [], 0, set()
        while True:
            while dark(i, trip):                         # (triplets: the dark steps are passed over)
                i += 1
            if not (i < L and len(path) < 4 * L):
                break
            c = ln.steps[i].comp
            path.append((i, True))
            if "pulse" in c and not cpass(c, "pulse", cycle, rng):
                c = {k: v for k, v in c.items() if k != "pulse"}
            if "hold" in c and not cpass(c, "hold", cycle, rng):
                c = {k: v for k, v in c.items() if k != "hold"}
            if "jump" in c and not cpass(c, "jump", cycle, rng):
                c = {k: v for k, v in c.items() if k != "jump"}
            if "pulse" in c:
                n = c["pulse"] + 1 if c["pulse"] < 9 else rng.randint(1, 9)
                path += [(i, True)] * n
            if "hold" in c:
                n = c["hold"] + 1 if c["hold"] < 9 else rng.randint(1, 9)
                path += [(i, False)] * n
            nxt = i + 1
            if "jump" in c and i not in used:
                used.add(i)
                j = COMPONENTS["jump"][c["jump"]]
                if j in ("1", "5", "9", "13"):
                    nxt = int(j) - 1
                elif j == "+1":
                    nxt = i + 2
                elif j == "-1":
                    nxt = max(0, i - 1)
                elif j == "+/-":
                    nxt = i + 2 if rng.random() < 0.5 else max(0, i - 1)
                else:
                    nxt = rng.randrange(L)
            i = nxt
        return path or [(0, True)]

    def _slot(self, li, ln, k):
        """Slot k (counting from PLAY) of a lane: (step, plays, time round the lane)."""
        L = ln.length
        trip = getattr(self, "trip", False)
        if not any(ln.steps[i].comp.keys() & {"pulse", "hold", "jump"} for i in range(L)):
            self._cyc.pop(li, None)
            n = live_len(L, trip) or 1
            return phys(k % n, trip), True, k // n
        st = self._cyc.get(li)
        if st and st[3] is not None and st[3] <= k < st[1]:
            i, plays = st[4][k - st[3]]
            return i, plays, st[0] - 1
        if st is None or k < st[1]:
            st = self._cyc[li] = [0, 0, None, None, None]
        while True:
            path = self._path(li, ln, st[0])
            if k < st[1] + len(path):
                st[2] = path
                i, plays = path[k - st[1]]
                return i, plays, st[0]
            st[3], st[4] = st[1], path
            st[1] += len(path)
            st[0] += 1

    def _events(self, a, b, block_start, fpb):
        out = []
        for li, ln in enumerate(self.pattern.lanes):
            step_frames = fpb / self.spb(ln)
            first = math.floor((a - self.anchor) / step_frames)
            last = math.floor((b - self.anchor) / step_frames)
            for k in range(first - 1, last + 2):        # (a nudged step can land in a neighbour's time)
                if k < 0:
                    continue
                i, plays, cycle = self._slot(li, ln, k)
                s = ln.steps[i]
                if not s.on or not plays:
                    continue
                if (li, k) in self._skip:
                    if self.anchor + k * step_frames + step_frames <= b:
                        self._skip.discard((li, k))
                    continue
                t0 = self.anchor + k * step_frames
                crng = random.Random(hash((self.seed, li, k, "c")))
                if "nudge" in s.comp and cpass(s.comp, "nudge", cycle, crng):
                    t0 += float(COMPONENTS["nudge"][s.comp["nudge"]].rstrip("%")) / 100 * step_frames
                rng = random.Random(hash((self.seed, li, k)))
                hits = s.ratchet if s.ratchet else rng.randint(1, MAX_RATCHET)
                if hits > 1 and not cpass(s.comp, "ratchet", cycle, crng):
                    hits = 1                                  # (MULTIPLY didn't happen this time: one hit)
                vel = s.vel if s.vel else rng.randint(1, 127)
                locks = dict(s.locks)
                c = s.comp
                name = None
                if PITCH and c.keys() & {"rand", "rup", "rdown"}:
                    name = "rand" if "rand" in c else "rup" if "rup" in c else "rdown"
                    if not cpass(c, name, cycle, crng):
                        name = None
                if PITCH and name:
                    n, octs = (int(v) for v in COMPONENTS[name][c[name]].replace("OCT", "").split("/"))
                    d = rng.randrange(n) if name == "rand" else cycle % n
                    semis = round(d * 12 * octs / n) * (-1 if name == "rdown" else 1)
                    try:
                        locks = PITCH(li, locks, semis, self)
                    except Exception:
                        pass
                for r in range(hits):
                    t = t0 + r * step_frames / hits
                    if a <= t < b:
                        key = (li, k)
                        if key not in self._decided:
                            self._decided[key] = chance_passes(s.chance, cycle)
                        if self._decided[key]:
                            out.append((int(t - block_start), li, vel, locks))
        out.sort(key=lambda e: e[0])
        return out

    def position(self, tape_frame, frames_per_beat):
        """Which step each lane is on at this tape frame: [step index] (for the screen)."""
        with self.lock:
            out = []
            for li, ln in enumerate(self.pattern.lanes):
                k = math.floor((tape_frame - self.anchor) / (frames_per_beat / self.spb(ln)))
                n = live_len(ln.length, self.trip) or 1
                out.append(self._slot(li, ln, k)[0] if k >= 0 else phys(k % n, self.trip))
            return out

    # ------------------------------------------------------------ saving

    def to_json(self):
        with self.lock:
            pats = []
            for p in self.patterns:
                lanes = []
                for ln in p.lanes:
                    steps = {}
                    for i, s in enumerate(ln.steps):
                        if not s.blank():
                            steps[str(i)] = [int(s.on), s.vel, CHANCES[s.chance], s.ratchet,
                                             {str(k): v for k, v in s.locks.items()}, dict(s.comp)]
                    lanes.append({"length": ln.length, "rate": ln.rate, "hits": ln.hits, "rotate": ln.rotate, "steps": steps})
                import lfo
                pats.append({"lanes": lanes, "lfos": lfo.to_json(p), "auto": __import__("autom").to_json(p)})
            import punch
            return {"current": self.current, "patterns": pats, "punchfx": punch.to_json(self)}

    def from_json(self, data):
        with self.lock:
            self.patterns = [Pattern(self.new_length()) for _ in range(PATTERNS)]
            self.current, self.queued, self.anchor = 0, None, 0.0
            import punch
            punch.from_json(self, None)
            if not isinstance(data, dict):
                return
            old = [(n, max(ld.get("length", 16) for ld in pd.get("lanes") or [{}]), pd.get("punch"))
                   for n, pd in enumerate(data.get("patterns", [])) if isinstance(pd, dict) and pd.get("punch")]
            punch.from_json(self, data.get("punchfx"), old)
            try:
                for p, pd in zip(self.patterns, data.get("patterns", [])):
                    import lfo
                    lfo.from_json(p, pd.get("lfos"))
                    __import__("autom").from_json(p, pd.get("auto"))
                    for ln, ld in zip(p.lanes, pd.get("lanes", [])):
                        ln.length = max(1, min(MAX_STEPS, int(ld.get("length", 16))))
                        ln.rate = max(0, min(len(RATES) - 1, int(ld.get("rate", 0))))
                        ln.hits = max(0, min(ln.length, int(ld.get("hits", 0))))
                        ln.rotate = int(ld.get("rotate", 0)) % ln.length
                        for i, v in (ld.get("steps") or {}).items():
                            i = int(i)
                            if 0 <= i < MAX_STEPS:
                                s = ln.steps[i]
                                s.on, s.vel, s.chance, s.ratchet = bool(v[0]), int(v[1]), chance_index(v[2]), int(v[3])
                                s.ratchet = max(0, min(MAX_RATCHET, s.ratchet))
                                s.locks = {int(k): int(x) for k, x in (v[4] if len(v) > 4 else {}).items()}
                                s.comp = {k: int(x) for k, x in (v[5] if len(v) > 5 else {}).items()
                                          if comp_ok(k, int(x))}
                self.current = max(0, min(PATTERNS - 1, int(data.get("current", 0))))
            except (TypeError, ValueError, KeyError, IndexError, AttributeError) as e:
                print("Sequencer: couldn't read the saved patterns:", e)
