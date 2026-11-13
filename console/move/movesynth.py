"""The synth sequencer on the Move (the sequencer page of a synth). A synth's notes are chords on steps, kept by
pi-app/notes.py's NoteSequencer; this is the Move's buttons for it.

  step buttons    the pattern's steps, 16 at a time (<- / -> for more). Tap: put the notes on the step (or take
                  them off). Hold a step: the pads light the notes it has; tap pads to add or remove notes
                  while you hold. Hold a step and tap a later step: that is where the notes end (the length;
                  the steps they hold over light up). Hold, press <- / ->, tap: a length past the page.
  Shift + step    select steps (they blink); the pads are then their settings, knob 1 sets the picked one
  pads            the notes (the scale, up the pads; Up / Down on a sound page move the octave)
  two types, picked per track (knob 3):
    UNIFIED   one sequence: tap a step with pads held to put that chord there (nothing held: the last note)
    PER NOTE  tap a pad: its notes only are on the step buttons (it lights); tap it again for them all
  Record: the pads you play go onto the nearest step of the pattern while it plays (nothing to do with the tape)
  knobs (nothing held)  1 length  2 rate  3 type  4 the lit note's own length  5 key  6 scale
"""
import threading
import time

import knobgate
import popup
import notes as notes_mod
import sequencer
from sequencer import CHANCES, MAX_RATCHET

PAGE = 16
TYPES = ["UNIFIED", "PER NOTE"]
STEP_PADS = [("vel", "VELOCITY"), ("chance", "CHANCE"), ("ratchet", "MULTIPLY"), ("nudge", "NUDGE"),
             ("pulse", "PULSE"), ("hold", "HOLD"), ("jump", "JUMP"), ("rand", "RANDOM"), ("rup", "RAMP UP"),
             ("rdown", "RAMP DOWN")]
PATH_ONLY = ("pulse", "hold", "jump")             # these change the order the steps play in: PER NOTE only
COMPS = ("pulse", "hold", "jump", "rand", "rup", "rdown")
CKEYS = ("ratchet", "nudge") + COMPS               # the components knob 3 gives a chance
LANE_KNOBS = ["length", "rate", "type", "lane", "key", "scale"]
LABELS = {"length": "LENGTH", "rate": "RATE", "type": "TYPE", "lane": "NOTE LEN", "key": "KEY", "scale": "SCALE"}


def lane_free(ms):
    """True unless the pad of the lit note is being held (it is already sounding)."""
    return ms.lane not in getattr(ms, 'pads_down', {}).values()


class MoveSynth:
    def __init__(self, T):
        self.T = T
        self.page = 0
        self.down = {}             # steps held (plain): step -> when
        self.used = set()          # held steps a pad or a length gesture has used (letting go does nothing)
        self.selected = []         # steps picked with Shift
        self.sel = None            # the pad picked while steps are selected
        self.knob_page = 0         # while steps are selected (no pad picked): which sound page knobs 1-8 lock
        self.lane = None           # PER NOTE: the note whose steps the buttons show
        self.pads_down = {}        # pad -> note
        self.rec = {}              # pad -> (step, Note, frame) of a note being recorded live (its length follows the hold)
        self.last = None

    # ------------------------------------------------------------ what's shown

    def active(self):
        T = self.T
        return bool(T.seq_page and not T.fx_page and not getattr(T, "auto_page", False) and T.synth_shown() and T.engine and T.engine.drums)

    @property
    def seq(self):
        return self.T.engine.seq

    @property
    def d(self):
        return self.T.engine.drums

    @property
    def kind(self):
        return getattr(self.seq, "move_type", 0)

    def length(self):
        """Steps shown: the pattern's, or in PER NOTE with a note picked, that note's own length."""
        if self.kind and self.lane is not None:
            return self.seq.pattern.lane_length(self.lane)
        return self.seq.pattern.length

    def first(self):
        last = (max(1, self.length()) - 1) // PAGE
        self.page = max(0, min(self.page, last))
        return self.page * PAGE

    def pad_note(self, p):
        seq = self.seq
        try:
            base = seq.note_row(seq.shown_notes()[0])
            note = seq.row_note(base + p)
        except Exception:
            note = 48 + p
        return max(0, min(127, note + 12 * getattr(self.T, "octave", 0)))

    def held_steps(self):
        return sorted(self.down) or []

    def edit_steps(self):
        return self.selected

    def playing_step(self):
        e = self.T.engine
        if not e.playing:
            return None
        try:
            seq = self.seq
            if self.lane is not None and self.kind:
                n = self.seq.pattern.lane_length(self.lane)
                k = seq.raw_step(e._heard_frame(), e.frames_per_beat(), self.lane)
                return sequencer.phys(k % (sequencer.live_len(n, seq.trip) or 1), seq.trip)
            return seq.position(e._heard_frame(), e.frames_per_beat())[0]
        except Exception:
            return None

    def notes_at(self, i):
        return self.seq.pattern.at(i)

    # ------------------------------------------------------------ the step buttons

    def step(self, n, down, shift=False):
        i = self.first() + n - 1
        if sequencer.dark(i, sequencer.TRIPLETS):
            return                                              # (TRIPLETS: every 4th step is off and does nothing)
        if shift:
            if not down:
                return
            if i >= self.length():
                self.T.say("STEP %d IS PAST THE END (LENGTH %d: KNOB 1)" % (i + 1, self.length()), 2)
            elif i in self.selected:
                self.selected.remove(i)
            else:
                if not self.selected:                           # the knobs start on the sound page you were on
                    self.knob_page = getattr(self.T, "drum_tab", 0)
                self.selected.append(i)
                self.sel = None
            return
        if down:
            if self.selected:                                   # finished setting the selected steps
                self.selected, self.sel = [], None
                self.used.add(i)
                return
            if i >= self.length():
                self.T.say("STEP %d IS PAST THE END (LENGTH %d: KNOB 1)" % (i + 1, self.length()), 2)
                return
            before = [s for s in self.down if s < i]
            if before:                                          # a step is held, this one is where it ends
                a = max(before)
                size = i - a + 1
                self._set_length(a, size)
                self.used.add(a)
                self.used.add(i)
                self.down[i] = time.monotonic()
                return
            self.down[i] = time.monotonic()
            return
        if i not in self.down:
            return
        del self.down[i]
        if i in self.used:
            self.used.discard(i)
            return
        self._tap(i)

    def _targets(self, a):
        """The notes a held step's length applies to: the lit note (PER NOTE) or all of the step's."""
        if self.lane is not None and self.kind:
            return [self.lane] if self.lane in self.notes_at(a) else []
        return list(self.notes_at(a))

    def _set_length(self, a, size):
        seq = self.seq
        got = self._targets(a)
        if not got:
            self.T.say("STEP %d HAS NO NOTES" % (a + 1), 2)
            return
        with seq.lock:
            for n in got:
                nt = seq.note(a, n)
                if nt is not None:
                    nt.length = max(1, min(notes_mod.MAX_LENGTH, size))
        self.T.engine.seq_changed()
        self.T.say("STEP %d: LENGTH %d" % (a + 1, size), 2)

    def _tap(self, i):
        seq, e = self.seq, self.T.engine
        if self.kind and self.lane is not None:
            on = seq.toggle(i, self.lane)
            if on and not e.playing and lane_free(self):        # a short preview, only when stopped (playing, the step sounds itself)
                d, lane = e.drums, self.lane
                d.note_on(lane, 100)
                threading.Timer(0.25, d.note_off, (lane,)).start()
        elif self.notes_at(i):
            for n in list(self.notes_at(i)):
                seq.toggle(i, n)
        else:
            chord = sorted(self.pads_down.values()) or [self.last if self.last is not None else seq.shown_notes()[0]]
            for n in chord:
                seq.toggle(i, n)
        e.seq_changed()

    def arrows(self, way):
        if self.selected:                                   # steps selected: the sound pages for the knobs
            pages = self.sound_pages()
            if pages:
                self.knob_page = max(0, min(len(pages) - 1, self.knob_page + way))
                self.sel = None
                self.T.say("KNOBS: %s (%d/%d)" % (self.page_name(), self.knob_page + 1, len(pages)), 2)
            return
        last = (max(1, self.length()) - 1) // PAGE
        self.page = max(0, min(last, self.first() // PAGE + way))
        self.T.say("STEPS %d-%d OF %d" % (self.page * PAGE + 1, self.page * PAGE + PAGE, self.length()), 2)

    def plus_minus(self, way):
        if self.down or self.selected:
            return
        T = self.T                                              # + / - are the pads' octave (patterns: Shift + a pad)
        T.octave = max(-4, min(4, getattr(T, "octave", 0) + way))
        T.say("OCTAVE %s" % ("%+d" % T.octave if T.octave else "0"), 2)

    # ------------------------------------------------------------ the pads

    def pad(self, p, vel):
        """A pad. Returns True if it has been used as a setting (so it makes no sound)."""
        if vel:
            self.vel = vel                                      # (a recorded note gets the velocity you played)
        note = self.pad_note(p)
        if not vel:
            self.pads_down.pop(p, None)
            rec = self.rec.pop(p, None)
            if rec and self.T.engine.playing:                    # a recorded note lasts as long as you held the pad
                e, seq = self.T.engine, self.seq
                i, nt, frame = rec
                with seq.lock:
                    step_frames = e.frames_per_beat() / seq.pattern.steps_per_beat(note)
                    nt.length = max(1, min(notes_mod.MAX_LENGTH, round((e._heard_frame() - frame) / step_frames)))
                e.seq_changed()
            return False
        e, seq = self.T.engine, self.seq
        self.pads_down[p] = note
        self.last = note
        if self.selected:
            self._step_pad(p)
            return True
        if self.down:                                           # notes on the held step(s)
            with seq.lock:
                for i in list(self.down):
                    seq.toggle(i, note)
            self.used.update(self.down)
            e.seq_changed()
            return False
        if self.T.live_rec and e.playing:
            frame = e._heard_frame()
            i = seq.live_place(note, frame, e.frames_per_beat(), vel=getattr(self, "vel", 100))
            self.rec[p] = (i, seq.pattern.notes[i][note], frame)
            e.seq_changed()
            return False
        if self.kind:                                           # PER NOTE: this note's steps on the buttons
            self.lane = None if self.lane == note else note
            self.T.say("ALL NOTES" if self.lane is None else "NOTE %s" % notes_mod.note_name(note), 2)
        return False

    # ------------------------------------------------------------ settings of selected steps (the pads)

    def pad_items(self):
        items = list(STEP_PADS)
        d = self.d
        try:
            for _name, params in d.pages(0):
                for p in params:
                    if len(items) >= 32:
                        return items
                    if d.lockable(p) and all(p != k for k, _l in items):
                        items.append((p, d.label(p)))
        except Exception:
            pass
        return items

    def _notes_of(self, i):
        return list(self.notes_at(i).items())

    def engaged(self, key):
        i = self.selected[0] if self.selected else None
        if i is None:
            return False
        for _n, nt in self._notes_of(i):
            if key == "length":
                if nt.length != 1:
                    return True
            elif key == "vel":
                if nt.vel != notes_mod.DEFAULT_VELOCITY:
                    return True
            elif key == "chance":
                if nt.chance:
                    return True
            elif key == "ratchet":
                if nt.ratchet != 1:
                    return True
            elif key == "nudge":
                if nt.nudge:
                    return True
            elif key in COMPS:
                if key in nt.comp:
                    return True
            elif key in nt.locks:
                return True
        return False

    def item_value(self, key):
        i = self.selected[0]
        nts = self._notes_of(i)
        if not nts:
            return "NO NOTES"
        nt = nts[0][1]
        if key == "length":
            return "%d STEP%s" % (nt.length, "" if nt.length == 1 else "S")
        if key == "vel":
            return str(nt.vel)
        if key == "chance":
            return CHANCES[nt.chance]
        if key == "ratchet":
            return "x%d" % nt.ratchet
        if key == "nudge":
            return "%+d%%" % nt.nudge if nt.nudge else "ON THE BEAT"
        if key in COMPS:
            return sequencer.COMPONENTS[key][nt.comp[key]] if key in nt.comp else "OFF"
        d = self.d
        return d.value_text(key, nt.locks[key]) if key in nt.locks else d.value_text(key)

    def chance_text(self, key):
        """Knob 3's line for the picked pad: the component's chance, or None if the pad has none."""
        if key not in CKEYS:
            return None
        nts = self._notes_of(self.selected[0])
        if not nts or not self.engaged(key):
            return "SET KNOB 1 1ST"
        return CHANCES[nts[0][1].comp.get(key + "_c", 0)]

    def set_chance(self, delta, shift):
        """Knob 3 while steps are selected and a component pad picked: how likely it is to happen."""
        key, label = self.pad_items()[self.sel]
        if key not in CKEYS:
            return
        one = knobgate.gate(("synchance", key), delta, shift)
        if not one:
            return
        if not self.engaged(key):
            popup.show(self.T, self.which(), label + " CHANCE", "SET KNOB 1 FIRST")
            return
        seq = self.seq
        with seq.lock:
            for i in self.selected:
                for _n, nt in self._notes_of(i):
                    on = nt.ratchet != 1 if key == "ratchet" else nt.nudge != 0 if key == "nudge" else key in nt.comp
                    if on:
                        v = max(0, min(len(CHANCES) - 1, nt.comp.get(key + "_c", 0) + one))
                        if v:
                            nt.comp[key + "_c"] = v
                        else:
                            nt.comp.pop(key + "_c", None)
        self.T.engine.seq_changed()
        popup.show(self.T, self.which(), label + " CHANCE", self.chance_text(key))

    def which(self):
        return "STEP %d" % (self.selected[0] + 1) if len(self.selected) == 1 else "%d STEPS" % len(self.selected)

    def _step_pad(self, p):
        items = self.pad_items()
        if p >= len(items):
            return
        key, label = items[p]
        off = self.sel == p
        was = self.engaged(key)
        if off:
            seq = self.seq
            with seq.lock:
                for i in self.selected:
                    for _n, nt in self._notes_of(i):
                        if key == "length":
                            nt.length = 1
                        elif key == "vel":
                            nt.vel = notes_mod.DEFAULT_VELOCITY
                        elif key == "chance":
                            nt.chance = 0
                        elif key == "ratchet":
                            nt.ratchet = 1
                            nt.comp.pop("ratchet_c", None)
                        elif key == "nudge":
                            nt.nudge = 0
                            nt.comp.pop("nudge_c", None)
                        elif key in COMPS:
                            nt.comp.pop(key, None)
                            nt.comp.pop(key + "_c", None)
                        else:
                            nt.locks.pop(key, None)
            self.sel = None
            popup.show(self.T, self.which(), label, "OFF" if was else "")
            self.T.engine.seq_changed()
        else:
            if key in PATH_ONLY and not self.kind:
                self.T.say("%s: PER NOTE ONLY (KNOB 3 ON THE LANE PAGE)" % label, 3)
                return
            self.sel = p
            popup.show(self.T, self.which(), label, self.item_value(key), "KNOB 1")

    # ------------------------------------------------------------ knobs 1-8 lock the sound page on the selected steps
    def sound_pages(self):
        try:
            return list(self.d.pages(0))
        except Exception:                                  # noqa: BLE001
            return []

    def page_name(self):
        pages = self.sound_pages()
        return pages[min(self.knob_page, len(pages) - 1)][0] if pages else ""

    def lock_params(self):
        pages = self.sound_pages()
        if not pages:
            return []
        self.knob_page = max(0, min(len(pages) - 1, self.knob_page))
        return list(pages[self.knob_page][1])[:8]

    def lock_list(self):
        """[(label, value, locked, lockable)] for knobs 1-8 while steps are selected."""
        d = self.d
        nts = self._notes_of(self.selected[0]) if self.selected else []
        nt = nts[0][1] if nts else None
        out = []
        for p in self.lock_params():
            locked = nt is not None and p in nt.locks
            out.append((d.label(p), d.value_text(p, nt.locks[p]) if locked else d.value_text(p), locked,
                        bool(d.lockable(p))))
        return out

    def lock_choice(self, number):
        params = self.lock_params()
        return number <= len(params) and knobgate.is_choice(self.d, params[number - 1])

    def lock_knob(self, number, delta, shift):
        params = self.lock_params()
        if number > len(params):
            return
        key, d, seq = params[number - 1], self.d, self.seq
        label = d.label(key)
        if not d.lockable(key):
            popup.show(self.T, self.which(), label, "CAN'T BE LOCKED")
            return
        if not any(self._notes_of(i) for i in self.selected):
            popup.show(self.T, self.which(), label, "NO NOTES")
            return
        clicks = self.T.knob_clicks(number, delta, shift)
        if knobgate.is_choice(d, key):
            clicks = knobgate.gate(("synlock", key), delta, shift)
            if not clicks:
                return
        now = time.monotonic()
        if getattr(self, "_lock_gesture", None) != (number, tuple(self.selected)) or now - getattr(self, "_lock_at", 0) > 2:
            seq.snapshot()
        self._lock_gesture, self._lock_at = (number, tuple(self.selected)), now
        with seq.lock:
            for i in self.selected:
                for _n, nt in self._notes_of(i):
                    nt.locks[key] = d.stepped(key, nt.locks.get(key, d.get_param(key)), clicks)
        self.T.engine.seq_changed()
        popup.show(self.T, self.which(), label, self.item_value(key))

    def unlock_knob(self, number):
        params = self.lock_params()
        if self.sel is not None or number > len(params):
            return
        key, seq = params[number - 1], self.seq
        seq.snapshot()
        with seq.lock:
            for i in self.selected:
                for _n, nt in self._notes_of(i):
                    nt.locks.pop(key, None)
        self.T.engine.seq_changed()
        popup.show(self.T, self.which(), self.d.label(key), "OFF")

    def is_choice_knob(self, n):
        if self.selected:
            if self.sel is None:
                return self.lock_choice(n)
            if n == 2:
                return self.pad_items()[self.sel][0] in CKEYS
            if n != 1:
                return False
            key = self.pad_items()[self.sel][0]
            return key in ("chance", "ratchet", "nudge") + COMPS or (not isinstance(key, str) and knobgate.is_choice(self.d, key))
        if self.down:
            return False
        return n in (2, 3, 5, 6)

    def set_selected(self, delta, shift):
        key, label = self.pad_items()[self.sel]
        seq, e = self.seq, self.T.engine
        clicks = delta
        if key in ("chance", "ratchet", "nudge") + COMPS or (not isinstance(key, str) and knobgate.is_choice(self.d, key)):
            clicks = knobgate.gate(("synstep", key), delta, shift)
            if not clicks:
                return
        one = 1 if clicks > 0 else -1
        with seq.lock:
            for i in self.selected:
                for n, nt in self._notes_of(i):
                    if key == "length":
                        nt.length = max(1, min(notes_mod.MAX_LENGTH, nt.length + clicks))
                    elif key == "vel":
                        nt.vel = max(1, min(127, nt.vel + clicks))
                    elif key == "chance":
                        nt.chance = max(0, min(len(CHANCES) - 1, nt.chance + one))
                    elif key == "ratchet":
                        nt.ratchet = max(1, min(MAX_RATCHET, nt.ratchet + one))
                    elif key == "nudge":
                        nt.nudge = max(-50, min(50, nt.nudge + 10 * one))
                    elif key in COMPS:
                        if key in nt.comp:
                            nt.comp[key] = max(0, min(len(sequencer.COMPONENTS[key]) - 1, nt.comp[key] + one))
                        else:
                            nt.comp[key] = 0                                    # the first turn: its first value
                        if key in ("rand", "rup", "rdown"):                    # one pitch movement at a time
                            for other in ("rand", "rup", "rdown"):
                                if other != key:
                                    nt.comp.pop(other, None)
                                    nt.comp.pop(other + "_c", None)
                    else:
                        nt.locks[key] = self.d.stepped(key, nt.locks.get(key, self.d.get_param(key)), clicks)
        e.seq_changed()
        popup.show(self.T, self.which(), label, self.item_value(key))

    # ------------------------------------------------------------ the knobs

    def knob(self, number, delta, shift):
        seq, e = self.seq, self.T.engine
        if self.selected:
            if self.sel is not None:
                if number == 1:
                    self.set_selected(delta, shift)
                elif number == 2:
                    self.set_chance(delta, shift)
            else:
                self.lock_knob(number, delta, shift)
            return
        if self.down:
            if number == 1:
                a = sorted(self.down)[0]
                for n in self._targets(a):
                    seq.change_note(a, n, "length", delta)
                self.used.update(self.down)
                e.seq_changed()
            return
        if number > len(LANE_KNOBS):
            return
        what = LANE_KNOBS[number - 1]
        if what == "length" and self.kind and self.lane is not None:      # PER NOTE, a note picked: its own length
            v = seq.change_lane_length(self.lane, delta)
            self.T.len_flash = (time.monotonic() + 1.2, self.first(), v)
            self.T.say("NOTE %s LENGTH %d" % (notes_mod.note_name(self.lane), v), 2)
        elif what == "length" and self.kind:                # PER NOTE, no note picked: don't change them all
            self.T.say("TAP A NOTE'S PAD FIRST: EACH NOTE HAS ITS OWN LENGTH", 2)
        elif what == "length":
            v = seq.change_track("length", delta)
            self.T.len_flash = (time.monotonic() + 1.2, self.first(), v)      # the step lights show the length
            self.T.say("LENGTH %d" % v, 2)
        elif what == "rate":
            way = knobgate.gate(("synrate",), delta, shift)
            if way:
                if self.kind and self.lane is not None:                       # PER NOTE, a note picked: its own rate
                    r = seq.change_lane_rate(self.lane, way)
                    self.T.say("NOTE %s RATE %s" % (notes_mod.note_name(self.lane), notes_mod.RATES[r][0]), 2)
                else:
                    seq.change_track("rate", way)
                    self.T.say("RATE %s" % notes_mod.RATES[seq.pattern.rate][0], 2)
        elif what == "type":
            way = knobgate.gate(("syntype",), delta, shift)
            if way:
                seq.move_type = 1 if way > 0 else 0
                self.lane = None
                self.T.say("TYPE: %s" % TYPES[seq.move_type], 2)
        elif what == "lane":
            if self.lane is None:
                self.T.say("TAP A PAD (TYPE PER NOTE) FIRST", 2)
                return
            v = seq.change_lane_length(self.lane, delta)
            self.T.len_flash = (time.monotonic() + 1.2, self.first(), v)
            self.T.say("NOTE %s LENGTH %d" % (notes_mod.note_name(self.lane), v), 2)
        elif what == "key":
            way = knobgate.gate(("synkey",), delta, shift)
            if way:
                seq.set_scale(root=seq.root + way)
                self.T.say("KEY %s" % notes_mod.NAMES[seq.root], 2)
        elif what == "scale":
            way = knobgate.gate(("synscale",), delta, shift)
            if way:
                seq.set_scale(scale=seq.scale + way)
                self.T.say("SCALE %s" % notes_mod.SCALES[seq.scale][0], 2)
        e.seq_changed()

    def knob_list(self):
        seq = self.seq
        out = []
        for w in LANE_KNOBS:
            if w == "length":
                v = self.length()
            elif w == "rate":
                pt = seq.pattern
                v = notes_mod.RATES[pt.lane_rate.get(self.lane, pt.rate) if self.kind and self.lane is not None
                                    else pt.rate][0]
            elif w == "type":
                v = TYPES[self.kind][:5]
            elif w == "lane":
                v = seq.pattern.lane_length(self.lane) if self.lane is not None else "-"
            elif w == "key":
                v = notes_mod.NAMES[seq.root]
            else:
                v = notes_mod.SCALES[seq.scale][0][:5]
            out.append((LABELS[w], v, False))
        return out

    # ------------------------------------------------------------ lights

    def step_lights(self):
        seq = self.seq
        first, length = self.first(), self.length()
        at = self.playing_step()
        pat = seq.pattern
        held_len = {}
        if len(self.down) == 1:                                 # a held step: where its notes reach
            a = next(iter(self.down))
            for n in self._targets(a):
                nt = seq.note(a, n)
                if nt:
                    for s in range(a + 1, min(length, a + nt.length)):
                        held_len[s] = True
        out = []
        blink = int(time.monotonic() * 4) % 2
        for k in range(PAGE):
            i = first + k
            if i >= length or sequencer.dark(i, sequencer.TRIPLETS):
                v = 0
            elif i in self.selected:
                v = 127 if blink else 0
            elif i in self.down:
                v = 127
            elif i in held_len:
                v = 45
            else:
                if self.lane is not None and self.kind:
                    on = self.lane in pat.at(i)
                else:
                    on = bool(pat.at(i))
                v = 127 if on else sequencer.STEP_IDLE         # notes red, an empty step dim white (as the drums)
                if at is not None and i == at:
                    v = 20 if on else 60
            out.append(v)
        return out

    def pad_lights(self):
        seq = self.seq
        out = []
        if self.selected:
            items = self.pad_items()
            for p in range(32):
                if p >= len(items):
                    out.append(0)
                elif not self.engaged(items[p][0]):
                    out.append(20)
                elif p == self.sel:
                    out.append(127 if int(time.monotonic() * 4) % 2 else 0)
                else:
                    out.append(127)
            return out
        here = set()
        if self.down:
            for i in self.down:
                here.update(self.notes_at(i))
        used = set()
        if self.kind:                                           # PER NOTE: the notes that have steps, orange
            with seq.lock:
                used = {pitch for step in seq.pattern.notes.values() for pitch in step}
        for p in range(32):
            note = self.pad_note(p)
            if self.kind and self.lane is not None and note == self.lane:
                out.append(120)
            elif note in here:
                out.append(127)
            elif note in used:
                out.append(3)                                   # (orange in the Move's colours)
            elif note % 12 == seq.root:
                out.append(45)
            else:
                out.append(20)
        return out
