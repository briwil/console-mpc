"""The AUTOMATION page (left button 1 after the sequencer), and recording knob moves into a pattern.

Recording: while recording into the pattern (Record on a sound or sequencer page, playing), turning one of the
sound page's knobs puts its value on the step playing, every step, notes or not (autom.py): it plays back as
the steps go by, so a sweep over a held note is heard as a sweep. On the page it's the setting's name + REC.

The page: knob 1 goes through what has locks in this pattern (the step settings, VELOCITY, CHANCE, MULTIPLY...,
then the sound's), the step buttons light where it is set. Tap a lit step: it goes from that step. Tap an unlit
step that plays: it gets the setting (the value of the lit step before it). Hold a lit step: its value, and knob 1
changes it while you hold it. Delete + step: that step's one goes. Shift + Delete, twice: it goes from every step. Undo
puts any of it back. A drum machine: tap a drum's pad to see its own. < > (or the wheel): steps 17-32...
"""
import time

import autom
import knobgate
import popup
import sequencer

# the step settings, in the order the step-settings pads have them (moveseq.STEP_PADS)
STEP_KEYS = [("vel", "VELOCITY"), ("chance", "CHANCE"), ("ratchet", "MULTIPLY"), ("pulse", "PULSE"),
             ("hold", "HOLD"), ("jump", "JUMP"), ("rand", "RANDOM"), ("rup", "RAMP UP"), ("rdown", "RAMP DOWN"),
             ("nudge", "NUDGE")]
STEP_LABELS = dict(STEP_KEYS)
RATCHETS = [1, 2, 3, 4, 5, 6, 7, 8, 0]
COLOURS = [127, 3, 8, 11, 15, 22]       # the step lights per setting: red, orange, yellow, green, teal, purple
CONFIRM_SECONDS = 4.0
TAP_SECONDS = 0.35                      # a step let go sooner than this (knob 1 not turned): a tap


def record(T, param):
    """A sound knob was turned (its setting now changed): while recording into the pattern, the step playing
    gets it as a lock."""
    e = getattr(T, "engine", None)
    if not (e and getattr(T, "live_rec", False) and e.playing and e.drums):
        return
    d, seq = e.drums, e.seq
    if not d.lockable(param):
        return
    value = d.get_param(param)
    now = time.monotonic()
    if now - getattr(T, "_auto_rec_at", 0) > 2.0:      # one undo per knob gesture, not one per click
        seq.snapshot()
    T._auto_rec_at = now
    with seq.lock:
        pat = seq.pattern
        if T.synth_shown():
            length, rate = pat.length, pat.rate
        else:
            ln = seq.lane(T.seqp.lane)
            length, rate = ln.length, ln.rate
        autom.record(seq, pat, param, value, e._heard_frame(), e.frames_per_beat(), length, rate)
    e.seq_changed()


class Auto:
    def __init__(self, T):
        self.T = T
        self.pick = 0                 # which of the locked settings knob 1 is on
        self.held = None              # the step held down (its value shown, knob 1 changes it)
        self.page = 0                 # which 16 steps the buttons show
        self.confirm_until = 0.0      # Shift + Delete once: asking; again before this: clear it everywhere
        self._snapped = None          # (step, key) the held step's undo was kept for
        self._down_at = 0.0           # when the held step went down
        self._tap = False             # the held step could still be a tap (lit when pressed, knob 1 not turned)

    # ------------------------------------------------------------ what's shown
    def active(self):
        T = self.T
        return bool(T.seq_page and not T.fx_page and getattr(T, "auto_page", False) is True and T.engine and T.engine.drums)

    @property
    def seq(self):
        return self.T.engine.seq

    def synth(self):
        return self.T.synth_shown()

    @staticmethod
    def rec(key):
        return isinstance(key, tuple) and key[0] == "rec"

    def rec_lane(self, key):
        return autom.lanes(self.seq.pattern).get(key[1])

    def length(self, key=None):
        seq = self.seq
        if self.rec(key):
            ln = self.rec_lane(key)
            return ln.length if ln else 16
        return seq.pattern.length if self.synth() else seq.lane(self.T.seqp.lane).length

    def units(self, i):
        """What a step holds: a drum's step, or a synth's notes that start there."""
        seq = self.seq
        if self.synth():
            return list(seq.pattern.at(i).values())
        return [seq.step(self.T.seqp.lane, i)]

    @staticmethod
    def has(u, key):
        if key == "vel":
            return u.vel != sequencer.DEFAULT_VELOCITY
        if key == "chance":
            return u.chance != 0
        if key == "ratchet":
            return u.ratchet != 1
        if key == "nudge" and hasattr(u, "nudge") and not isinstance(getattr(u, "nudge"), dict):
            return u.nudge != 0 or "nudge" in u.comp
        if isinstance(key, str):
            return key in u.comp
        return key in u.locks

    def keys(self):
        """The settings with something set on some step, step settings first, then the sound's by number."""
        found = set()
        with self.seq.lock:
            for i in range(self.length()):
                for u in self.units(i):
                    for k, _l in STEP_KEYS:
                        if self.has(u, k):
                            found.add(k)
                    found.update(u.locks)
        steps = [k for k, _l in STEP_KEYS if k in found]
        recs = [("rec", p) for p in sorted(autom.lanes(self.seq.pattern)) if autom.lanes(self.seq.pattern)[p].steps]
        return steps + sorted(k for k in found if not isinstance(k, str)) + recs

    def key(self):
        ks = self.keys()
        if not ks:
            return None
        self.pick = max(0, min(len(ks) - 1, self.pick))
        return ks[self.pick]

    def label(self, key):
        if self.rec(key):
            return self.T.engine.drums.label(key[1]) + " REC"
        if isinstance(key, str):
            return STEP_LABELS.get(key, key.upper())
        return self.T.engine.drums.label(key)

    def steps_with(self, key):
        if key is None:
            return set()
        if self.rec(key):
            ln = self.rec_lane(key)
            return {i for i in ln.steps if i < ln.length} if ln else set()
        with self.seq.lock:
            return {i for i in range(self.length()) if any(self.has(u, key) for u in self.units(i))}

    def value_text(self, i, key):
        if self.rec(key):
            ln = self.rec_lane(key)
            return self.T.engine.drums.value_text(key[1], ln.steps[i]) if ln and i in ln.steps else "-"
        us = [u for u in self.units(i) if self.has(u, key)]
        if not us:
            return "-"
        u = us[0]
        if key == "vel":
            return "RND" if u.vel == 0 else str(u.vel)
        if key == "chance":
            return sequencer.CHANCES[u.chance]
        if key == "ratchet":
            return "RND" if u.ratchet == 0 else "x%d" % u.ratchet
        if key == "nudge" and "nudge" not in u.comp and hasattr(u, "nudge"):
            return "%+d%%" % u.nudge
        if isinstance(key, str):
            return sequencer.COMPONENTS[key][u.comp[key]]
        return self.T.engine.drums.value_text(key, u.locks[key])

    # ------------------------------------------------------------ changing it
    def _keep(self, i, key):
        if self._snapped != (i, key):
            self.seq.snapshot()
            self._snapped = (i, key)

    def change(self, i, key, clicks, one):
        d = self.T.engine.drums
        self._keep(i, key)
        if self.rec(key):
            with self.seq.lock:
                ln = self.rec_lane(key)
                if ln and i in ln.steps:
                    v = ln.steps[i]
                    ln.steps[i] = int(d.stepped(key[1], v, clicks)) if hasattr(d, "stepped") else max(0, min(127, v + clicks))
            self.T.engine.seq_changed()
            return
        with self.seq.lock:
            for u in self.units(i):
                if not self.has(u, key):
                    continue
                if key == "vel":
                    u.vel = max(0, min(127, (u.vel or 0) + clicks))
                elif key == "chance":
                    u.chance = max(0, min(len(sequencer.CHANCES) - 1, u.chance + one))
                elif key == "ratchet":
                    at = RATCHETS.index(u.ratchet) if u.ratchet in RATCHETS else 0
                    u.ratchet = RATCHETS[max(0, min(len(RATCHETS) - 1, at + one))]
                elif key == "nudge" and "nudge" not in u.comp and hasattr(u, "nudge"):
                    u.nudge = max(-50, min(50, u.nudge + 10 * one)) or (10 * one)
                elif isinstance(key, str):
                    u.comp[key] = max(0, min(len(sequencer.COMPONENTS[key]) - 1, u.comp[key] + one))
                else:
                    v = u.locks[key]
                    u.locks[key] = int(d.stepped(key, v, clicks)) if hasattr(d, "stepped") else \
                        max(0, min(127, v + clicks))
        self.T.engine.seq_changed()

    def _reset(self, u, key):
        if key == "vel":
            u.vel = sequencer.DEFAULT_VELOCITY
        elif key == "chance":
            u.chance = 0
        elif key == "ratchet":
            u.ratchet = 1
        elif isinstance(key, str):
            u.comp.pop(key, None)
            if key == "nudge" and hasattr(u, "nudge") and not isinstance(u.nudge, dict):
                u.nudge = 0
        else:
            u.locks.pop(key, None)

    def remove(self, i, key):
        self.seq.snapshot()
        if self.rec(key):
            with self.seq.lock:
                ln = self.rec_lane(key)
                if ln:
                    ln.steps.pop(i, None)
            self._snapped = None
            self.T.engine.seq_changed()
            return
        with self.seq.lock:
            for u in self.units(i):
                self._reset(u, key)
        self._snapped = None
        self.T.engine.seq_changed()

    @staticmethod
    def _copy(src, dst, key):
        if key in ("vel", "chance", "ratchet"):
            setattr(dst, key, getattr(src, key))
        elif key == "nudge" and "nudge" not in src.comp and hasattr(src, "nudge"):
            dst.nudge = src.nudge
        elif isinstance(key, str):
            dst.comp[key] = src.comp[key]
        else:
            dst.locks[key] = src.locks[key]

    def add(self, i, key):
        """Put the setting on step i, with the value of the lit step before it (round from the end).
        False when nothing plays on the step (a lock only counts where a note plays)."""
        lit = sorted(self.steps_with(key))
        if not lit:
            return False
        before = [k for k in lit if k < i]
        src_i = before[-1] if before else lit[-1]
        if self.rec(key):                                 # recorded: any step can have it
            self.seq.snapshot()
            with self.seq.lock:
                ln = self.rec_lane(key)
                ln.steps[i] = ln.steps[src_i]
            self._snapped = (i, key)
            self.T.engine.seq_changed()
            return True
        with self.seq.lock:
            ok = any(self.has(u, key) for u in self.units(src_i)) and \
                any(self.synth() or getattr(u, "on", False) for u in self.units(i))
        if not ok:
            return False
        self.seq.snapshot()
        with self.seq.lock:
            src = next(u for u in self.units(src_i) if self.has(u, key))
            for u in [u for u in self.units(i) if self.synth() or getattr(u, "on", False)]:
                self._copy(src, u, key)
        self._snapped = (i, key)
        self.T.engine.seq_changed()
        return True

    def clear_key(self, key):
        self.seq.snapshot()
        if self.rec(key):
            with self.seq.lock:
                autom.lanes(self.seq.pattern).pop(key[1], None)
            self._snapped = None
            self.T.engine.seq_changed()
            return
        with self.seq.lock:
            for i in range(self.length()):
                for u in self.units(i):
                    self._reset(u, key)
        self._snapped = None
        self.T.engine.seq_changed()

    # ------------------------------------------------------------ controls
    def knob(self, number, delta, shift):
        if number == 2:
            self.set_length(delta, shift)
            return
        if number != 1:
            return
        key = self.key()
        if self.held is not None and key is not None and self.held in self.steps_with(key):
            d = self.T.engine.drums
            clicks = self.T.knob_clicks(1, delta, shift)
            if isinstance(key, str) and key != "vel":
                one = knobgate.gate(("comp", key), delta, shift)
                if not one:
                    return
                delta = one
            elif not isinstance(key, str) and knobgate.is_choice(d, key):
                clicks = knobgate.gate(("step", key), delta, shift)
                if not clicks:
                    return
            self._tap = False
            self.change(self.held, key, clicks, 1 if delta > 0 else -1)
            popup.show(self.T, "STEP %d" % (self.held + 1), self.label(key), self.value_text(self.held, key))
            return
        way = knobgate.gate(("auto-pick",), delta, shift)          # (a list: a few clicks each)
        if not way:
            return
        n = len(self.keys())
        if n:
            self.pick = (self.pick + (1 if way > 0 else -1)) % n
        self.confirm_until = 0.0

    def set_length(self, delta, shift):
        """Knob 2: a recorded setting's own length (its steps are kept when it's shortened)."""
        key = self.key()
        if not self.rec(key):
            if key is not None:
                self.T.say("KNOB 2 SETS A RECORDED SETTING'S LENGTH", 2)
            return
        one = knobgate.gate(("auto-length",), delta, shift, 2)
        if not one:
            return
        now = time.monotonic()
        if now - getattr(self, "_len_at", 0) > 2.0:           # one undo per turn of the knob
            self.seq.snapshot()
        self._len_at = now
        with self.seq.lock:
            ln = self.rec_lane(key)
            if not ln:
                return
            ln.length = max(1, min(sequencer.MAX_STEPS, ln.length + one))
            n = ln.length
        self.held = None
        self.page = max(0, min(self.page, (n - 1) // 16))
        self.T.engine.seq_changed()
        popup.show(self.T, self.label(key)[:12], "LENGTH", "%d STEPS" % n)

    def step(self, n, down, deleting):
        i = self.page * 16 + n - 1
        if not down:
            if self.held == i:
                key = self.key()
                if self._tap and key is not None and time.monotonic() - self._down_at < TAP_SECONDS \
                        and i in self.steps_with(key):
                    self.remove(i, key)                   # a tap on a lit step: it goes
                    popup.show(self.T, "STEP %d" % (i + 1), self.label(key), "OFF")
                self.held = None
                self._snapped = None
                self._tap = False
            return
        key = self.key()
        if key is None or i >= self.length(key):
            return
        if deleting:
            if i in self.steps_with(key):
                self.remove(i, key)
                self.T.say("STEP %d: %s TAKEN OFF" % (i + 1, self.label(key)), 2)
            return
        self._down_at = time.monotonic()
        if i in self.steps_with(key):
            self.held, self._tap = i, True
            popup.show(self.T, "STEP %d" % (i + 1), self.label(key), self.value_text(i, key))
        elif self.add(i, key):                            # an unlit step: it gets the setting (hold it: knob 1)
            self.held, self._tap = i, False
            popup.show(self.T, "STEP %d" % (i + 1), self.label(key), self.value_text(i, key), "ADDED")
        else:
            self.T.say("STEP %d: NO NOTE THERE" % (i + 1), 2)

    def clear(self):
        """Shift + Delete: asks first; again (within a few seconds): this setting off every step."""
        key = self.key()
        if key is None:
            return
        if time.monotonic() < self.confirm_until:
            n = len(self.steps_with(key))
            self.clear_key(key)
            self.confirm_until = 0.0
            self.pick = 0
            self.T.say("%s TAKEN OFF %d STEP%s" % (self.label(key), n, "" if n == 1 else "S"), 2)
        else:
            self.confirm_until = time.monotonic() + CONFIRM_SECONDS

    def confirming(self):
        return time.monotonic() < self.confirm_until

    def arrows(self, way):
        pages = max(1, (self.length(self.key()) + 15) // 16)
        self.page = max(0, min(pages - 1, self.page + way))

    def lane_changed(self):
        self.pick, self.held, self.page, self.confirm_until = 0, None, 0, 0.0

    # ------------------------------------------------------------ lights
    def playing_step(self):
        e = self.T.engine
        if not e.playing:
            return None
        try:
            key = self.key()
            if self.rec(key):
                ln = self.rec_lane(key)
                return autom.position(self.seq, ln, e._heard_frame(), e.frames_per_beat())[1] if ln else None
            at = self.seq.position(e._heard_frame(), e.frames_per_beat())
            return at[0] if self.synth() else at[self.T.seqp.lane]
        except Exception:                                # noqa: BLE001
            return None

    def colour(self):
        """Each setting knob 1 goes to has its own colour, so you can see you've switched."""
        return COLOURS[self.pick % len(COLOURS)]

    def step_lights(self):
        key = self.key()
        on = self.steps_with(key)
        length, now = self.length(key), self.playing_step()
        colour = self.colour()
        out = []
        for k in range(16):
            i = self.page * 16 + k
            if i >= length or sequencer.dark(i, sequencer.TRIPLETS):
                out.append(0)
            elif i == self.held:
                out.append(120)                                   # held: white
            elif i == now:
                out.append(120 if i in on else 118)               # the playhead passing
            else:
                out.append(colour if i in on else 0)              # set: this setting's colour
        return out

    def pad_lights(self):
        """A drum machine: the drums that have automation lit (the one shown white)."""
        out = [0] * 32
        if self.synth():
            return out
        e, seq = self.T.engine, self.seq
        d = e.drums
        with seq.lock:
            for ln in range(min(16, d.lanes)):
                busy = any(st.locks or st.vel != sequencer.DEFAULT_VELOCITY or st.chance or st.ratchet != 1 or st.comp
                           for st in seq.lane(ln).steps[:seq.lane(ln).length])
                r, c = divmod(ln, 4)
                p = r * 8 + c
                out[p] = 120 if ln == self.T.seqp.lane else (127 if busy else 20)
        return out
