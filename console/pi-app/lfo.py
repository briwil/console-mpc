"""Two LFOs for every instrument, each aimed at one of its settings (modelled on the Syntakt's); a sampler has two
for each of its drums. They belong to a
pattern: each pattern keeps its own two (the first time you pick a pattern it starts as a copy of the one you
came from, after that they're separate).

  DEST   which setting it moves (a number setting of the instrument; a list or mode isn't moved)
  WAVE   SINE, TRIANGLE, SAW UP, SAW DOWN, SQUARE, RANDOM (a new random value each cycle)
  SPEED  how long one cycle is: 8 bars down to 1/8 of a beat, in time with the tempo; RND: a new one each cycle
  DEPTH  how far it swings each way, -100..+100 % of the setting's range
  PHASE  where in the cycle it starts
  MODE   FREE (runs on with the song) or TRIG (starts again at the pattern's first step)
  STEPS  16 steps (1/16 notes, one bar), each can be muted (the LFO rests) or lock its own DEPTH or WAVE
The setting goes up and down around the value it has on the instrument's page.
"""
import copy
import math
import time
import random

WAVES = ["SINE", "TRIANGLE", "SAW UP", "SAW DOWN", "SQUARE", "RANDOM"]
SPEEDS = [("8BAR", 32.0), ("4BAR", 16.0), ("2BAR", 8.0), ("1BAR", 4.0), ("1/2", 2.0), ("1/4", 1.0),
          ("1/8", 0.5), ("1/16", 0.25), ("1/32", 0.125),
          # triplets (added later: songs store the place, so new ones go at the end; SPEED_ORDER is the knob's order)
          ("1/2T", 4 / 3), ("1/4T", 2 / 3), ("1/8T", 1 / 3), ("1/16T", 1 / 6),
          ("RND", None)]                       # every cycle a new speed, 1/16 to 1 bar, in time (rnd_phase)
RND = len(SPEEDS) - 1
SPEED_ORDER = sorted(range(RND), key=lambda i: -SPEEDS[i][1]) + [RND]   # slow to fast: 1/4, 1/4T, 1/8... then RND
RND_LENGTHS = [4.0, 2.0, 1.0, 0.5, 0.25]       # the beats a RND cycle can last


def rnd_phase(beats, seed):
    """SPEED RND: each bar is cut into cycles of random lengths (1 bar down to 1/16), each starting on a multiple
    of its own length, so it stays in time. The same bar always cuts the same way (no state to lose)."""
    bar = int(math.floor(beats / 4.0))
    pos, n, at = 0.0, 0, beats - bar * 4.0
    while True:
        r = random.Random(hash((seed, bar, n)) & 0xFFFFFFFF)
        fits = [ln for ln in RND_LENGTHS if pos % ln == 0 and pos + ln <= 4.0]
        ln = r.choice(fits)
        if at < pos + ln or pos + ln >= 4.0:
            return bar * 64 + n + (at - pos) / ln          # (the whole part: a new one each cycle, for WAVE RANDOM)
        pos += ln
        n += 1


def next_speed(speed, way):
    """The knob's next speed (slow to fast, each triplet after its straight one)."""
    at = SPEED_ORDER.index(speed) if speed in SPEED_ORDER else 0
    return SPEED_ORDER[max(0, min(len(SPEED_ORDER) - 1, at + (1 if way > 0 else -1)))]
MODES = ["FREE", "TRIG"]
COUNT = 2
STEPS = 16
INSERT_DEST = 1000                 # a dest at or above this is an insert effect's setting: 1000 + 8 * (insert 0 / 1) + knob 0-7


def default():
    return {"dest": -1, "wave": 0, "speed": 3, "depth": 50, "phase": 0, "mode": 0, "steps": {}}


def defaults():
    return [default() for _ in range(COUNT)]


def of(pattern, n=COUNT):
    """A pattern's LFOs (made if it has none). n: how many it needs (a sampler: two per drum, COUNT * drums;
    drum v's are v * COUNT and v * COUNT + 1)."""
    if not hasattr(pattern, "lfos") or pattern.lfos is None:
        pattern.lfos = defaults()
    while len(pattern.lfos) < n:
        pattern.lfos.append(default())
    return pattern.lfos


def per_drum(machine):
    """How many drums have LFOs of their own (a sampler: every one; anything else: 0, the instrument has two)."""
    return int(getattr(machine, "lanes", 0) or 0) if getattr(machine, "id", "") == "sampler" else 0


def spread(pattern, machine):
    """A sampler's song from before each drum had its own: an LFO aimed at drum v's setting moves to drum v's."""
    lf = pattern.lfos
    for j in range(COUNT):
        l = lf[j]
        d = l.get("dest", -1)
        if 0 <= d < INSERT_DEST:
            try:
                v = int(machine.params[d]["voice"])
            except Exception:                            # noqa: BLE001
                continue
            k = v * COUNT + j
            if v and k < len(lf) and lf[k].get("dest", -1) < 0:
                lf[k], lf[j] = l, default()


def inherit(seq, n):
    """Picking pattern n: a pattern that has never had LFOs starts as a copy of the current one's."""
    p = seq.patterns[n]
    if getattr(p, "lfos", None) is None:
        cur = getattr(seq.pattern, "lfos", None)
        p.lfos = copy.deepcopy(cur) if cur else None


def to_json(pattern):
    l = getattr(pattern, "lfos", None)
    if l is None:
        return None
    out = copy.deepcopy(l)
    for o in out:
        o["steps"] = {str(k): v for k, v in o.get("steps", {}).items()}
    return out


def from_json(pattern, data):
    try:
        out = [default() for _ in range(max(COUNT, min(256, len(data or []))))]
        for o, d in zip(out, data or []):
            o["dest"] = int(d.get("dest", -1))
            o["wave"] = max(0, min(len(WAVES) - 1, int(d.get("wave", 0))))
            o["speed"] = max(0, min(len(SPEEDS) - 1, int(d.get("speed", 3))))
            o["depth"] = max(-100, min(100, int(d.get("depth", 50))))
            o["phase"] = max(0, min(100, int(d.get("phase", 0))))
            o["mode"] = max(0, min(len(MODES) - 1, int(d.get("mode", 0))))
            o["steps"] = {int(k): {a: int(b) for a, b in v.items() if a in ("depth", "wave", "mute")}
                          for k, v in (d.get("steps") or {}).items() if 0 <= int(k) < STEPS}
        pattern.lfos = out if data else None
    except (TypeError, ValueError, AttributeError):
        pattern.lfos = None


def wave(shape, ph, cycle, seed):
    """-1..1 at phase ph (cycles; the whole part counts the cycle for RANDOM)."""
    f = ph - math.floor(ph)
    if shape == 0:
        return math.sin(2 * math.pi * f)
    if shape == 1:
        return 4 * abs(f - 0.5) - 1 if False else 1 - 4 * abs(f - 0.5)
    if shape == 2:
        return 2 * f - 1
    if shape == 3:
        return 1 - 2 * f
    if shape == 4:
        return 1.0 if f < 0.5 else -1.0
    return random.Random(hash((seed, int(math.floor(ph)))) & 0xFFFFFFFF).uniform(-1, 1)


def settings_dest(machine, only_voice=None):
    """[param indexes] an LFO can move on this instrument: the number settings, in page order (only_voice: just
    that drum's)."""
    out = []
    try:
        for voice in range(max(1, getattr(machine, "voices", 1))):
            if only_voice is not None and voice != only_voice:
                continue
            for _name, params in machine.pages(voice):
                for p in params:
                    if p not in out and machine.kind(p) in ("num", "pm", "send") and p < machine.param_count:
                        out.append(p)
    except Exception:
        pass
    return out


def top(machine, p):
    try:
        return int(machine.params[p].get("steps", 127))
    except Exception:
        return 127


class Runner:
    """Moves the settings the LFOs aim at (called often, from the sound core's bridge). It sends the setting to the
    instrument without changing the value kept on its page, so the LFO swings around that."""

    def __init__(self, engine):
        self.e = engine
        self.last = {}                 # (slot, lfo) -> (dest, last value sent)

    def tick(self):
        e = self.e
        try:
            fpb = e.frames_per_beat()
        except Exception:
            return
        for k, mid in enumerate(e.slots):
            m = e.drums.get(mid) if (mid and e.drums) else None
            seq = e.seqs.get(mid) if mid else None
            if m is None or seq is None:
                self._release(k, None)
                continue
            lfos = getattr(seq.pattern, "lfos", None) or []
            for j in range(max(COUNT, len(lfos))):
                l = lfos[j] if j < len(lfos) else None
                dest = l["dest"] if l else -1
                key = (k, j)
                prev = self.last.get(key)
                if prev and prev[0] != dest:
                    self._restore(k, m, prev[0])
                    self.last.pop(key, None)
                running = e.playing or k == e.slot          # stopped: the instrument you're on still moves (to play it by hand)
                ins = self._insert(k, dest)
                known = ins is not None if dest >= INSERT_DEST else 0 <= dest < getattr(m, "param_count", 0)
                if not l or dest < 0 or not known or not running:
                    if prev and prev[0] == dest and not running:
                        self._restore(k, m, dest)
                        self.last.pop(key, None)
                    continue
                if dest < INSERT_DEST and m.kind(dest) not in ("num", "pm", "send"):
                    continue
                if e.playing:
                    frame = e.seq_clock + e.read_ahead
                    if l["mode"] == 1:
                        frame -= getattr(seq, "anchor", 0)
                else:                                       # not playing: a clock of its own (TRIG has no pattern start to wait for)
                    frame = time.monotonic() * getattr(e, "rate", 44100)
                beats = frame / fpb
                if l["speed"] == RND:
                    ph = rnd_phase(beats, (k, j)) + l["phase"] / 100.0
                else:
                    ph = beats / SPEEDS[l["speed"]][1] + l["phase"] / 100.0
                lock = (l.get("steps") or {}).get(int(math.floor(beats * 4)) % STEPS)
                shape, depth = l["wave"], l["depth"]
                if lock:
                    shape, depth = lock.get("wave", shape), lock.get("depth", depth)
                v = 0.0 if lock and lock.get("mute") else wave(shape, ph, 0, (k, j))
                if dest >= INSERT_DEST:                     # an insert effect's setting (a number, in its own range)
                    idx = (dest - INSERT_DEST) % 8
                    _k, _l, lo, hi, _d, _s, _o = ins.params[idx]
                    base = ins.values.get(ins.params[idx][0], lo)
                    val = round(max(lo, min(hi, base + v * depth / 100.0 * (hi - lo) / 2)), 3)
                    if prev is None or prev[1] != val:
                        self.last[key] = (dest, val)
                        ins.modulate(idx, val)
                    continue
                base = m.get_param(dest)
                span = top(m, dest)
                val = int(round(max(0, min(span, base + v * depth / 100.0 * span / 2))))
                if prev is None or prev[1] != val:
                    self.last[key] = (dest, val)
                    self._send(m, dest, val)

    def _insert(self, k, dest):
        """The insert effect a dest (>= INSERT_DEST) points at on slot k, if it is loaded and that setting is a number."""
        if dest < INSERT_DEST:
            return None
        ins = (getattr(self.e, "insert_fx", None) or {}).get((k, (dest - INSERT_DEST) // 8))
        idx = (dest - INSERT_DEST) % 8
        if ins is None or not ins.h or idx >= len(ins.params) or ins.params[idx][6]:
            return None
        return ins

    def _release(self, k, _m):
        for key in [x for x in self.last if x[0] == k]:
            self.last.pop(key, None)

    def _restore(self, k, m, dest):
        try:
            if dest >= INSERT_DEST:
                ins = (getattr(self.e, "insert_fx", None) or {}).get((k, (dest - INSERT_DEST) // 8))
                if ins is not None:
                    ins.restore((dest - INSERT_DEST) % 8)
                return
            self._send(m, dest, m.get_param(dest))
        except Exception:
            pass

    @staticmethod
    def _send(m, index, value):
        with m._lock:
            m._pending.append(("param", index, int(value)))
