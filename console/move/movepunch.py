"""The PUNCH FX page (left button 1 after AUTOMATION): a sequencer of punch-in effects on the instrument you're on,
one lane per effect (see punch.py).

  pads 1-16 (bottom two rows)   the effects. Tap: that effect's lane (its steps show on the step buttons).
                                Hold: it plays while held (several held: stacked); recording into the pattern
                                (Record, playing), it also goes on its lane's steps it's held over
  Shift + pad 1-16              punch pattern 1-16 (its own, apart from the note patterns; playing: it takes
                                over when the instrument's pattern next comes round)
  step buttons                  the lane's steps: tap on / off. Hold one: knob 1 is its chance. Hold one + tap
                                a later step: it lasts until there (again: back to one step). Hold one + tap
                                pads: those effects' steps there on / off. Delete + step: off
  knob 1, 2 (nothing held)      the lane's LENGTH and RATE (as the drum lanes; TRIPLETS too)
  knob 8                        TIME SCALE: every lane's steps that many times longer (long sweeps)
  Shift + Delete, twice         every lane of the punch pattern cleared
  < > (or the wheel)            steps 17-32...
"""
import time

import knobgate
import popup
import punch
import sequencer

PADS = punch.LANES                      # pads 0-15: the effects
# each effect's pad colour, by group: time (repeats orange, the others yellow), filters, crush / gate, pan / echo, kill
COLOUR = [3, 3, 3, 3, 3, 8, 8, 8, 11, 11, 11, 15, 15, 22, 22, 127]
CONFIRM_SECONDS = 4.0
SCALE_KNOB = 8


class Punch:
    def __init__(self, T):
        self.T = T
        self.lane = 0                 # the effect whose steps show
        self.held = None              # the step held down
        self.held_used = False        # (a knob or pad was used while it was held: letting go doesn't turn it off)
        self.held_was_on = False
        self.page = 0
        self.pads_down = []           # the effect pads held (0-15), in the order pressed
        self.confirm_until = 0.0
        self._snapped = None

    @property
    def pad_down(self):
        return self.pads_down[-1] if self.pads_down else None

    # ------------------------------------------------------------ what's shown
    def active(self):
        T = self.T
        return bool(T.seq_page and not T.fx_page and getattr(T, "auto_page", False) == "punch"
                    and T.engine and T.engine.drums)

    @property
    def seq(self):
        return self.T.engine.seq

    def st(self):
        return punch.state(self.seq)

    def pattern(self):
        return self.st().pattern

    def ln(self):
        return self.pattern().lanes[self.lane]

    def mid(self):
        e = self.T.engine
        return e.slots[e.slot] if e.slot is not None else None

    def trip(self):
        return bool(getattr(self.seq, "trip", False))

    def playing_step(self, lane=None):
        e = self.T.engine
        if not e.playing:
            return None
        try:
            return punch.lane_pos(self.seq, self.lane if lane is None else lane, e._heard_frame(), e.frames_per_beat())[1]
        except Exception:                                # noqa: BLE001
            return None

    def now(self):
        """The effects playing on this instrument now (a mask), or 0."""
        return self.T.engine.punch_now.get(self.mid(), 0)

    def held_mask(self):
        m = 0
        for p in self.pads_down:
            m = punch.with_fx(m, p + 1)
        return m

    def rate_name(self, ln=None):
        ln = ln or self.ln()
        name = sequencer.RATES[ln.rate][0]
        return name + "T" if self.trip() and not name.endswith("T") else name

    # ------------------------------------------------------------ controls
    def _snapshot(self, why):
        if self._snapped != why:
            punch.snapshot(self.seq)
            self._snapped = why

    def _live(self):
        """Tell the engine which pads are held now."""
        e = self.T.engine
        m = self.held_mask()
        e.punch_live = (self.mid(), m) if m else None
        if not m:
            e.punch_rec = False

    def pattern_pad(self, p):
        """Shift + pad: punch pattern p."""
        e = self.T.engine
        punch.choose(self.seq, p, e.playing)
        e.seq_changed()
        q = self.st().queued
        self.T.say("PUNCH PATTERN %d%s" % (p + 1, "  (NEXT)" if e.playing and q is not None else ""), 2)

    def pad(self, p, vel):
        """A pad on this page. Returns True (it's used here, never a note)."""
        e = self.T.engine
        if p >= PADS:
            return True
        if not vel:
            if p in self.pads_down:
                self.pads_down.remove(p)
                self._live()
                self._snapped = None
            return True
        if self.held is not None:                        # a step held: this effect's step there on / off
            i = self.held
            ln = self.pattern().lanes[p]
            if i < ln.length and not sequencer.dark(i, self.trip()):
                self._snapshot(("steppad", i, p, time.monotonic()))
                with self.seq.lock:
                    shown = self.ln()
                    if not self.held_was_on and not self.held_used and p != self.lane:
                        shown.steps.pop(i, None)         # (pressing the step put the shown lane's on: you meant this one)
                        shown.lens.pop(i, None)
                    on = i not in ln.steps
                    if on:
                        ln.steps[i] = 0
                    else:
                        ln.steps.pop(i, None)
                        ln.lens.pop(i, None)
                self.held_used = True
                e.seq_changed()
                popup.show(self.T, "STEP %d" % (i + 1), punch.name(p + 1), "ON" if on else "OFF")
            return True
        self.lane = p                                    # its lane shows, and it plays while held
        if self.page * 16 >= self.ln().length:
            self.page = 0
        if p not in self.pads_down:
            self.pads_down.append(p)
        rec = bool(getattr(self.T, "live_rec", False) and e.playing)
        if rec and not e.punch_rec:
            punch.snapshot(self.seq)
        self._live()
        e.punch_rec = rec
        return True

    def step(self, n, down, shift, deleting):
        i = self.page * 16 + n - 1
        ln = self.ln()
        if not down:
            if self.held == i:
                if self.held_was_on and not self.held_used:      # a tap on a step that was on: off
                    self._snapshot(("off", self.lane, i))
                    with self.seq.lock:
                        ln.steps.pop(i, None)
                        ln.lens.pop(i, None)
                    self.T.engine.seq_changed()
                self.held = None
                self._snapped = None
            return
        if i >= ln.length or sequencer.dark(i, self.trip()):
            return
        if self.held is not None and i != self.held and not deleting and not shift:
            self._span(self.held, i)                     # a step held + a later one tapped: it lasts until there
            return
        if deleting:
            if i in ln.steps:
                punch.snapshot(self.seq)
                with self.seq.lock:
                    ln.steps.pop(i, None)
                    ln.lens.pop(i, None)
                self.T.engine.seq_changed()
            return
        if shift:
            return
        self.held, self.held_used = i, False
        self.held_was_on = i in ln.steps
        if not self.held_was_on:                         # off: on straight away (hold it: knob 1 its chance)
            self._snapshot(("on", self.lane, i))
            with self.seq.lock:
                ln.steps[i] = 0
            self.T.engine.seq_changed()

    def _span(self, i, j):
        """Step i held, step j tapped: i lasts until j (counted round the lane's end; j already its end: one step)."""
        ln, trip = self.ln(), self.trip()
        n = max(1, sequencer.live_len(ln.length, trip))
        L = (sequencer.played(j, trip) - sequencer.played(i, trip)) % n + 1
        self._snapshot(("span", self.lane, i, time.monotonic()))
        with self.seq.lock:
            ln.steps.setdefault(i, 0)
            if ln.lens.get(i, 1) == L:
                L = 1
            if L > 1:
                ln.lens[i] = L
            else:
                ln.lens.pop(i, None)
        self.held_used = True
        self.T.engine.seq_changed()
        popup.show(self.T, "STEP %d" % (i + 1), punch.name(self.lane + 1), "%d STEP%s LONG" % (L, "" if L == 1 else "S"))

    def knob(self, number, delta, shift):
        e = self.T.engine
        ln, pat = self.ln(), self.pattern()
        if self.held is not None:
            if number != 1:
                return
            i = self.held
            if i not in ln.steps:
                return
            one = knobgate.gate(("punch-chance",), delta, shift)
            if not one:
                return
            self._snapshot(("chance", self.lane, i))
            with self.seq.lock:
                ln.steps[i] = max(0, min(len(sequencer.CHANCES) - 1, ln.steps[i] + one))
            self.held_used = True
            e.seq_changed()
            popup.show(self.T, "STEP %d" % (i + 1), punch.name(self.lane + 1), "CHANCE " + sequencer.CHANCES[ln.steps[i]])
            return
        if number == 1:                                  # LENGTH
            one = knobgate.gate(("punch-length",), delta, shift, 2)
            if not one:
                return
            self._snapshot(("length", self.lane))
            with self.seq.lock:
                ln.length = max(1, min(sequencer.MAX_STEPS, ln.length + one))
            if self.page * 16 >= ln.length:
                self.page = (ln.length - 1) // 16
            e.seq_changed()
            popup.show(self.T, punch.name(self.lane + 1), "LENGTH", "%d STEPS" % ln.length)
        elif number == 2:                                # RATE: the straight ones (TRIPLETS makes them triplets)
            one = knobgate.gate(("punch-rate",), delta, shift)
            if not one:
                return
            self._snapshot(("rate", self.lane))
            with self.seq.lock:
                ln.rate = sequencer.next_straight_rate(ln.rate, one)
            e.seq_changed()
            popup.show(self.T, punch.name(self.lane + 1), "RATE", self.rate_name(ln))
        elif number == SCALE_KNOB:                       # TIME SCALE: the whole punch pattern
            one = knobgate.gate(("punch-scale",), delta, shift)
            if not one:
                return
            self._snapshot(("scale",))
            with self.seq.lock:
                pat.scale = max(0, min(len(punch.SCALES) - 1, pat.scale + one))
            e.seq_changed()
            popup.show(self.T, "PUNCH PATTERN %d" % (self.st().current + 1), "TIME SCALE", "x%d" % punch.SCALES[pat.scale])

    def clear(self):
        """Shift + Delete: asks first; again (within a few seconds): every lane of the punch pattern cleared."""
        if time.monotonic() < self.confirm_until:
            punch.snapshot(self.seq)
            with self.seq.lock:
                for ln in self.pattern().lanes:
                    ln.steps.clear()
                    ln.lens.clear()
            self.confirm_until = 0.0
            self.T.engine.seq_changed()
            self.T.say("PUNCH PATTERN %d CLEARED" % (self.st().current + 1), 2)
        else:
            self.confirm_until = time.monotonic() + CONFIRM_SECONDS

    def confirming(self):
        return time.monotonic() < self.confirm_until

    def arrows(self, way):
        pages = max(1, (self.ln().length + 15) // 16)
        self.page = max(0, min(pages - 1, self.page + way))

    def leave(self):
        """Off the page: nothing left held."""
        e = self.T.engine
        if e is not None and self.pads_down:
            e.punch_live, e.punch_rec = None, False
        self.pads_down, self.held = [], None

    # ------------------------------------------------------------ lights
    def step_lights(self):
        ln = self.ln()
        now, trip = self.playing_step(), self.trip()
        colour = COLOUR[self.lane]
        tails = punch.covered(ln, trip)
        out = []
        for k in range(16):
            i = self.page * 16 + k
            if i >= ln.length or sequencer.dark(i, trip):
                out.append(0)
            elif i == self.held:
                out.append(120)
            elif i == now:                                 # the playhead: on steps dim, off steps glow (as the drum lanes)
                out.append(20 if i in ln.steps or i in tails else 60)
            else:
                out.append(colour if i in ln.steps or i in tails else sequencer.STEP_IDLE)
        return out

    def pad_lights(self, shift=False):
        out = [0] * 32
        st = self.st()
        if shift:                                        # Shift: the punch patterns (the current one bright)
            blink = int(time.monotonic() * 4) % 2
            for p in range(punch.PATTERNS):
                if p == st.current:
                    out[p] = 127
                elif p == st.queued:
                    out[p] = 127 if blink else 20
                else:
                    out[p] = 20 if not st.patterns[p].empty() else 0
            return out
        lit = self.now() | self.held_mask()
        pat = st.pattern
        for p in range(PADS):
            if p == self.lane or lit & punch.bit(p + 1):
                out[p] = 120
            elif self.held is not None:                   # a step held: the effects on there lit, the others dim
                out[p] = COLOUR[p] if self.held in pat.lanes[p].steps else 0
            else:
                out[p] = COLOUR[p]
        return out
