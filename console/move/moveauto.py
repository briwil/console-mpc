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
        self.mode = "list"            # list (the settings with steps) -> pick (choose a setting) / edit (its steps, in a pop-up)
        self.edit_key = None          # the setting the pop-up is on
        self.extra = []               # settings chosen this visit that have no steps yet (they go when you leave)
        self.row = 0                  # the list's cursor
        self.items, self.prow = [], 0 # the picker: [(key, label)], its cursor
        self.selected = []            # steps picked with Shift (the white boxes): knob 1 sets them all
        self.cur = None               # the white box the wheel moves over the steps
        self._on = False
        self._orig = {}               # live recording: the setting's value before you turned it (it goes back to it when recording ends)

    # ------------------------------------------------------------ what's shown
    def active(self):
        T = self.T
        on = bool(T.seq_page and not T.fx_page and getattr(T, "auto_page", False) is True and T.engine and T.engine.drums)
        if self._on and not on:
            self._left()                                      # (left the page: it opens on the list again)
        self._on = on
        return on

    def _left(self):
        self.restore()
        self.mode, self.edit_key, self.extra, self.row = "list", None, [], 0
        self.held = self.cur = None
        self.selected, self.page, self.confirm_until, self._snapped = [], 0, 0.0, None

    # ------------------------------------------------------------ the list and the picker
    def rows(self):
        ks = self.keys()
        return ks + [k for k in self.extra if k not in ks]

    def shown(self):
        """List rows on screen: 8 to start, one more empty row once they are all used."""
        return max(8, len(self.rows()) + 1)

    def row_key(self):
        rs = self.rows()
        return rs[self.row] if 0 <= self.row < len(rs) else None

    def build_items(self):
        d = self.T.engine.drums
        items = [(k, l) for k, l in STEP_KEYS]
        try:
            voice = 0
            if not self.synth():
                lane = self.T.seqp.lane
                voice = d.lane_voice[lane] if lane < len(getattr(d, "lane_voice", [])) else 0
            seen = set()
            for _name, params in d.pages(voice):
                for p in params:
                    if p not in seen and d.lockable(p):
                        seen.add(p)
                        items.append((("rec", p), d.label(p)))      # (a sound setting: a lane of its own, any step, not only where a note starts)
        except Exception:                                      # noqa: BLE001
            pass
        self.items, self.prow = items, 0

    def open_row(self):
        k = self.row_key()
        if k is None:
            self.build_items()
            self.mode = "pick"
            return
        self.mode, self.edit_key, self.page = "edit", k, 0
        self.held = self.cur = None
        self.selected = []

    def pick_push(self):
        if not self.items:
            self.mode = "list"
            return
        k = self.items[max(0, min(len(self.items) - 1, self.prow))][0]
        if k not in self.rows():
            self.extra.append(k)
        self.row = self.rows().index(k)
        self.mode, self.edit_key, self.page = "edit", k, 0
        self.held = self.cur = None
        self.selected = []

    def back(self):
        """Back from the pop-up or the picker: to the list. False on the list (the page's own Back)."""
        if self.mode == "list":
            return False
        self.restore()
        k = self.edit_key
        if self.mode == "edit" and k in self.extra and not self.steps_with(k):
            self.extra.remove(k)                               # (nothing set on it: it is not kept)
        self.mode, self.edit_key = "list", None
        self.held = self.cur = None
        self.selected, self._snapped = [], None
        self.row = max(0, min(self.row, self.shown() - 1))
        return True

    def wheel(self, delta, shift):
        """The big wheel: down the list / the picker; in the pop-up the white box along the steps."""
        if self.mode == "list":
            way = knobgate.gate(("auto-pick",), delta, shift, 1)
            if way:
                self.row = max(0, min(self.shown() - 1, self.row + (1 if way > 0 else -1)))
                self.confirm_until = 0.0
        elif self.mode == "pick":
            way = knobgate.gate(("auto-pick",), delta, shift, 1)
            if way and self.items:
                self.prow = (self.prow + (1 if way > 0 else -1)) % len(self.items)
        else:
            way = knobgate.gate(("auto-cur",), delta, shift, 1)
            if not way:
                return
            n = self.length(self.edit_key)
            at = self.cur if self.cur is not None else self.page * 16 - (1 if way > 0 else 0)
            self.cur = max(0, min(n - 1, at + (1 if way > 0 else -1)))
            self.page = self.cur // 16

    def push(self):
        """Push the wheel: open the row / choose the setting; in the pop-up the white box's step goes on or off (or the picked steps are done)."""
        if self.mode == "list":
            self.open_row()
        elif self.mode == "pick":
            self.pick_push()
        else:
            key = self.edit_key
            if self.selected:
                self.selected = []
                return
            i = self.cur
            if i is None or i >= self.length(key):
                return
            if i in self.steps_with(key):
                self.remove(i, key)
                popup.show(self.T, "STEP %d" % (i + 1), self.label(key), "OFF")
            elif self.add(i, key):
                popup.show(self.T, "STEP %d" % (i + 1), self.label(key), self.value_text(i, key), "ADDED")
            else:
                self.T.say("STEP %d: %s NEEDS A NOTE ON THE STEP" % (i + 1, self.label(key)[:14]), 3)

    def targets(self):
        """The steps knob 1 changes: the picked ones, else the one held, else the white box's."""
        key = self.edit_key
        on = self.steps_with(key)
        if self.selected:
            return sorted(i for i in self.selected if i < self.length(key))
        if self.held is not None and self.held in on:
            return [self.held]
        if self.cur is not None and self.cur in on:
            return [self.cur]
        return []

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
            if ln:
                return ln.length
            return max(16, seq.pattern.length if self.synth() else seq.lane(self.T.seqp.lane).length)      # (a new one: at least 16 steps)
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
        return self.edit_key if self.mode == "edit" else None

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

    def change(self, i, key, clicks, one, keep=True):
        d = self.T.engine.drums
        if keep:
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
            return self._first(i, key)                    # nothing set yet: this step is the first, with a starting value
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

    def _first(self, i, key):
        """The first step of a setting (just chosen from the picker): its starting value."""
        d = self.T.engine.drums
        if self.rec(key):                                      # a lane: any step, the sound's value as it is now
            self.seq.snapshot()
            with self.seq.lock:
                pat = self.seq.pattern
                a = autom.lanes(pat)
                ln = a.get(key[1])
                if ln is None:
                    if self.synth():
                        length, rate = pat.length, pat.rate
                    else:
                        lane = self.seq.lane(self.T.seqp.lane)
                        length, rate = lane.length, lane.rate
                    ln = a[key[1]] = autom.Lane(max(16, length), rate)
                if i < ln.length:
                    ln.steps[i] = int(d.get_param(key[1]))
            self._snapped = (i, key)
            self.T.engine.seq_changed()
            return True
        with self.seq.lock:
            us = [u for u in self.units(i) if self.synth() or getattr(u, "on", False)]
        if not us:
            return False
        self.seq.snapshot()
        with self.seq.lock:
            for u in us:
                if key == "vel":
                    u.vel = max(1, sequencer.DEFAULT_VELOCITY - 10)
                elif key == "chance":
                    u.chance = 1
                elif key == "ratchet":
                    u.ratchet = 2
                elif key == "nudge" and "nudge" not in u.comp and hasattr(u, "nudge") and not isinstance(u.nudge, dict):
                    u.nudge = 10
                elif isinstance(key, str):
                    u.comp[key] = 0
                else:
                    u.locks[key] = d.get_param(key)
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
        if self.mode != "edit":
            if number == 1:
                self.wheel(delta, shift)                          # (knob 1 scrolls the list too)
            return
        if number == 2:
            self.set_length(delta, shift)
            return
        if number != 1:
            return
        key = self.key()
        d = self.T.engine.drums
        if self.rec(key) and not self.selected and self.held is None and self.live_ready():
            self.live_knob(key, delta, shift)                     # recording and playing: the knob is played live and laid on the steps
            return
        on = self.steps_with(key)
        for i in self.selected:                                    # picked steps that have nothing yet get the setting first
            if i not in on and i < self.length(key):
                self.add(i, key)
        targets = self.targets()
        if not targets:
            self.T.say("PICK A STEP: A STEP BUTTON, SHIFT + STEPS, OR THE WHEEL", 2)
            return
        clicks = self.T.knob_clicks(1, delta, shift)
        if isinstance(key, str) and key != "vel":
            one = knobgate.gate(("comp", key), delta, shift)
            if not one:
                return
            delta = one
        elif not isinstance(key, str) and not self.rec(key) and knobgate.is_choice(d, key):
            clicks = knobgate.gate(("step", key), delta, shift)
            if not clicks:
                return
        self._tap = False
        self._keep(tuple(targets), key)                           # one undo for all the steps
        for i in targets:
            self.change(i, key, clicks, 1 if delta > 0 else -1, keep=False)
        i = targets[0]
        popup.show(self.T, "STEP %d" % (i + 1) if len(targets) == 1 else "%d STEPS" % len(targets), self.label(key),
                   self.value_text(i, key))

    def live_ready(self):
        T, e = self.T, self.T.engine
        return bool(getattr(T, "live_rec", False) and e and e.playing and e.drums)

    def live_knob(self, key, delta, shift):
        """Recording into the pattern, playing: knob 1 turns the setting (you hear it) and puts its value on the step playing."""
        T, d, param = self.T, self.T.engine.drums, key[1]
        if not d.lockable(param):
            return
        v = d.get_param(param)
        if param not in self._orig:
            self._orig[param] = v                                 # (what it goes back to)
        clicks = T.knob_clicks(1, delta, shift)
        if knobgate.is_choice(d, param):
            clicks = knobgate.gate(("step", param), delta, shift)
            if not clicks:
                return
        nv = int(d.stepped(param, v, clicks)) if hasattr(d, "stepped") else max(0, min(127, v + clicks))
        d.set_param(param, nv)
        record(T, param)
        popup.show(T, self.label(key), "RECORDING", d.value_text(param))

    def restore(self):
        """Recording ended: the settings turned live go back to what they were."""
        if not self._orig:
            return
        d = self.T.engine.drums if self.T.engine else None
        for param, v in list(self._orig.items()):
            try:
                if d is not None:
                    d.set_param(param, v)
            except Exception:                                      # noqa: BLE001
                pass
        self._orig.clear()

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

    def step(self, n, down, deleting, shift=False):
        if self.mode != "edit":
            return
        i = self.page * 16 + n - 1
        if shift and down:                                         # Shift + a step: a white box on it (or off); knob 1 sets them all
            if i < self.length(self.key()):
                self.selected = [j for j in self.selected if j != i] if i in self.selected else self.selected + [i]
                self.cur = i
                self.T.say("%d STEP%s PICKED" % (len(self.selected), "" if len(self.selected) == 1 else "S") if self.selected else "NO STEPS PICKED", 2)
            return
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
        self.cur = i
        if i in self.steps_with(key):
            self.held, self._tap = i, True
            popup.show(self.T, "STEP %d" % (i + 1), self.label(key), self.value_text(i, key))
        elif self.add(i, key):                            # an unlit step: it gets the setting (hold it: knob 1)
            self.held, self._tap = i, False
            popup.show(self.T, "STEP %d" % (i + 1), self.label(key), self.value_text(i, key), "ADDED")
        else:
            self.T.say("STEP %d: %s NEEDS A NOTE ON THE STEP" % (i + 1, self.label(key)[:14]), 3)

    def clear(self):
        """Shift + Delete: asks first; again (within a few seconds): this setting off every step."""
        key = self.key() or (self.row_key() if self.mode == "list" else None)
        if key is None:
            return
        if time.monotonic() < self.confirm_until:
            n = len(self.steps_with(key))
            self.clear_key(key)
            if key in self.extra:
                self.extra.remove(key)
            self.confirm_until = 0.0
            self.mode, self.edit_key, self.selected, self.cur = "list", None, [], None
            self.T.say("%s TAKEN OFF %d STEP%s" % (self.label(key), n, "" if n == 1 else "S"), 2)
        else:
            self.confirm_until = time.monotonic() + CONFIRM_SECONDS

    def confirming(self):
        return time.monotonic() < self.confirm_until

    def arrows(self, way):
        if self.mode != "edit":
            return
        pages = max(1, (self.length(self.key()) + 15) // 16)
        self.page = max(0, min(pages - 1, self.page + way))

    def lane_changed(self):
        self._left()                                               # (another drum: its own list)

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
        return COLOURS[self.row % len(COLOURS)]

    def step_lights(self):
        key = self.key()
        if key is None:
            return [0] * 16
        on = self.steps_with(key)
        length, now = self.length(key), self.playing_step()
        colour = self.colour()
        out = []
        for k in range(16):
            i = self.page * 16 + k
            if i >= length or sequencer.dark(i, sequencer.TRIPLETS):
                out.append(0)
            elif i == self.held or i in self.selected or i == self.cur:
                out.append(120)                                   # held, picked or under the white box: white
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
