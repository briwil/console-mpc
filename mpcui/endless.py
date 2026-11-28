"""ENDLESS: a sequencer like the OP-1's Endless, for synths and drum machines (MPC only; Console's own files are not changed).

An instrument plays either its step sequencer (STEP) or ENDLESS. Picked in the ARP pop-up's second page (NOTE REPEAT, then
right: GLIDE, BEND, SEQUENCER) for a synth, in the PADS pop-up (PAD FX: OCTAVE, VELOCITY, CURVE, SEQUENCER) for a drum machine.

The line: up to 128 steps, each a note (a drum, on a drum machine), a rest, or a tie (the note before it holds on). Each of the
instrument's 16 patterns has its own line, so song mode works as before.

On its page (SEQ, when the instrument plays ENDLESS):
    SEQ RECORD      entry on / off. While on, a pad adds its note (its drum) at the end of the line, and plays it.
    PLUS            a rest            Shift + PLUS    the last note one step longer (a tie)
    MINUS           takes the last step off
    ERASE           twice within 2 s: clears the line
    K1 / K2 / K3    RATE / DIRECTION (FWD, REV, PING-PONG, RANDOM) / SWING
    Shift + K1-K3   STYLE (a rhythm over the line: rests in it skip a step, the line waits) / HOLD / GATE

It plays with the tape (PLAY), in time with everything else, round and round. While it plays, a synth's pads transpose the line
(the first note moves to the pad's note) instead of playing: let go and it goes back, unless HOLD is on.
"""
import random
import threading

import arp
import sequencer

KINDS = ["STEP", "ENDLESS"]
MAX = 128
DIRECTIONS = ["FWD", "REV", "PING-PONG", "RANDOM"]
DEFAULT_VEL = 100


class Endless:
    """The ENDLESS settings and lines of one instrument (kept on its sequencer as .endless)."""

    def __init__(self):
        self.kind = "STEP"
        self.lines = [[] for _ in range(sequencer.PATTERNS)]     # tokens: ["n", note or drum, velocity] / ["r"] / ["t"]
        self.rate = 0                                            # an index into sequencer.RATES (1/16)
        self.direction = 0
        self.swing = 50                                          # 50 = straight, up to 75
        self.style = 0                                           # an index into arp.STYLES (0: OFF)
        self.hold = 0
        self.gate = 90                                           # % of the note's steps
        self.transpose = 0                                       # (not saved) semitones, from the pads while it plays
        self.entry = False                                       # (not saved) SEQ RECORD on its page
        self.held = []                                           # (not saved) pads held for transposing, oldest first
        self.seed = random.randrange(1 << 30)

    # ------------------------------------------------------------ saving
    def to_json(self):
        return {"kind": self.kind, "lines": [[list(t) for t in ln] for ln in self.lines], "rate": self.rate,
                "direction": self.direction, "swing": self.swing, "style": self.style, "hold": self.hold, "gate": self.gate}

    def from_json(self, d):
        if not isinstance(d, dict):
            return
        try:
            self.kind = d.get("kind") if d.get("kind") in KINDS else "STEP"
            lines = []
            for ln in (d.get("lines") or [])[:sequencer.PATTERNS]:
                out = []
                for t in (ln or [])[:MAX]:
                    if t and t[0] == "n" and len(t) >= 2:
                        out.append(["n", max(0, min(127, int(t[1]))), max(1, min(127, int(t[2]) if len(t) > 2 else DEFAULT_VEL))])
                    elif t and t[0] in ("r", "t"):
                        out.append([t[0]])
                lines.append(out)
            self.lines = lines + [[] for _ in range(sequencer.PATTERNS - len(lines))]
            self.rate = max(0, min(len(sequencer.RATES) - 1, int(d.get("rate", 0))))
            self.direction = max(0, min(len(DIRECTIONS) - 1, int(d.get("direction", 0))))
            self.swing = max(50, min(75, int(d.get("swing", 50))))
            self.style = max(0, min(len(arp.STYLES) - 1, int(d.get("style", 0))))
            self.hold = 1 if d.get("hold") else 0
            self.gate = max(10, min(200, int(d.get("gate", 90))))
        except (TypeError, ValueError, AttributeError) as e:
            print("endless: couldn't read the saved line:", e, flush=True)

    # ------------------------------------------------------------ where the line is
    def mask(self):
        return arp.STYLE_PATTERNS[self.style - 1] if self.style else None

    def played_before(self, k):
        """How many steps played before step k (a rest of the STYLE doesn't count: the line waits)."""
        m = self.mask()
        if m is None:
            return k
        ones = sum(1 for x in m if x)
        full, part = divmod(k, len(m))
        return full * ones + sum(1 for x in m[:part] if x)

    def index(self, n, L):
        """The line's step for the n-th step played."""
        if L <= 1:
            return 0
        d = self.direction
        if d == 1:
            return L - 1 - n % L
        if d == 2:
            p = n % (2 * L - 2)
            return p if p < L else 2 * L - 2 - p
        if d == 3:
            return random.Random(hash((self.seed, n))).randrange(L)
        return n % L

    def where(self, k, L):
        """(the line's step, accent) for step k of the clock, or None when the STYLE rests there."""
        m = self.mask()
        a = 0
        if m is not None:
            a = m[k % len(m)]
            if not a:
                return None
        return self.index(self.played_before(k), L), a == 2

    # ------------------------------------------------------------ editing (the screen / key threads)
    def line(self, seq):
        return self.lines[seq.current]

    def add(self, seq, token):
        with seq.lock:
            ln = self.line(seq)
            if len(ln) >= MAX:
                return False
            if token[0] == "t" and not ln:
                return False                                     # (a tie needs a note before it)
            ln.append(token)
            return True

    def drop_last(self, seq):
        with seq.lock:
            ln = self.line(seq)
            if ln:
                ln.pop()
                return True
            return False

    def clear(self, seq):
        with seq.lock:
            self.lines[seq.current] = []

    def first_note(self, seq):
        for t in self.line(seq):
            if t[0] == "n":
                return t[1]
        return None

    # ------------------------------------------------------------ playing (the audio thread)
    def events(self, seq, start, frames, fpb, synth):
        """As the sequencers' events(): [(offset, note / drum, velocity, locks)]; a synth's notes carry "gate" (frames)."""
        out = []
        with seq.lock:
            if seq.silent and seq.queued is None:
                return out
            spb = sequencer.RATES[self.rate][1]
            step = fpb / spb
            end = start + frames
            k = max(0, int(start // step) - 1)
            swing = (2.0 * self.swing / 100.0 - 1.0) * step                   # how late the off-beat steps come
            while True:
                t = k * step + (swing if k % 2 else 0.0)
                if t >= end:
                    break
                if t >= start:
                    ln = self.lines[seq.current]
                    got = self.where(k, len(ln)) if ln else None
                    if got is not None and got[0] == 0 and seq.queued is not None and self.played_before(k) > 0:
                        seq.current, seq.queued = seq.queued, None               # a pattern picked while it plays: at the line's start
                        if seq.queued_silent is not None:
                            seq.silent, seq.queued_silent = seq.queued_silent, None
                        ln = self.lines[seq.current]
                        got = self.where(k, len(ln)) if ln else None
                    if got is not None and not seq.silent:
                        i, accent = got
                        tok = ln[i]
                        if tok[0] == "n":
                            ties = 0
                            while i + 1 + ties < len(ln) and ln[i + 1 + ties][0] == "t":
                                ties += 1
                            vel = min(127, tok[2] + 20) if accent else tok[2]
                            if synth:
                                note = max(0, min(127, tok[1] + self.transpose))
                                gate = max(64, int((1 + ties) * step * self.gate / 100.0))
                                out.append((int(t - start), note, vel, {"gate": gate}))
                            else:
                                out.append((int(t - start), tok[1], vel, {}))
                k += 1
        return out

    def playing_index(self, seq, frame, fpb):
        """The line's step playing at this sequencer frame (for the screen), or None."""
        ln = self.lines[seq.current]
        if not ln:
            return None
        step = fpb / sequencer.RATES[self.rate][1]
        k = int(frame // step)
        for back in range(16):                                   # (a STYLE rest: the step before it is still sounding)
            if k - back < 0:
                return None
            got = self.where(k - back, len(ln))
            if got is not None:
                return got[0]
        return None


def of(seq):
    """The instrument's ENDLESS (made the first time it's asked for)."""
    en = getattr(seq, "endless", None)
    if en is None:
        en = Endless()
        try:
            seq.endless = en
        except AttributeError:
            pass
    return en


def active(seq):
    en = getattr(seq, "endless", None)
    return en is not None and en.kind == "ENDLESS"


# ------------------------------------------------------------------ hooking the sequencers (called once, from mpc_app.py)

def install_engine():
    """Both kinds of sequencer play ENDLESS when it's picked, and keep it in the project."""
    import notes
    for cls, synth in ((sequencer.Sequencer, False), (notes.NoteSequencer, True)):
        if getattr(cls, "_endless_hooked", False):
            continue
        o_events, o_to, o_from = cls.events, cls.to_json, cls.from_json

        def events(self, start, frames, fpb, _o=o_events, _synth=synth):
            en = getattr(self, "endless", None)
            if en is not None and en.kind == "ENDLESS":
                return en.events(self, start, frames, fpb, _synth)
            return _o(self, start, frames, fpb)

        def to_json(self, _o=o_to):
            d = _o(self)
            en = getattr(self, "endless", None)
            if en is not None and isinstance(d, dict):
                d["endless"] = en.to_json()
            return d

        def from_json(self, data, _o=o_from):
            _o(self, data)
            en = of(self)
            fresh = Endless()
            fresh.seed = en.seed
            self.endless = fresh
            if isinstance(data, dict):
                fresh.from_json(data.get("endless"))

        cls.events, cls.to_json, cls.from_json = events, to_json, from_json
        cls._endless_hooked = True
