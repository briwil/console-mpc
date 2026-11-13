"""Recorded automation: knob moves recorded while playing, one value per step, on every step (not only where
notes start), played back as the steps go by, so a filter sweep over a held note sounds like a sweep.

Each pattern (drum or synth) has its own: pattern.auto = {setting: Lane}. A lane has its own length and rate (the
ones of the lane or pattern it was recorded on) and its steps' values. A step with no value: the knob's own value
(sent once, after a run of steps with values). Step locks on notes still win on their notes.
"""
import math

import sequencer

AUTO = "auto"                          # (the "lane" of an automation event: (offset, AUTO, 0, {setting: value or None}))


class Lane:
    def __init__(self, length=16, rate=0):
        self.length = length
        self.rate = rate
        self.steps = {}                    # step -> value


def lanes(pattern):
    """The pattern's automation lanes (made the first time)."""
    a = getattr(pattern, "auto", None)
    if a is None:
        a = pattern.auto = {}
    return a


def step_frames(seq, ln, fpb):
    trip = getattr(seq, "trip", False)
    return fpb / (sequencer.RATES[ln.rate][1] * (sequencer.TRIP_SPEED if trip else 1.0))


def position(seq, ln, frame, fpb):
    """(slot k counted from the pattern's start, step number) at sequencer time frame; (None, None) before it."""
    sf = step_frames(seq, ln, fpb)
    k = math.floor((frame - seq.anchor) / sf + 1e-9)
    if k < 0:
        return None, None
    trip = getattr(seq, "trip", False)
    n = max(1, sequencer.live_len(ln.length, trip))
    return k, sequencer.phys(k % n, trip)


def record(seq, pattern, param, value, frame, fpb, length, rate):
    """Put value on the step playing at frame (the lane made with this length and rate if new)."""
    a = lanes(pattern)
    ln = a.get(param)
    if ln is None:
        ln = a[param] = Lane(length, rate)
    _k, i = position(seq, ln, frame, fpb)
    if i is not None:
        ln.steps[i] = int(value)
    return i


GLIDE_GAP = 128                        # frames between glide points at the closest (about 3 ms)


class Glide(int):
    """A value on the way from one step's value to the next (a menu setting skips these: it only takes the
    steps' own values)."""


def events(seq, start, n, fpb):
    """The automation in sequencer frames [start, start + n): [(offset, AUTO, 0, {setting: value or None})].
    Two steps in a row with values: the setting glides from one to the other over the step."""
    a = getattr(seq.pattern, "auto", None)
    if not a:
        return []
    trip = getattr(seq, "trip", False)
    out = {}

    def put(t, param, v):
        if start <= t < start + n:
            out.setdefault(int(round(t - start)), {})[param] = v

    for param, ln in a.items():
        if not ln.steps:
            continue
        sf = step_frames(seq, ln, fpb)
        live = max(1, sequencer.live_len(ln.length, trip))
        k = max(0, math.ceil((start - seq.anchor) / sf - 1e-9) - 1)     # (the step before: its glide may reach in)
        while True:
            t = seq.anchor + k * sf
            if t >= start + n:
                break
            i = sequencer.phys(k % live, trip)
            if i in ln.steps:
                v = ln.steps[i]
                put(t, param, v)
                nxt = sequencer.phys((k + 1) % live, trip)
                if nxt in ln.steps and ln.steps[nxt] != v and t + sf > start:
                    w = ln.steps[nxt]
                    diff = w - v
                    points = min(abs(diff), max(1, int(sf // GLIDE_GAP)))
                    for j in range(1, points):                  # (the next step's own value comes at its start)
                        put(t + sf * j / points, param, Glide(round(v + diff * j / points)))
            elif k == 0 or sequencer.phys((k - 1) % live, trip) in ln.steps:
                put(t, param, None)                              # back to the knob's own value
            k += 1
    return [(off, AUTO, 0, d) for off, d in sorted(out.items())]


def to_json(pattern):
    a = getattr(pattern, "auto", None)
    if not a:
        return None
    return {str(p): {"length": ln.length, "rate": ln.rate, "steps": {str(i): v for i, v in ln.steps.items()}}
            for p, ln in a.items() if ln.steps}


def from_json(pattern, data):
    pattern.auto = {}
    if not isinstance(data, dict):
        return
    for p, ld in data.items():
        try:
            ln = Lane(max(1, min(sequencer.MAX_STEPS, int(ld.get("length", 16)))),
                      max(0, min(len(sequencer.RATES) - 1, int(ld.get("rate", 0)))))
            ln.steps = {int(i): int(v) for i, v in (ld.get("steps") or {}).items() if 0 <= int(i) < sequencer.MAX_STEPS}
            if ln.steps:
                pattern.auto[int(p)] = ln
        except (TypeError, ValueError, AttributeError):
            pass
