"""The synth sequencer: 16 patterns of notes, like the Deluge's: each row of the grid is a note of the scale,
and a step can have any number of notes (a chord), each with its own length.

A pattern has one length (1-64 steps) and rate for all its notes. Any row (lane) can have a length of its
own (SHIFT + the pattern-length knob), so it loops on its own cycle against the rest, as on the Deluge.
Each note: its length in steps (it
holds over the steps after it), velocity, chance, ratchets and parameter locks (synth settings for that
note only), as the drum sequencer's steps have.

The rows: the song's key (root) and scale make the rows' notes; the grid shows 8 rows at a time, `low` being
the lowest one's place in the scale (0 = the root at C-1, MIDI 0's octave). The arrows move it an octave.
Notes are kept as MIDI numbers, so changing the scale doesn't change what's there.

It has the same methods the audio thread and the instrument pages use on the drum sequencer (events,
stop, choose_pattern, snapshot / undo, to_json...). events() gives each note's length in its locks, as
"gate" (frames), for the synth (schwung/modules.py SynthModule) to let go of it.
"""
import copy
import math
import threading

import random

import arp
import sequencer
from sequencer import (next_rate, CHANCES, DEFAULT_VELOCITY, MAX_RATCHET, MAX_STEPS, PATTERNS, RATES, UNDO_STEPS, bar_steps,
                       chance_index, chance_passes)

ROWS = 8                             # rows on screen (and track keys)
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALES = [("MAJOR", [0, 2, 4, 5, 7, 9, 11]), ("MINOR", [0, 2, 3, 5, 7, 8, 10]),
          ("DORIAN", [0, 2, 3, 5, 7, 9, 10]), ("PHRYGIAN", [0, 1, 3, 5, 7, 8, 10]),
          ("LYDIAN", [0, 2, 4, 6, 7, 9, 11]), ("MIXOLYDIAN", [0, 2, 4, 5, 7, 9, 10]),
          ("LOCRIAN", [0, 1, 3, 5, 6, 8, 10]), ("HARM MINOR", [0, 2, 3, 5, 7, 8, 11]),
          ("MEL MINOR", [0, 2, 3, 5, 7, 9, 11]), ("MAJ PENTA", [0, 2, 4, 7, 9]), ("MIN PENTA", [0, 3, 5, 7, 10]),
          ("BLUES", [0, 3, 5, 6, 7, 10]), ("CHROMATIC", list(range(12)))]
MAX_LENGTH = MAX_STEPS               # a note can hold for up to a whole pattern


def note_name(n):
    """60 -> C4 (middle C)."""
    return "%s%d" % (NAMES[n % 12], n // 12 - 1)


class Note:
    __slots__ = ("length", "vel", "chance", "ratchet", "locks", "nudge", "comp")

    def __init__(self, length=1, vel=DEFAULT_VELOCITY):
        self.length = length
        self.vel = vel
        self.chance = 0
        self.ratchet = 1
        self.locks = {}
        self.comp = {}                   # step components (pulse, hold, jump, rand, rup, rdown): name -> option, see sequencer.COMPONENTS
        self.nudge = 0                   # a step early (-) or late (+), in percent of a step (0: on the beat)


class NotePattern:
    def __init__(self, length=16):
        self.length = length
        self.rate = 0                    # index into RATES
        self.notes = {}                  # step -> {MIDI note: Note}
        self.lane_len = {}               # MIDI note -> its own length in steps (no entry: the pattern's)
        self.lane_rate = {}              # MIDI note -> its own rate (an index into RATES; no entry: the pattern's)

    def lane_length(self, pitch):
        return self.lane_len.get(pitch, self.length)

    def steps_per_beat(self, pitch=None):
        if pitch is not None and pitch in self.lane_rate:
            return RATES[self.lane_rate[pitch]][1]
        return RATES[self.rate][1]

    def empty(self):
        return not any(self.notes.values())

    def at(self, step):
        return self.notes.get(step) or {}


class _Steps:
    """One pitch's row as the drum sequencer's path code sees a lane: .steps[i].comp"""
    def __init__(self, pat, pitch):
        self.pat, self.pitch = pat, pitch

    def __getitem__(self, i):
        n = self.pat.notes.get(i, {}).get(self.pitch)
        return n if n is not None else _EMPTY


class _Empty:
    comp = {}


_EMPTY = _Empty()


class _Row:
    def __init__(self, pat, pitch):
        self.length = pat.lane_length(pitch)
        self.steps = _Steps(pat, pitch)


class NoteSequencer:
    kind = "notes"
    seed = 0
    _path = sequencer.Sequencer._path           # pulse / hold / jump: the order a row plays its steps in
    _slot = sequencer.Sequencer._slot

    def __init__(self):
        self.lock = threading.RLock()
        self.bar_beats = 4.0
        self.patterns = [NotePattern(self.new_length()) for _ in range(PATTERNS)]
        self.current = 0
        self.queued = None
        self.anchor = 0.0
        self.root = 0                    # C
        self.scale = 0                   # MAJOR
        self.low = 5 * 7                 # the lowest row on screen: middle C (C4), in C major
        self._decided = {}
        self._skip = set()
        self._cyc = {}
        self.seed = random.randrange(1 << 30)
        self.undo_stack = []
        self.arp_cfg = arp.default()     # the instrument's arpeggiator (all its patterns)
        self.trip = sequencer.TRIPLETS   # triplets as it plays now (see sequencer.TRIPLETS)

    @property
    def pattern(self):
        return self.patterns[self.current]

    def _tf(self):
        return sequencer.TRIP_SPEED if self.trip else 1.0

    def follow_triplets(self, playing):
        """TRIPLETS changed: stopped, take it now (playing: events() takes it when the pattern comes round)."""
        with self.lock:
            if not playing and self.trip != sequencer.TRIPLETS:
                self.trip = sequencer.TRIPLETS
                self._cyc.clear()
                self._decided.clear()

    # ------------------------------------------------------------ the rows
    def degrees(self):
        return SCALES[self.scale][1]

    def row_note(self, row):
        """A row's note (row counted from the root at MIDI 0's octave)."""
        d = self.degrees()
        return self.root + 12 * (row // len(d)) + d[row % len(d)]

    def note_row(self, note):
        """The row a note is on, or None if it isn't in the scale."""
        d = self.degrees()
        octave, rest = divmod(note - self.root, 12)
        return octave * len(d) + d.index(rest) if rest in d else None

    def shown_notes(self):
        """The notes of the 8 rows on screen, lowest first (row 1 is track key 1)."""
        return [self.row_note(self.low + r) for r in range(ROWS)]

    def move_rows(self, rows):
        """The arrows: up or down (an octave is len(scale) rows), kept within MIDI's 0-127."""
        with self.lock:
            top = self.note_row_floor(127) - ROWS + 1
            self.low = max(0, min(top, self.low + rows))
            return self.low

    def note_row_floor(self, note):
        """The highest row whose note is at most this one."""
        r = 0
        while self.row_note(r + 1) <= note:
            r += 1
        return r

    def set_scale(self, root=None, scale=None):
        """Change the key or scale, keeping the lowest row's note about where it was."""
        with self.lock:
            keep = self.row_note(self.low)
            if root is not None:
                self.root = root % 12
            if scale is not None:
                self.scale = max(0, min(len(SCALES) - 1, scale))
            self.low = self.note_row_floor(keep)

    # ------------------------------------------------------------ editing
    def new_length(self):
        return bar_steps(RATES[0][1], self.bar_beats) or 16

    def set_bar_beats(self, bar_beats):
        with self.lock:
            old = self.bar_beats
            self.bar_beats = bar_beats
            if abs(old - bar_beats) < 1e-9:
                return
            for p in self.patterns:
                if p.empty():
                    p.length = bar_steps(p.steps_per_beat(), bar_beats) or p.length

    def snapshot(self):
        with self.lock:
            self.undo_stack.append((self.current, copy.deepcopy(self.pattern)))
            del self.undo_stack[:-UNDO_STEPS]

    def undo(self):
        with self.lock:
            if not self.undo_stack:
                return None
            n, pattern = self.undo_stack.pop()
            import punch
            if punch.undo_entry(self, n, pattern):
                return self.current
            self.patterns[n] = pattern
            return n

    def note(self, step, note):
        return self.pattern.at(step).get(note)

    def covering(self, step, note):
        """The step whose note of this pitch is sounding at this step (it, or one that holds over it)."""
        p = self.pattern
        for s in range(step, -1, -1):
            n = p.at(s).get(note)
            if n is not None:
                return s if s + n.length > step else None
        return None

    def toggle(self, step, note, length=1):
        """Put a note on a step, or take it off. Returns True if it's there now."""
        with self.lock:
            notes = self.pattern.notes.setdefault(step, {})
            if note in notes:
                del notes[note]
                if not notes:
                    del self.pattern.notes[step]
                return False
            notes[note] = Note(length)
            return True

    def change_note(self, step, note, what, delta):
        """what: "length", "vel", "chance" or "ratchet". Returns the new value (None if there's no note)."""
        with self.lock:
            n = self.note(step, note)
            if n is None:
                return None
            if what == "length":
                n.length = max(1, min(MAX_LENGTH, n.length + delta))
            elif what == "vel":
                n.vel = max(1, min(127, n.vel + delta))
            elif what == "chance":
                n.chance = max(0, min(len(CHANCES) - 1, n.chance + (1 if delta > 0 else -1)))
            elif what == "ratchet":
                n.ratchet = max(1, min(MAX_RATCHET, n.ratchet + (1 if delta > 0 else -1)))
            return getattr(n, what)

    def set_lock(self, step, note, param, value):
        with self.lock:
            n = self.note(step, note)
            if n is None:
                n = self.pattern.notes.setdefault(step, {})[note] = Note()
            n.locks[param] = int(value)
            return n

    def change_lane_length(self, pitch, delta):
        """One row's own length (steps). Back at the pattern's length, it follows the pattern again."""
        with self.lock:
            p = self.pattern
            n = max(1, min(MAX_STEPS, p.lane_length(pitch) + delta))
            if n == p.length:
                p.lane_len.pop(pitch, None)
            else:
                p.lane_len[pitch] = n
            return n

    def change_lane_rate(self, pitch, delta):
        """One row's own rate. Back at the pattern's rate, it follows the pattern again. Returns its rate (an index)."""
        with self.lock:
            p = self.pattern
            r = sequencer.next_straight_rate(p.lane_rate.get(pitch, p.rate), delta)
            if r == p.rate:
                p.lane_rate.pop(pitch, None)
            else:
                p.lane_rate[pitch] = r
            return r

    def change_track(self, what, delta):
        """The pattern's "length" (steps) or "rate". Returns the new value."""
        with self.lock:
            p = self.pattern
            if what == "length":
                p.length = max(1, min(MAX_STEPS, p.length + delta))
            elif what == "rate":                      # a pure speed change: the steps stay as they are
                p.rate = sequencer.next_straight_rate(p.rate, delta)
            return getattr(p, what)

    def live_place(self, note, tape_frame, frames_per_beat, length=1, vel=DEFAULT_VELOCITY):
        """A note played while recording: onto the nearest step. Returns the step."""
        with self.lock:
            p = self.pattern
            step_frames = frames_per_beat / (p.steps_per_beat(note) * self._tf())
            k = round((tape_frame - self.anchor) / step_frames)
            i = sequencer.phys(k % (sequencer.live_len(p.lane_length(note), self.trip) or 1), self.trip)
            p.notes.setdefault(i, {})[note] = Note(length, vel)
            if self.anchor + k * step_frames > tape_frame:
                self._skip.add((note, k))
            return i

    def clear_all_locks(self):
        with self.lock:
            for p in self.patterns:
                for notes in p.notes.values():
                    for n in notes.values():
                        n.locks = {}

    def choose_pattern(self, n, playing):
        with self.lock:
            n = max(0, min(PATTERNS - 1, n))
            import lfo
            lfo.inherit(self, n)
            if not playing or n == self.current:
                self.current, self.queued = n, None
            else:
                self.queued = n

    def stop(self):
        with self.lock:
            if self.queued is not None:
                self.current, self.queued = self.queued, None
            self.anchor = 0.0
            import punch
            punch.stop(self)
            self._decided.clear()
            self._skip.clear()
            self._cyc.clear()

    # ------------------------------------------------------------ playing (the audio thread)
    def pattern_frames(self, frames_per_beat):
        p = self.pattern
        return sequencer.live_len(p.length, self.trip) * frames_per_beat / (p.steps_per_beat() * self._tf())

    def events(self, start, frames, frames_per_beat):
        """The notes starting in [start, start + frames): [(offset, note, velocity, locks with "gate")]."""
        out = []
        with self.lock:
            end = start + frames
            import punch
            if self.queued is not None or self.trip != sequencer.TRIPLETS or punch.pending(self):
                length = self.pattern_frames(frames_per_beat)
                boundary = self.anchor + math.ceil((start - self.anchor) / length - 1e-9) * length
                if boundary < end:
                    out += self._events(start, boundary, start, frames_per_beat)
                    if self.queued is not None:
                        self.current, self.queued = self.queued, None
                    punch.take_queued(self, boundary)
                    self.trip = sequencer.TRIPLETS       # (triplets on / off: from the pattern's start)
                    self.anchor = boundary
                    self._decided.clear()
                    self._cyc.clear()
                    out += self._events(boundary, end, start, frames_per_beat)
                    return out
            out += self._events(start, end, start, frames_per_beat)
            if len(self._decided) > 1024:
                self._decided.clear()
        return out

    def _events(self, a, b, block_start, fpb):
        """The pattern's rate, then each rate a row has chosen for itself (a row's own rate: its steps are longer
        or shorter than the pattern's)."""
        p = self.pattern
        f = self._tf()
        out = self._events_at(a, b, block_start, fpb, p.steps_per_beat() * f, lambda pitch: pitch not in p.lane_rate)
        for r in sorted(set(p.lane_rate.values())):
            out += self._events_at(a, b, block_start, fpb, RATES[r][1] * f, lambda pitch, r=r: p.lane_rate.get(pitch) == r)
        out.sort(key=lambda e: e[0])
        return out

    def _events_at(self, a, b, block_start, fpb, spb, want):
        out = []
        p = self.pattern
        step_frames = fpb / spb
        first = math.floor((a - self.anchor) / step_frames) - 1        # (a nudged note can start a step away)
        last = math.floor((b - self.anchor) / step_frames) + 1
        per_note = getattr(self, "move_type", 0) == 1
        rows = {}
        if per_note:                                          # every pitch is a row of its own: pulse / hold / jump work
            pitches = {pitch for ns in p.notes.values() for pitch in ns if want(pitch)}
            rows = {pitch: _Row(p, pitch) for pitch in pitches}
        for k in range(first, last + 1):
            if per_note:
                hits = []
                for pitch, row in rows.items():
                    if k < 0:
                        continue
                    i, plays, cycle = self._slot(pitch, row, k)
                    n = p.at(i).get(pitch)
                    if n is not None and plays:
                        hits.append((pitch, n, cycle))
            else:
                own = set(p.lane_len) | set(p.lane_rate)
                trip = self.trip
                L = sequencer.live_len(p.length, trip) or 1       # (triplets: the dark steps don't play)
                hits = [(pitch, n, k // L) for pitch, n in p.at(sequencer.phys(k % L, trip)).items()
                        if pitch not in own and want(pitch)]
                for pitch in own:                                  # a row with its own length or rate loops on its own
                    if not want(pitch):
                        continue
                    ln = sequencer.live_len(p.lane_length(pitch), trip) or 1
                    n = p.at(sequencer.phys(k % ln, trip)).get(pitch)
                    if n is not None:
                        hits.append((pitch, n, k // ln))
            for pitch, n, loop in hits:
                if (pitch, k) in self._skip:
                    if self.anchor + (k + 1) * step_frames <= b:
                        self._skip.discard((pitch, k))
                    continue
                c = n.comp
                nudge = n.nudge if n.nudge and sequencer.cpass(c, "nudge", loop, random.Random(hash((self.seed, pitch, k, "n")))) else 0
                t0 = self.anchor + k * step_frames + nudge / 100 * step_frames
                out_pitch = pitch
                crng = random.Random(hash((self.seed, pitch if per_note else -1, k, "c")))
                if c.keys() & {"rand", "rup", "rdown"} and sequencer.cpass(
                        c, "rand" if "rand" in c else "rup" if "rup" in c else "rdown", loop, crng):   # a pitch movement (a chord moves together in UNIFIED)
                    name = "rand" if "rand" in c else "rup" if "rup" in c else "rdown"
                    cnt, octs = (int(v) for v in sequencer.COMPONENTS[name][c[name]].replace("OCT", "").split("/"))
                    rng = random.Random(hash((self.seed, pitch if per_note else -1, k)))
                    d = rng.randrange(cnt) if name == "rand" else loop % cnt
                    out_pitch = max(0, min(127, pitch + round(d * 12 * octs / cnt) * (-1 if name == "rdown" else 1)))
                nh = n.ratchet if sequencer.cpass(c, "ratchet", loop, random.Random(hash((self.seed, pitch, k, "r")))) else 1
                each = step_frames / nh
                for r in range(nh):
                    t = t0 + r * each
                    if a <= t < b:
                        key = (pitch, k)
                        if key not in self._decided:
                            self._decided[key] = chance_passes(n.chance, loop)
                        if self._decided[key]:
                            # a ratchet's notes share the note's length; the last one holds to its end
                            gate = each * 0.9 if r < nh - 1 else n.length * step_frames - r * each - 1
                            locks = dict(n.locks)
                            locks["gate"] = max(1, int(gate))
                            out.append((int(t - block_start), out_pitch, n.vel, locks))
        return out

    def position(self, tape_frame, frames_per_beat):
        """The step playing (one per pattern: [step], like the drum sequencer's per-lane list)."""
        with self.lock:
            p = self.pattern
            k = math.floor((tape_frame - self.anchor) / (frames_per_beat / (p.steps_per_beat() * self._tf())))
            return [sequencer.phys(k % (sequencer.live_len(p.length, self.trip) or 1), self.trip)]

    def raw_step(self, tape_frame, frames_per_beat, pitch=None):
        """How many steps have played since the pattern began (a row with its own length wraps it itself); at a
        row's own rate, when its pitch is given."""
        with self.lock:
            return math.floor((tape_frame - self.anchor) / (frames_per_beat / (self.pattern.steps_per_beat(pitch) * self._tf())))

    # ------------------------------------------------------------ saving
    def to_json(self):
        with self.lock:
            pats = []
            for p in self.patterns:
                notes = {}
                for step, ns in p.notes.items():
                    for pitch, n in ns.items():
                        notes.setdefault(str(step), {})[str(pitch)] = [
                            n.length, n.vel, CHANCES[n.chance], n.ratchet, {str(k): v for k, v in n.locks.items()}, n.nudge, dict(n.comp)]
                import lfo
                pats.append({"length": p.length, "rate": p.rate, "notes": notes, "lfos": lfo.to_json(p), "auto": __import__("autom").to_json(p),
                             "lanes": {str(k): v for k, v in p.lane_len.items()},
                             "lane_rates": {str(k): v for k, v in p.lane_rate.items()}})
            return {"kind": "notes", "current": self.current, "root": self.root, "scale": self.scale,
                    "low": self.low, "move_type": getattr(self, "move_type", 0), "patterns": pats,
                    "arp": dict(self.arp_cfg), "punchfx": __import__("punch").to_json(self)}

    def from_json(self, data):
        with self.lock:
            self.patterns = [NotePattern(self.new_length()) for _ in range(PATTERNS)]
            self.current, self.queued, self.anchor = 0, None, 0.0
            self.arp_cfg.clear()
            self.arp_cfg.update(arp.clean(data.get("arp") if isinstance(data, dict) else None))
            import punch
            punch.from_json(self, None)
            if not isinstance(data, dict) or data.get("kind") != "notes":
                return
            old = [(n, pd.get("length", 16), pd.get("punch"))
                   for n, pd in enumerate(data.get("patterns", [])) if isinstance(pd, dict) and pd.get("punch")]
            punch.from_json(self, data.get("punchfx"), old)
            try:
                self.root = int(data.get("root", 0)) % 12
                self.scale = max(0, min(len(SCALES) - 1, int(data.get("scale", 0))))
                self.low = max(0, int(data.get("low", self.low)))
                self.move_type = 1 if int(data.get("move_type", 0)) else 0
                for p, pd in zip(self.patterns, data.get("patterns", [])):
                    p.length = max(1, min(MAX_STEPS, int(pd.get("length", 16))))
                    p.rate = max(0, min(len(RATES) - 1, int(pd.get("rate", 0))))
                    import lfo
                    lfo.from_json(p, pd.get("lfos"))
                    __import__("autom").from_json(p, pd.get("auto"))
                    p.lane_len = {int(k): max(1, min(MAX_STEPS, int(v))) for k, v in (pd.get("lanes") or {}).items()
                                  if 0 <= int(k) <= 127 and int(v) != p.length}
                    p.lane_rate = {int(k): max(0, min(len(RATES) - 1, int(v)))
                                   for k, v in (pd.get("lane_rates") or {}).items()
                                   if 0 <= int(k) <= 127 and int(v) != p.rate}
                    for step, ns in (pd.get("notes") or {}).items():
                        step = int(step)
                        if not 0 <= step < MAX_STEPS:
                            continue
                        for pitch, v in ns.items():
                            pitch = int(pitch)
                            if not 0 <= pitch <= 127:
                                continue
                            n = Note(max(1, min(MAX_LENGTH, int(v[0]))), max(1, min(127, int(v[1]))))
                            n.chance = chance_index(v[2])
                            n.ratchet = max(1, min(MAX_RATCHET, int(v[3])))
                            n.locks = {int(k): int(x) for k, x in (v[4] if len(v) > 4 else {}).items()}
                            n.nudge = max(-50, min(50, int(v[5]))) if len(v) > 5 else 0
                            n.comp = {k: int(x) for k, x in (v[6] if len(v) > 6 else {}).items()
                                      if k != "nudge" and sequencer.comp_ok(k, int(x))}
                            p.notes.setdefault(step, {})[pitch] = n
                self.current = max(0, min(PATTERNS - 1, int(data.get("current", 0))))
            except (TypeError, ValueError, KeyError, IndexError, AttributeError) as e:
                print("Synth sequencer: couldn't read the saved patterns:", e)
