"""The drum sequencer the Move's way: the 16 step buttons are the steps, the knobs set the lane, and the
screen shows what the knobs do.

  pads (left 4 x 4)      pick the drum (and play it)
  step buttons 1-16      tap: the step on / off
  Shift + tap steps      select them (they blink). Knobs 1-8 are then the drum's sound page (as on its sound
                         page; < > or the wheel: its other pages): turning one locks that setting on the steps
                         (Shift + touch the knob: the lock off). The pads are their settings (OP-XY style), bottom
                         left first: VELOCITY, CHANCE, MULTIPLY, PULSE, HOLD, JUMP, RANDOM, RAMP UP, RAMP DOWN, NUDGE,
                         then the drum's own sound settings. Tap a pad: it's on, knob 1 sets it; the same pad again:
                         off (back to normal, and the knobs back to the sound page). Lit pads: what the steps have.
                         Tap any step: done
  <- / ->                the lane's steps 1-16, 17-32, 33-48, 49-64
  knobs                  1 LENGTH, 2 RATE (length scale), 3 EUCLID, 4 SHIFT
  + / -                  the pattern
It works through the Pi app's own SeqPage (T.seqp), so the pattern, undo and saving are the same.
"""
import time

import knobgate
import popup
import seqpage
import sequencer

PAGE = 16                                          # step buttons
LANE_KNOBS = ["length", "rate", "hits", "rotate"]  # knobs 1-4, no step held
LABELS = dict(seqpage.STEP_LABELS, rate="RATE", hits="EUCLID", rotate="SHIFT")
# the pads while a step is held, bottom left first: (key, label). Then the drum's sound settings
STEP_PADS = [("vel", "VELOCITY"), ("chance", "CHANCE"), ("ratchet", "MULTIPLY"), ("pulse", "PULSE"),
             ("hold", "HOLD"), ("jump", "JUMP"), ("rand", "RANDOM"), ("rup", "RAMP UP"), ("rdown", "RAMP DOWN"),
             ("nudge", "NUDGE")]
CKEYS = ("ratchet", "pulse", "hold", "jump", "rand", "rup", "rdown", "nudge")   # the components knob 3 gives a chance
RATCHETS = [1, 2, 3, 4, 5, 6, 7, 8, 0]            # MULTIPLY's values in knob order (0: random)
SEMI = 2                                          # knob clicks of a drum's pitch setting per semitone (a guess)
PITCH_WORDS = ("TUNE", "PITCH", "COARSE", "FREQ", "NOTE")


class MoveSeq:
    def __init__(self, T):
        self.T = T
        self.page = {}             # lane -> which 16 steps the buttons show (0-3)
        self.selected = []         # the steps picked with Shift (their settings are on the pads)
        self.knob_page = 0         # while steps are selected: which of the drum's sound pages knobs 1-8 are
        self.sel = None            # while a step is held: the pad picked (its setting is on knob 1)
        self.down = set()
        self.chrom = {}                                      # chromatic pads held: pad -> semitones (a step tapped meanwhile gets it)          # step buttons physically held (a right-half pad then puts its pitch on them)
        self._pitch = {}           # voice -> its pitch setting (or None)
        sequencer.PITCH = self.pitch_locks

    # ------------------------------------------------------------ pitch (RANDOM / RAMPS and the right-hand pads)

    def pitch_param(self, voice, d=None, mid=None):
        e = self.T.engine
        if d is None:
            d, mid = e.drums, (e.slots[e.slot] if e.slot is not None else None)
        key = (mid, voice)                                   # (per instrument: they differ)
        if key not in self._pitch:
            found = None
            for _name, params in d.pages(voice):
                for p in params:
                    if any(w in d.label(p).upper() for w in PITCH_WORDS):
                        found = p
                        break
                if found is not None:
                    break
            self._pitch[key] = found
        return self._pitch[key]

    def pitch_locks(self, lane, locks, semis, seq=None):
        """locks, with the lane's drum moved by some semitones (its pitch setting locked). seq: the
        sequence playing it (another slot's instrument, not the one shown)."""
        e = self.T.engine
        d, mid = e.drums, (e.slots[e.slot] if e.slot is not None else None)
        if seq is not None:
            mid = next((k for k, v in list(e.seqs.items()) if v is seq), None)
            d = e.drums.get(mid) if mid else None
            if d is None:
                return locks
        lv = d.lane_voice
        p = self.pitch_param(lv[min(len(lv) - 1, lane)], d, mid)
        if p is None or not semis:
            return locks
        out = dict(locks)
        out[p] = d.stepped(p, locks.get(p, d.get_param(p)), semis * SEMI)
        return out

    # ------------------------------------------------------------ what's shown

    @property
    def sp(self):
        return self.T.seqp

    @property
    def seq(self):
        return self.T.engine.seq

    def active(self):
        T = self.T
        return bool(T.seq_page and not T.fx_page and not getattr(T, "auto_page", False) and not T.synth_shown() and T.engine and T.engine.drums)

    def first(self):
        lane = self.sp.lane
        length = self.seq.lane(lane).length
        last = (max(1, length) - 1) // PAGE
        p = min(self.page.get(lane, 0), last)
        return p * PAGE

    def sound_pages(self):
        return self.sp.pages()

    def page_name(self):
        pages = self.sound_pages()
        return pages[min(self.knob_page, len(pages) - 1)][0] if pages else ""

    def lock_params(self):
        """The 8 settings knobs 1-8 lock while steps are selected (no pad picked): the drum's sound page."""
        pages = self.sound_pages()
        if not pages:
            return []
        self.knob_page = max(0, min(len(pages) - 1, self.knob_page))
        return list(pages[self.knob_page][1])[:8]

    def lock_list(self):
        """[(label, value, locked, lockable)] for knobs 1-8 on the sound page while steps are selected."""
        d = self.T.engine.drums
        st = self.held_step()
        out = []
        for p in self.lock_params():
            locked = p in st.locks
            out.append((d.label(p), d.value_text(p, st.locks[p]) if locked else d.value_text(p), locked,
                        bool(d.lockable(p))))
        return out

    def knob_list(self):
        """[(label, value, locked)] for knobs 1-8 as they are now."""
        sp, e = self.sp, self.T.engine
        lane = sp.lane
        if self.held is None:
            return [(LABELS[p], sp.step_value(p, lane), False) for p in LANE_KNOBS]
        self._aim()
        items = self.pad_items()
        if self.sel is None or self.sel >= len(items):
            return []
        key, label = items[self.sel]
        return [(label, self.item_value(key), self.engaged(key))]

    # ------------------------------------------------------------ a held step's settings on the pads

    def pad_items(self):
        """[(key, label)] for pads 0-31 while a step is held: the step settings, then the drum's sound ones."""
        e = self.T.engine
        items = list(STEP_PADS)
        for _name, params in self.sound_pages():
            for p in params:
                if len(items) >= 32:
                    return items
                if e.drums.lockable(p) and all(p != k for k, _l in items):
                    items.append((p, e.drums.label(p)))
        return items

    def held_step(self):
        return self.seq.step(self.sp.lane, self.held)

    def engaged(self, key):
        st = self.held_step()
        if key == "vel":
            return st.vel != sequencer.DEFAULT_VELOCITY
        if key == "chance":
            return st.chance != 0
        if key == "ratchet":
            return st.ratchet != 1
        if isinstance(key, str):
            return key in st.comp
        return key in st.locks

    def item_value(self, key):
        st, d = self.held_step(), self.T.engine.drums
        if key == "vel":
            return "RND" if st.vel == 0 else str(st.vel)
        if key == "chance":
            return sequencer.CHANCES[st.chance]
        if key == "ratchet":
            return "RND" if st.ratchet == 0 else "x%d" % st.ratchet
        if isinstance(key, str):
            return sequencer.COMPONENTS[key][st.comp[key]] if key in st.comp else "OFF"
        return d.value_text(key, st.locks[key]) if key in st.locks else d.value_text(key)

    def chance_text(self, key):
        """Knob 3's line for the picked pad: the component's chance, or None if the pad has none."""
        if key not in CKEYS:
            return None
        st = self.held_step()
        return sequencer.CHANCES[st.comp.get(key + "_c", 0)] if self.engaged(key) else "SET KNOB 1 1ST"

    def set_chance(self, delta, shift):
        """Knob 3 while a step is held and a component pad picked: how likely it is to happen on those steps."""
        key, label = self.pad_items()[self.sel]
        if key not in CKEYS:
            return
        one = knobgate.gate(("compchance", key), delta, shift)
        if not one:
            return
        sp, seq, e = self.sp, self.seq, self.T.engine
        lane = sp.lane
        if not self.engaged(key):
            popup.show(self.T, self.which(), label + " CHANCE", "SET KNOB 1 FIRST")
            return
        sp._edit(("knob2", self.sel, self.held))
        with seq.lock:
            for j in self.selected:
                if j < seq.lane(lane).length:
                    st = seq.step(lane, j)
                    if (st.ratchet != 1) if key == "ratchet" else (key in st.comp):
                        v = max(0, min(len(sequencer.CHANCES) - 1, st.comp.get(key + "_c", 0) + one))
                        if v:
                            st.comp[key + "_c"] = v
                        else:
                            st.comp.pop(key + "_c", None)
        e.seq_changed()
        popup.show(self.T, self.which(), label + " CHANCE", self.chance_text(key))

    def step_pad(self, p):
        """A pad while a step is held: pick that setting (it's on), or the picked one again: off."""
        if self.held is None:
            return
        items = self.pad_items()
        if p >= len(items):
            return
        key, label = items[p]
        sp, seq, e = self.sp, self.seq, self.T.engine
        lane, i = sp.lane, self.held
        sp._edit(("pad", p, i, time.monotonic()))
        off = self.sel == p
        was_set = self.engaged(key)
        for j in self.selected:
            self._pad_one(lane, j, p, key, off)
        if off:
            self.sel = None                                   # (the knobs: back to the sound page)
            popup.show(self.T, self.which(), label, "OFF" if was_set else "")
        else:
            self.sel = p
            popup.show(self.T, self.which(), label, self.item_value(key), "KNOB 1" + (", 2: CHANCE" if key in CKEYS else ""))
        e.seq_changed()

    def which(self):
        return "STEP %d" % (self.held + 1) if len(self.selected) == 1 else "%d STEPS" % len(self.selected)

    def _pad_one(self, lane, i, p, key, off):
        """Tapping a pad only picks it (to see what it is); it's set when knob 1 turns. Picked again: off."""
        seq = self.seq
        if i >= seq.lane(lane).length or not off:
            return
        with seq.lock:
            st = seq.step(lane, i)
            if key == "vel":
                st.vel = sequencer.DEFAULT_VELOCITY
            elif key == "chance":
                st.chance = 0
            elif key == "ratchet":
                st.ratchet = 1
                st.comp.pop("ratchet_c", None)
            elif isinstance(key, str):
                st.comp.pop(key, None)
                st.comp.pop(key + "_c", None)
            else:
                st.locks.pop(key, None)

    def set_selected(self, delta, shift):
        """Knob 1 while a step is held and a pad picked: that setting."""
        key, label = self.pad_items()[self.sel]
        sp, seq, e = self.sp, self.seq, self.T.engine
        lane, i = sp.lane, self.held
        clicks = self.T.knob_clicks(1, delta, shift)
        if isinstance(key, str) and key != "vel" and key != "chance":     # short lists (multiply, pulse, jump...)
            one = knobgate.gate(("comp", key), delta, shift)
            if not one:
                return
            delta = one
        if not isinstance(key, str) and knobgate.is_choice(e.drums, key):
            clicks = knobgate.gate(("step", key), delta, shift)      # a mode, not a number: several clicks each
            if not clicks:
                return
        sp._edit(("knob1", self.sel, i))
        one = 1 if delta > 0 else -1
        for j in self.selected:
            if j < seq.lane(lane).length:
                self._knob_one(lane, j, key, clicks, one)
        e.seq_changed()
        if not isinstance(key, str):
            sp.audition(lane, i)
        popup.show(self.T, self.which(), label, self.item_value(key))

    def _knob_one(self, lane, i, key, clicks, one):
        seq, e = self.seq, self.T.engine
        with seq.lock:
            st = seq.step(lane, i)
            st.on = True
            if key == "vel":
                st.vel = max(0, min(127, (st.vel or 0) + clicks))
            elif key == "chance":
                st.chance = max(0, min(len(sequencer.CHANCES) - 1, st.chance + one))
            elif key == "ratchet":
                at = RATCHETS.index(st.ratchet) if st.ratchet in RATCHETS else 0
                st.ratchet = RATCHETS[max(0, min(len(RATCHETS) - 1, at + one))]
            elif isinstance(key, str):
                if key in st.comp:
                    st.comp[key] = max(0, min(len(sequencer.COMPONENTS[key]) - 1, st.comp[key] + one))
                else:
                    st.comp[key] = 0                                # the first turn: its first value
                if key in ("rand", "rup", "rdown"):                 # one pitch movement at a time
                    for other in ("rand", "rup", "rdown"):
                        if other != key:
                            st.comp.pop(other, None)
                            st.comp.pop(other + "_c", None)
            else:
                st.locks[key] = e.drums.stepped(key, st.locks.get(key, e.drums.get_param(key)), clicks)

    def pad_lights(self):
        """32 pad lights while a step is held: picked bright, on medium, the rest dim."""
        items = self.pad_items()
        out = []
        for p in range(32):
            if p >= len(items):
                out.append(0)
            elif self.engaged(items[p][0]):
                out.append(127)                            # set (its value was changed): red
            elif p == self.sel:
                out.append(7)                              # tapped, not changed yet: yellow
            else:
                out.append(20)                             # not used: its own dim colour (also after it's cancelled)
        return out

    def playing_step(self):
        e = self.T.engine
        if not e.playing:
            return None
        try:
            return self.seq.position(e._heard_frame(), e.frames_per_beat())[self.sp.lane]
        except Exception:
            return None

    # ------------------------------------------------------------ controls

    def _aim(self):
        """Point the Pi's SeqPage at the held step: its cursor there (shown, so it's used while playing)."""
        sp = self.sp
        sp.cursor = self.held
        sp._cursor_until = time.monotonic() + 2.0

    def pick_lane(self, lane):
        sp = self.sp
        if lane >= sp.d.lanes or self.held is not None:
            return
        sp.lane = lane
        self.T.drum_voice = sp.voice()
        self.knob_page = 0

    @property
    def held(self):
        """The first selected step (its settings are the ones shown), or None."""
        return self.selected[0] if self.selected else None

    def step(self, n, down, shift=False):
        """Step button n (1-16). Shift + tap: select steps (they blink) to set them with the pads; tap any step
        (without Shift) to finish. Otherwise a tap turns the step on or off."""
        i = self.first() + n - 1
        if sequencer.dark(i, sequencer.TRIPLETS):
            return                                            # (TRIPLETS: every 4th step is off and does nothing)
        if not down:
            self.down.discard(i)
            return
        if not shift:
            self.down.add(i)                                  # (held: a chromatic pad now puts its pitch on it)
        lane = self.sp.lane
        length = self.seq.lane(lane).length
        if shift:
            if i >= length:
                self.T.say("STEP %d IS PAST THE END (LENGTH %d: KNOB 1)" % (i + 1, length), 2)
            elif i in self.selected:
                self.selected.remove(i)
            else:
                if not self.selected:                         # the knobs start on the sound page you were on
                    self.knob_page = getattr(self.T, "drum_tab", 0)
                self.selected.append(i)
                self.sel = None
            return
        if self.selected:                                     # finished setting the selected steps
            self.selected, self.sel = [], None
            return
        if self.chrom and i < length:                         # a chromatic pad held + a step tapped: that note on it
            semis = list(self.chrom.values())[-1]
            with self.seq.lock:
                st = self.seq.step(lane, i)
                st.on = True
                st.locks.update(self.pitch_locks(lane, {}, semis))
            self.T.engine.seq_changed()
            self.T.say("STEP %d  PITCH %+d" % (i + 1, semis), 2)
            return
        if i < length:
            self._toggle(lane, i)
        else:
            self.T.say("STEP %d IS PAST THE END (LENGTH %d: KNOB 1)" % (i + 1, length), 2)

    def _toggle(self, lane, i):
        sp = self.sp
        sp._edit(("toggle", time.monotonic()))
        sp.seq.toggle(lane, i)
        self.T.engine.seq_changed()

    def knob(self, number, delta, shift):
        """Knobs 1-8."""
        sp = self.sp
        if self.held is None:
            if number > len(LANE_KNOBS):
                return
            if LANE_KNOBS[number - 1] == "rate":                  # a list of speeds: 6 clicks each
                delta = knobgate.gate(("rate",), delta, shift)
                if not delta:
                    return
                shift = True
            sp.mode, sp.held = 0, {}
            sp.knob(2 + seqpage.STEP_PARAMS.index(LANE_KNOBS[number - 1]), delta, shift)
            if LANE_KNOBS[number - 1] == "length":
                self.T.len_flash = (time.monotonic() + 1.2, self.first(), self.seq.lane(sp.lane).length)
            return
        self._aim()
        if self.sel is not None:
            if number == 1:
                self.set_selected(delta, shift)
            elif number == 2:
                self.set_chance(delta, shift)
            return
        self.lock_knob(number, delta, shift)

    def lock_knob(self, number, delta, shift):
        """A knob while steps are selected (no pad picked): lock that sound setting on them."""
        params = self.lock_params()
        if number > len(params):
            return
        key = params[number - 1]
        e, seq, sp = self.T.engine, self.seq, self.sp
        d = e.drums
        label = d.label(key)
        if not d.lockable(key):
            popup.show(self.T, self.which(), label, "CAN'T BE LOCKED")
            return
        lane, i = sp.lane, self.held
        clicks = self.T.knob_clicks(number, delta, shift)
        if knobgate.is_choice(d, key):
            clicks = knobgate.gate(("step", key), delta, shift)      # a mode, not a number: several clicks each
            if not clicks:
                return
        sp._edit(("lockknob", number, i))
        for j in self.selected:
            if j < seq.lane(lane).length:
                self._knob_one(lane, j, key, clicks, 1 if delta > 0 else -1)
        e.seq_changed()
        sp.audition(lane, i)
        popup.show(self.T, self.which(), label, self.item_value(key))

    def unlock_knob(self, number):
        """Shift + touch a knob while steps are selected: that setting's lock off them."""
        params = self.lock_params()
        if self.sel is not None or number > len(params):
            return
        key, seq, lane = params[number - 1], self.seq, self.sp.lane
        seq.snapshot()
        with seq.lock:
            for j in self.selected:
                if j < seq.lane(lane).length:
                    seq.step(lane, j).locks.pop(key, None)
        self.T.engine.seq_changed()
        popup.show(self.T, self.which(), self.T.engine.drums.label(key), "OFF")

    def lock_choice(self, number):
        """True when knob n (steps selected, no pad picked) is a mode (it counts its own clicks)."""
        params = self.lock_params()
        return number <= len(params) and knobgate.is_choice(self.T.engine.drums, params[number - 1])

    def plus_minus(self, way):
        """+ / -: the knob page while a step is held, else the pattern."""
        if self.held is not None:
            return
        T = self.T                                              # + / - are the pads' octave (patterns: Shift + a pad)
        T.octave = max(-4, min(4, getattr(T, "octave", 0) + way))
        T.say("OCTAVE %s" % ("%+d" % T.octave if T.octave else "0"), 2)

    def arrows(self, way):
        """<- / ->: the lane's next or previous 16 steps (steps selected: the drum's sound pages for the knobs)."""
        if self.selected:
            pages = self.sound_pages()
            if pages:
                self.knob_page = max(0, min(len(pages) - 1, self.knob_page + way))
                self.sel = None
                self.T.say("KNOBS: %s (%d/%d)" % (self.page_name(), self.knob_page + 1, len(pages)), 2)
            return
        lane = self.sp.lane
        length = self.seq.lane(lane).length
        last = (max(1, length) - 1) // PAGE
        p = max(0, min(last, self.first() // PAGE + way))
        self.page[lane] = p
        self.T.say("STEPS %d-%d OF %d" % (p * PAGE + 1, p * PAGE + PAGE, length), 2)

    # ------------------------------------------------------------ lights

    def step_lights(self):
        """16 light values for the step buttons."""
        lane = self.sp.lane
        ln = self.seq.lane(lane)
        first = self.first()
        at = self.playing_step()
        out = []
        for k in range(PAGE):
            i = first + k
            if i >= ln.length or sequencer.dark(i, sequencer.TRIPLETS):
                v = 0
            elif i in self.selected:
                v = 127 if int(time.monotonic() * 4) % 2 else 0
            else:
                on = ln.steps[i].on
                v = 127 if on else sequencer.STEP_IDLE         # (an empty step: dim white, so a dark one shows)
                if at is not None and i == at:
                    v = 20 if on else 60                  # the playhead: on steps dim, off steps glow
            out.append(v)
        return out
