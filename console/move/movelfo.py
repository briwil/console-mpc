"""The LFO pages on the Move: after the last settings page of an instrument (Right past it), LFO 1, LFO 2, INSERT 1, INSERT 2
and SENDS (knobs 1-4: its REVERB and DELAY sends, how much of SONG INSERT 1 and 2 it hears).
Step buttons: tap = that step of the LFO rests, hold + knob 2/4 = its own WAVE/DEPTH. Knobs 1-6: DEST, WAVE, SPEED, DEPTH, PHASE, MODE (see pi-app/lfo.py). Each pattern has its own."""
import arp
import knobgate
import lfo
import notes as notes_mod
import sequencer

LABELS = ["DEST", "WAVE", "SPEED", "DEPTH", "PHASE", "MODE"]
CHOICE = {0, 1, 2, 5}                         # knobs that pick from a list: several clicks each


class MoveLFO:
    def __init__(self, T):
        self.T = T
        self.tab = None                       # None (the settings pages), 0 (LFO 1) or 1 (LFO 2)
        self.held = {}                        # step buttons held: step -> True once a knob has used it

    def active(self):
        T = self.T
        if not T.drum_page:
            self.tab = None
        return self.tab is not None and bool(T.drum_page and not T.seq_page and not T.fx_page and T.engine and T.engine.drums)

    def _inserts(self):
        return 2 if self.T.insert_fx_available() else 0

    def has_arp(self):
        """A synth has an arpeggiator page, the last one."""
        return bool(self.T.synth_shown())

    def sends_tab(self):
        return lfo.COUNT + self._inserts()

    def sends_on_page(self):
        return self.tab is not None and self.tab == self.sends_tab()

    def arp_tab(self):
        return self.sends_tab() + 1 if self.has_arp() else None

    def last(self):
        """The last tab Right goes to: LFO 1, LFO 2, then (if the effects came with the update) INSERT 1, INSERT 2,
        then SENDS. A synth's ARP (and ARP 2) and PADS come after it, but only by Shift + step 3 / step 2."""
        return self.sends_tab()

    def insert_pos(self):
        """0 / 1 while on the INSERT 1 / 2 page, else None."""
        if self.tab is not None and lfo.COUNT <= self.tab < lfo.COUNT + self._inserts():
            return self.tab - lfo.COUNT
        return None

    def pads_tab(self):
        return self.arp_tab() + 2 if self.has_arp() else self.sends_tab() + 1

    def pads_on_page(self):
        """True on the PADS page (the hexagon icon): the pads' key, scale and octave."""
        return self.tab is not None and self.tab == self.pads_tab()

    def goto_pads(self):
        if True:                                     # (a synth's or a drum machine's)
            if self.pads_on_page():
                self.tab = None
                return
            self.tab = self.pads_tab()
            self.T.say("PADS", 2)

    def pads_values(self):
        """[(label, text)]: a synth's KEY, SCALE, OCTAVE, VELOCITY, CURVE; a drum machine has no key or scale, so
        its knobs 1-3 are OCTAVE (the chromatic pads), VELOCITY, CURVE."""
        seq, oc = self.T.engine.seq, getattr(self.T, "octave", 0)
        v = getattr(self.T, "pad_vel", 0)
        feel = [("OCTAVE", "%+d" % oc if oc else "0"), ("VELOCITY", str(v) if v else "TOUCH"),
                ("CURVE", ("SOFT", "NORMAL", "HARD")[getattr(self.T, "pad_curve", 1)])]
        if not self.has_arp():
            return feel
        return [("KEY", notes_mod.NAMES[seq.root]), ("SCALE", notes_mod.SCALES[seq.scale][0]),
                ("OCTAVE", "%+d" % oc if oc else "0"), ("VELOCITY", str(v) if v else "TOUCH"),
                ("CURVE", ("SOFT", "NORMAL", "HARD")[getattr(self.T, "pad_curve", 1)])]

    def pads_knob(self, number, delta, shift):
        T = self.T
        if not self.has_arp():                       # a drum machine: knobs 1-3 are a synth's 3-5
            if number > 3:
                return
            number += 2
        seq = T.engine.seq
        way = knobgate.gate(("pads", number), delta, shift)
        if not way:
            return
        one = 1 if way > 0 else -1
        if number == 1:
            seq.set_scale(root=seq.root + one)
        elif number == 2:
            seq.set_scale(scale=seq.scale + one)
        elif number == 3:
            T.octave = max(-4, min(4, getattr(T, "octave", 0) + one))
        elif number == 4:                                # TOUCH (as you hit them) or a fixed velocity
            v = getattr(T, "pad_vel", 0)
            v = 100 if (v == 0 and one > 0) else v + 5 * one
            T.pad_vel = 0 if v < 10 else min(127, v)
            T.engine.remember("pad_vel", T.pad_vel)
        elif number == 5:
            T.pad_curve = max(0, min(2, getattr(T, "pad_curve", 1) + one))
            T.engine.remember("pad_curve", T.pad_curve)
        else:
            return
        T.engine.seq_changed()
        T.say("%s  %s" % self.pads_values()[number - (1 if self.has_arp() else 3)], 2)

    def arp_on_page(self):
        """True on the ARP page."""
        return self.tab is not None and self.arp_tab() is not None and self.tab in (self.arp_tab(), self.arp_tab() + 1)

    def arp_second(self):
        """True on ARP 2 (glide, bend)."""
        return self.tab is not None and self.arp_tab() is not None and self.tab == self.arp_tab() + 1

    def goto_arp(self):
        """Shift + step 3 (the ARP icon) on a synth's sound pages: straight to the arp page, and back again."""
        if self.has_arp():
            if self.arp_on_page():                    # its own icon again: back to the settings pages
                self.tab = None
                return
            self.tab = self.arp_tab()
            self.T.say("ARP", 2)

    # ------------------------------------------------------------ SENDS
    def sends_values(self):
        """[(label, text)]: REVERB, DELAY (this instrument's sends), SONG INSERT 1, 2 (how much of each it hears)."""
        T, e = self.T, self.T.engine
        out = []
        for kind in ("reverb", "delay"):
            v = e.inst_send(kind)
            out.append((kind.upper(), "%d%%" % round(v * 100) if v is not None else "OWN FX"))
        if self._inserts():
            slot = e.slot if e.slot is not None else 0
            for p in (0, 1):
                sf = T.songfx(p)
                out.append(("SONG INS %d" % (p + 1), "%d%%" % sf.amount(slot) if sf.index else "NONE"))
        return out

    def sends_knob(self, number, delta):
        T, e = self.T, self.T.engine
        if number in (1, 2):
            kind = "reverb" if number == 1 else "delay"
            v = e.change_inst_sends(kind, delta * 0.02)
            T.say("%s SEND  %s" % (kind.upper(), "%d%%" % round(v * 100) if v is not None else "OWN FX"), 2)
        elif number in (3, 4) and self._inserts():
            sf = T.songfx(number - 3)
            if not sf.index:
                T.say("SONG INSERT %d IS EMPTY (LEFT BUTTON 3)" % (number - 2), 2)
                return
            slot = e.slot if e.slot is not None else 0
            v = sf.set_amount(slot, sf.amount(slot) + 2 * delta)
            T._insfx_save()
            T.say("SONG INSERT %d  %d%%" % (number - 2, v), 2)

    def cfg(self):
        return self.T.engine.seq.arp_cfg

    def arp_values(self):
        """[(label, text)] for the page's knobs: ARP 1 (ON ... STYLE) or ARP 2 (GLIDE, BEND)."""
        c = self.cfg()
        if self.arp_second():
            return [("GLIDE", "%d%%" % c["glide"] if c["glide"] else "OFF"),
                    ("BEND", "%+d%%" % c["bend"] if c["bend"] else "OFF")]
        return [("ON", "ON" if c["on"] else "OFF"), ("MODE", arp.MODES[c["mode"]]), ("OCT", str(c["oct"])),
                ("RATE", sequencer.RATES[c["rate"]][0]), ("GATE", "%d%%" % c["gate"]),
                ("HOLD", "ON" if c["hold"] else "OFF"), ("STYLE", arp.STYLES[c["style"]])]

    def arp_knob(self, number, delta, shift):
        c = self.cfg()
        k = number - 1
        if self.arp_second():
            if k == 0:
                c["glide"] = max(0, min(100, c["glide"] + 5 * delta))
            elif k == 1:
                c["bend"] = max(-100, min(100, c["bend"] + 5 * delta))
            else:
                return
            self.T.engine.seq_changed()
            self.T.say("ARP  %s  %s" % self.arp_values()[k], 2)
            return
        if k in (0, 1, 2, 3, 5, 6):                  # a list or a switch: several clicks a choice
            way = knobgate.gate(("arp", k), delta, shift)
            if not way:
                return
            one = 1 if way > 0 else -1
            if k == 0:
                c["on"] = 1 if one > 0 else 0
            elif k == 1:
                c["mode"] = max(0, min(len(arp.MODES) - 1, c["mode"] + one))
            elif k == 2:
                c["oct"] = max(1, min(4, c["oct"] + one))
            elif k == 3:
                c["rate"] = sequencer.next_rate(c["rate"], one)
            elif k == 5:
                c["hold"] = 1 if one > 0 else 0
            else:
                c["style"] = max(0, min(len(arp.STYLES) - 1, c["style"] + one))
        elif k == 4:
            c["gate"] = max(10, min(200, c["gate"] + 5 * delta))
        else:
            return
        self.T.engine.seq_changed()
        self.T.say("ARP  %s  %s" % self.arp_values()[k], 2)

    def arp_step(self, n, down):
        """A step button on the ARP page: tap it to go note -> accent -> rest -> note."""
        if down:
            return
        c = self.cfg()
        c["rhythm"][n - 1] = {1: 2, 2: 0, 0: 1}[c["rhythm"][n - 1]]
        self.T.engine.seq_changed()
        self.T.say("ARP STEP %d: %s" % (n, ("REST", "NOTE", "ACCENT")[c["rhythm"][n - 1]]), 2)

    def arrows(self, way, last_tab):
        """Left / Right on a sound page. Returns True if it moved between the LFO pages / off the settings."""
        T = self.T
        if self.tab is None:
            if way > 0 and T.drum_tab >= last_tab:
                self.tab = 0
                return True
            return False
        if self.pads_on_page():
            return True                              # (PADS is on its own: Shift + step 2 again leaves it)
        if self.arp_on_page():                       # ARP <-> ARP 2, and no further
            self.tab = self.arp_tab() + (1 if way > 0 else 0)
            return True
        self.tab = self.tab + way
        if self.tab < 0:
            self.tab = None
        self.tab = None if self.tab is None else min(self.last(), self.tab)
        return True

    def step(self, n, down):
        if self.pads_on_page():
            return
        if self.arp_on_page():
            self.arp_step(n, down)
            return
        if self.insert_pos() is not None or self.sends_on_page():
            return
        """A step button (1-16): a tap mutes / unmutes that step of the LFO; hold it and turn DEPTH (knob 4) or WAVE
        (knob 2) to give the step its own."""
        i = n - 1
        if down:
            self.held[i] = False
            return
        used = self.held.pop(i, True)
        if not used:
            steps = self.cur().setdefault("steps", {})
            st = steps.setdefault(i, {})
            if st.get("mute"):
                st.pop("mute")
            else:
                st["mute"] = 1
            if not st:
                steps.pop(i, None)
            self.T.engine.seq_changed()
            self.T.say("%sLFO %d STEP %d %s" % (self.who(), self.tab + 1, n, "RESTS" if st.get("mute") else "PLAYS"), 2)

    def step_lights(self):
        if self.pads_on_page():
            return [0] * 16
        if self.arp_on_page():
            return [{0: 0, 1: 120, 2: 127}[x] for x in self.cfg()["rhythm"]]
        if self.insert_pos() is not None or self.sends_on_page():
            return [0] * 16
        steps = self.cur().get("steps", {})
        out = []
        for i in range(16):
            st = steps.get(i)
            out.append(127 if i in self.held else 0 if st and st.get("mute") else 45 if st else 20)
        return out

    def lfos(self):
        e = self.T.engine
        d = e.drums
        n = lfo.per_drum(d)
        if not n:
            return lfo.of(e.seq.pattern)
        pat = e.seq.pattern
        old = getattr(pat, "lfos", None) is not None and len(pat.lfos) < n * lfo.COUNT
        out = lfo.of(pat, n * lfo.COUNT)
        if old:
            lfo.spread(pat, d)                           # (a song from before: each LFO to its drum)
        return out

    def base(self):
        """Where the LFOs of the drum you're on start in lfos() (a sampler: each drum has its own two)."""
        d = self.T.engine.drums
        return min(self.T.drum_voice, lfo.per_drum(d) - 1) * lfo.COUNT if lfo.per_drum(d) else 0

    def who(self):
        """ "D3 " on a sampler (whose drum's LFO it is), else "". """
        return "D%d " % (self.base() // lfo.COUNT + 1) if lfo.per_drum(self.T.engine.drums) else ""

    def cur(self):
        """The LFO on the page (for a sampler: of the drum you're on)."""
        return self.lfos()[self.base() + self.tab]

    def insert_dests(self):
        """[dest] the number settings of this instrument's two insert effects (the LFO can move them too)."""
        out = []
        if not self.T.insert_fx_available():
            return out
        for pos in (0, 1):
            ins = self.T.insfx(None, pos)
            if ins.h:
                out += [lfo.INSERT_DEST + 8 * pos + i for i, p in enumerate(ins.params) if not p[6]]
        return out

    def insert_label(self, dest):
        pos, idx = divmod(dest - lfo.INSERT_DEST, 8)
        ins = self.T.insfx(None, pos)
        return "I%d %s" % (pos + 1, ins.params[idx][1] if idx < len(ins.params) else "?")

    def dests(self):
        d = self.T.engine.drums
        mine = bool(lfo.per_drum(d))                         # (a sampler: the settings of the drum you are on, not all 16's)
        return lfo.settings_dest(d, self.T.drum_voice if mine else None) + self.insert_dests()

    def values(self):
        """[(label, text)] for knobs 1-6."""
        e = self.T.engine
        l = self.cur()
        d = e.drums
        dest = "OFF"
        if l["dest"] >= lfo.INSERT_DEST:
            dest = self.insert_label(l["dest"])[:9] if l["dest"] in self.insert_dests() else "OFF"
        elif l["dest"] >= 0 and l["dest"] < getattr(d, "param_count", 0):
            dest = ("%s" % d.label(l["dest"]))
            if getattr(d, "id", "") == "sampler":              # which drum: "D3 LEVEL"
                dest = "D%d %s" % (d.params[l["dest"]]["voice"] + 1, dest)
            dest = dest[:9]
        return [("DEST", dest), ("WAVE", lfo.WAVES[l["wave"]]), ("SPEED", lfo.SPEEDS[l["speed"]][0]),
                ("DEPTH", "%+d%%" % l["depth"]), ("PHASE", "%d%%" % l["phase"]), ("MODE", lfo.MODES[l["mode"]])]

    def is_choice(self, n):
        if self.pads_on_page():
            return True
        if self.arp_on_page():
            return (not self.arp_second()) and (n - 1) in (0, 1, 2, 3, 5, 6)
        if self.insert_pos() is not None or self.sends_on_page():
            return False
        if self.held:
            return n == 2
        return (n - 1) in CHOICE

    def knob(self, number, delta, shift):
        if self.sends_on_page():
            self.sends_knob(number, delta)
            return
        if self.pads_on_page():
            self.pads_knob(number, delta, shift)
            return
        if self.arp_on_page():
            self.arp_knob(number, delta, shift)
            return
        pos = self.insert_pos()
        if pos is not None:                           # an INSERT page: knobs 1-8 are the effect's first eight settings
            ins = self.T.insfx(None, pos)
            if number <= 8:
                ins.knob(number - 1, delta)
                self.T._insfx_save()
            return
        if number > len(LABELS):
            return
        e = self.T.engine
        l = self.cur()
        k = number - 1
        if self.held and k in (1, 3):                 # a held step: its own WAVE / DEPTH
            steps = self.cur().setdefault("steps", {})
            way = knobgate.gate(("lfostep", k), delta, shift) if k == 1 else delta
            if not way:
                return
            for i in self.held:
                self.held[i] = True
                st = steps.setdefault(i, {})
                if k == 1:
                    st["wave"] = max(0, min(len(lfo.WAVES) - 1, st.get("wave", l["wave"]) + (1 if way > 0 else -1)))
                else:
                    st["depth"] = max(-100, min(100, st.get("depth", l["depth"]) + way))
                shown = lfo.WAVES[st["wave"]] if k == 1 else "%+d%%" % st["depth"]
            e.seq_changed()
            self.T.say("STEP %s  %s  %s" % (",".join(str(i + 1) for i in sorted(self.held)), LABELS[k], shown), 2)
            return
        if k in CHOICE:
            way = knobgate.gate(("lfo", k), delta, shift)
            if not way:
                return
            one = 1 if way > 0 else -1
            if k == 0:
                opts = [-1] + self.dests()
                i = opts.index(l["dest"]) if l["dest"] in opts else 0
                l["dest"] = opts[max(0, min(len(opts) - 1, i + one))]
            elif k == 1:
                l["wave"] = max(0, min(len(lfo.WAVES) - 1, l["wave"] + one))
            elif k == 2:
                l["speed"] = lfo.next_speed(l["speed"], one)
            else:
                l["mode"] = max(0, min(len(lfo.MODES) - 1, l["mode"] + one))
        elif k == 3:
            l["depth"] = max(-100, min(100, l["depth"] + delta))
        elif k == 4:
            l["phase"] = max(0, min(100, l["phase"] + delta))
        e.seq_changed()
        self.T.say("%sLFO %d  %s  %s" % (self.who(), self.tab + 1, LABELS[k], self.values()[k][1]), 2)
