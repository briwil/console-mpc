"""The arpeggiator. It sits between the notes and the synth: the pads you hold (live) and the chords the sequencer plays
are turned into a run of single notes. Settings live in a dict (cfg) kept with the instrument's sequencer.

    MODE   UP, DOWN, UP-DOWN, DOWN-UP, RANDOM, AS PLAYED, CHORD (every step plays all the notes)
    OCT    1-4 octaves
    RATE   one of the sequencer's rates (an index into sequencer.RATES)
    GATE   how long each note lasts, % of a step (10-200: over 100 the notes overlap)
    HOLD   the notes stay on after you let go (until you press new ones)
    RHYTHM 16 steps: 0 rest, 1 note, 2 accent (a rest does not use up a note: the run carries on at the next one)
    GLIDE  portamento (the synth must respond to CC 65 / CC 5); the notes also overlap
    BEND   each note starts bent up (+) or down (-) and slides to its pitch (pitch bend, the synth's own range)
"""
import random
import sys

try:
    from sequencer import RATES
except ImportError:                                       # (the core's own tests)
    RATES = [("1/16", 4), ("1/16T", 6), ("1/8", 2), ("1/8T", 3), ("1/32", 8),
             ("1/4", 1), ("1/4T", 1.5), ("1/2", 0.5), ("1/2T", 0.75), ("1/1", 0.25)]

MODES = ["UP", "DOWN", "UP-DOWN", "DOWN-UP", "RANDOM", "AS PLAYED", "CHORD"]
# STYLE: five rhythm patterns over the 16 steps (0 rest, 1 note, 2 accent), laid over the hand-made rhythm
STYLES = ["OFF", "GALLOP", "OFFBEAT", "TRESILLO", "SYNCOPATED", "STUTTER"]
STYLE_PATTERNS = [
    [2, 1, 0, 1] * 4,
    [1, 0, 2, 0] * 4,
    [2, 0, 0, 1, 0, 0, 1, 0] * 2,
    [2, 0, 1, 1, 0, 2, 0, 1, 1, 0, 2, 0, 1, 1, 0, 0],
    [2, 1, 1, 1, 0, 1, 1, 1, 2, 1, 1, 1, 0, 0, 1, 1],
]
LOOKAHEAD = 2205                                          # frames (50 ms): live steps are sent this far ahead
SLIDE_STEPS = 4                                           # a BEND is sent as this many pitch-bend messages


def default():
    return {"on": 0, "mode": 0, "oct": 1, "rate": 0, "gate": 50, "hold": 0, "rhythm": [1] * 16, "glide": 0, "bend": 0, "style": 0}


def clean(d):
    """A saved dict -> a good one (missing or odd values become the defaults)."""
    out = default()
    if isinstance(d, dict):
        try:
            out["on"] = 1 if d.get("on") else 0
            out["mode"] = max(0, min(len(MODES) - 1, int(d.get("mode", 0))))
            out["oct"] = max(1, min(4, int(d.get("oct", 1))))
            out["rate"] = max(0, min(len(RATES) - 1, int(d.get("rate", 0))))
            out["gate"] = max(10, min(200, int(d.get("gate", 50))))
            out["hold"] = 1 if d.get("hold") else 0
            r = [max(0, min(2, int(x))) for x in (d.get("rhythm") or [])][:16]
            out["rhythm"] = r + [1] * (16 - len(r))
            out["glide"] = max(0, min(100, int(d.get("glide", 0))))
            out["bend"] = max(-100, min(100, int(d.get("bend", 0))))
            out["style"] = max(0, min(len(STYLES) - 1, int(d.get("style", 0))))
        except (TypeError, ValueError):
            return default()
    return out


def cycle(notes, mode, octs):
    """The run for these notes (in the order played), as a list of tuples of notes (CHORD: one tuple of all of them)."""
    if not notes:
        return []
    if mode == 6:
        return [tuple(sorted(n + 12 * o for o in range(octs) for n in notes))]
    base = notes if mode == 5 else sorted(notes)
    up = [(n + 12 * o,) for o in range(octs) for n in base]
    if mode == 1:
        return up[::-1]
    if mode in (2, 3):
        run = up if mode == 2 else up[::-1]
        return run + run[-2:0:-1]
    return up


class Arp:
    """One instrument's arp. cfg: its settings dict. The Slot sets fpb (frames per beat) and origin (the core frame the
    sequencer's frame 0 is at, or None when it isn't playing) before each look."""

    def __init__(self, seed=None):
        self.cfg = default()
        self.fpb = 44100 * 0.5
        self.origin = None
        self.rng = random.Random(seed)
        self.reset()

    def reset(self):
        self.held = []                  # notes played (in order), latched ones too
        self.down = set()               # the keys physically down
        self.vel = {}
        self.next_t = None
        self.j = 0
        self.kfree = 0
        self.glide_on = False
        self.sounding = []              # (off_frame, note) of what was sent, for a stop

    @property
    def on(self):
        return bool(self.cfg.get("on"))

    def step_frames(self):
        return self.fpb / RATES[self.cfg["rate"]][1]

    # ------------------------------------------------------------ one step
    def _one(self, notes, j, k, vel):
        """What step number k of the grid does: (notes, velocity) or None for a rest. notes: this run's notes."""
        c = self.cfg
        r = c["rhythm"][k % 16]
        if c.get("style"):                                    # a style on top of the rhythm: a rest in either is a rest
            st = STYLE_PATTERNS[c["style"] - 1][k % 16]
            r = 0 if (r == 0 or st == 0) else max(r, st)
        if r == 0:
            return None
        run = cycle(notes, c["mode"], c["oct"])
        if not run:
            return None
        pick = self.rng.choice(run) if c["mode"] == 4 else run[j % len(run)]
        v = min(127, int(vel * 1.3) + 10) if r == 2 else vel
        return pick, max(1, v)

    def _send(self, midi, src, at, notes, vel, step):
        c = self.cfg
        length = max(1, int(step * c["gate"] / 100.0))
        if c["glide"]:
            length = max(length, int(step * 1.05))                       # legato: the next note starts before this one ends
            if not self.glide_on:
                midi(src, 0xB0, 65, 127, at=at)
                midi(src, 0xB0, 5, int(c["glide"] * 127 / 100), at=at)
                self.glide_on = True
        bend = c["bend"]
        for n in notes:
            if bend:
                for s in range(SLIDE_STEPS):
                    frac = 1.0 - s / float(SLIDE_STEPS)
                    v = int(8192 + (bend / 100.0) * 8191 * frac)
                    midi(src, 0xE0, v & 127, v >> 7, at=at + int(length * s / (SLIDE_STEPS * 2.0)))
                midi(src, 0xE0, 0, 64, at=at + int(length * 0.5))
            midi(src, 0x90, max(0, min(127, n)), vel, at=at)
            midi(src, 0x80, max(0, min(127, n)), 0, at=at + length)
            self.sounding.append((at + length, n))
        self.sounding = self.sounding[-64:]

    def _glide_off(self, midi, src, at):
        if self.glide_on:
            midi(src, 0xB0, 65, 0, at=at)
            self.glide_on = False

    # ------------------------------------------------------------ the sequencer's chords
    def expand(self, midi, src, groups):
        """groups: [(at, [notes], velocity, gate_frames)] from the sequencer. Each chord becomes a run over its length."""
        step = self.step_frames()
        for at, notes, vel, gate in groups:
            n = max(1, int(-(-gate // step) if gate > 0 else 1))
            if step > 0 and gate / step - int(gate / step) < 0.05:
                n = max(1, int(gate / step))
            j = 0
            for i in range(n):
                t = at + int(i * step)
                k = int(round((t - self.origin) / step)) if self.origin is not None else i
                got = self._one(notes, j, k, vel)
                if got is None:
                    continue
                j += 1
                self._send(midi, src, t, got[0], got[1], step)
            self._glide_off(midi, src, at + int(n * step) + 1)

    # ------------------------------------------------------------ the pads
    def press(self, note, vel):
        if self.cfg["hold"] and not self.down:
            self.held = []                                    # new notes after letting everything go: they replace the latched ones
        self.down.add(note)
        if note not in self.held:
            self.held.append(note)
        self.vel[note] = vel

    def release(self, note):
        self.down.discard(note)
        if not self.cfg["hold"] and note in self.held:
            self.held.remove(note)

    def unhold(self):
        """HOLD switched off: the latched notes go (what is still down stays)."""
        self.held = [n for n in self.held if n in self.down]

    def tick(self, midi, src, now):
        """Every few ms: send the live steps falling before now + LOOKAHEAD."""
        if not self.cfg["hold"] and self.held:                # HOLD off: only what is still down stays
            self.held = [n for n in self.held if n in self.down]
        if not self.held:
            if self.next_t is not None:
                self._glide_off(midi, src, now)
            self.next_t, self.j, self.kfree = None, 0, 0
            return
        step = self.step_frames()
        if step <= 0:
            return
        if self.next_t is None:
            if self.origin is not None:                       # the sequencer is playing: on its grid
                k = int(-(-(now - self.origin) // step))
                self.next_t = self.origin + k * step
            else:
                self.next_t = now
        while self.next_t < now + LOOKAHEAD:
            t = int(self.next_t)
            k = int(round((t - self.origin) / step)) if self.origin is not None else self.kfree
            self.kfree += 1
            vel = self.vel.get(self.held[0], 100)
            got = self._one(list(self.held), self.j, k, vel)
            if got is not None:
                self.j += 1
                self._send(midi, src, t, got[0], got[1], step)
            self.next_t += step

    def stop(self, midi, src, now):
        """Stop / all notes off: forget what is held and let go of what we started."""
        for _off, n in self.sounding:
            midi(src, 0x80, n, 0, at=now)
        self.sounding = []
        self._glide_off(midi, src, now)
        midi(src, 0xE0, 0, 64, at=now)
        self.reset()
