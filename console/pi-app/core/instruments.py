"""The instrument slots, played by the sound core (core.c) instead of rendered in Python.

Each machine keeps working as before from the app's side: set_param(), hit(), note_on() and the rest still
just queue things up (machine._pending). What changes is who acts on them. Instead of machine.render() doing
the work in Python, this file turns the queue, and the sequencer's steps, into the core's timed events:
calls into the machine's library at the right frame (settings and step locks), and triggers / MIDI notes.

Every machine has two copies, as before: "seq" (the sequencer plays it) and "live" (your hands do). Each
copy is one core source.
"""
import math
import time

import autom

import arp as arplib
import drums
from core import Core  # noqa: F401  (for type hints in docs)

sw_modules = drums.schwung_modules         # schwung/modules.py, as drums.py loaded it (None if it couldn't)

NOTE_LEN = 4410            # how long a drum module's pad note is held (frames): they only need the start


class _Calls:
    """Stands in for an instrument library: every call becomes a core event at frame `at`."""

    def __init__(self, core, lib, at=0):
        self._core, self._lib, self._at = core, lib, at

    def __getattr__(self, name):
        fn = getattr(self._lib, name)
        core, at = self._core, self._at
        return lambda *args: core.call(fn, *[a if isinstance(a, (bytes, int)) else int(a) for a in args], at=at)


class _InstCalls:
    """Stands in for a Schwung module instance (modules.Instance): set() becomes a core event."""

    def __init__(self, core, inst, at=0):
        self._core, self._inst, self._at = core, inst, at

    def set(self, key, value):
        h = sw_modules.host()
        self._core.call(h.sh_set, self._inst.ptr, key.encode(), str(value).encode(), at=self._at)


def kind(m):
    if isinstance(m, drums.LXR):
        return "lxr"
    if sw_modules and isinstance(m, sw_modules.SynthModule):
        return "synth"
    if sw_modules and isinstance(m, sw_modules.Module):
        return "module"
    return "engine"                         # the 606, 808, Machinedrum (Schwung class in drums.py)


class Slot:
    """One machine in the core: its two sources, and how its steps and settings turn into events."""

    def __init__(self, core, machine, k=None):
        """k: the instrument slot (0-7) it's in: the core then makes its recording inputs and mixes it as a
        slot. None: mixed on its own (tests)."""
        self.core, self.m, self.kind, self.k = core, machine, kind(machine), k
        m = machine
        if self.kind == "lxr":
            self.seq_lib, self.live_lib = drums._lib, drums._live
            self.seq = core.add_engine(drums._lib.drums_render, drums._lib.drums_trigger, drums.VOICES)
            self.live = (core.add_engine(drums._live.drums_render, drums._live.drums_trigger, drums.VOICES)
                         if drums._live is not drums._lib else self.seq)
        elif self.kind == "engine":
            self.seq_lib, self.live_lib = m._lib, m._live
            self.seq = core.add_engine(m._lib.sw_render, m._lib.sw_trigger, m.voices)
            self.live = core.add_engine(m._live.sw_render, m._live.sw_trigger, m.voices) \
                if m._live is not m._lib else self.seq
        else:
            h = sw_modules.host()
            self.seq = core.add_module(h.sh_render, h.sh_midi, m._seq.ptr)
            self.live = core.add_module(h.sh_render, h.sh_midi, m._live.ptr) if m._live is not m._seq else self.seq
        self.arp = arplib.Arp()              # a synth's arpeggiator: the pads you hold (live source) ...
        self.arp_seq = arplib.Arp()          # ... and the sequencer's chords (seq source); they share the settings
        self._refresh_after = None          # (core frame) a module re-reads its settings once the core has them
        self.fx = None
        if k is not None:
            voices = drums.VOICES if self.kind == "lxr" else (m.voices if self.kind == "engine" else 2)
            core.slot(k, self.seq, self.live, voices)
            self.voices = voices
            for v, lane in self.lanes(voices).items():
                core.slot_lane(k, v, lane)
            try:
                import effects
                if effects.AVAILABLE:
                    self.fx = (effects.Reverb(core.rate), effects.Delay(core.rate))
                    core.slot_effects(k, self.fx[0].h, self.fx[1].h)
            except Exception as e:                              # noqa: BLE001
                print("Slot effects:", e)
        self.sync_mix()
        core.on(self.seq)
        core.on(self.live)

    def sources(self):
        return {self.seq, self.live}

    def lanes(self, voices):
        """{voice: DRUM n channel (0-7)}: how the machine's drums land on their own recording inputs."""
        m = self.m
        if self.kind == "lxr":
            return {v: v for v in range(min(voices, 8))}
        if self.kind == "engine":
            if isinstance(m, drums.Machinedrum):
                return {v: v % m.channels for v in range(voices)}
            out = {}
            for lane, v in enumerate(m.lane_voice):
                out.setdefault(v, lane % m.channels)
            return out
        return {}                                   # modules and synths: only the kit (stereo) inputs

    def remove(self):
        if self.k is not None:
            self.core.slot_clear(self.k)
        for s in self.sources():
            self.core.remove(s)

    def effect_settings(self, rev_size, rev_tone, dly_samples, dly_feedback, rev_width=1.0):
        """The slot's own effects (printed into its KIT inputs) follow the main ones' settings."""
        if self.fx:
            self.fx[0].set(rev_size, rev_tone, rev_width)
            self.fx[1].set(dly_samples, dly_feedback)

    def sync_mix(self, gain=0.8):
        """Pans and effect sends, from the machine (call when they may have changed)."""
        pans = self.m.pans()
        rev, dly = self.m.sends()
        if self.k is not None:
            lv = float(getattr(self, "level", 1.0))                       # the MIXER: volume and pan of the whole instrument
            a = (float(getattr(self, "balance", 0.0)) + 1.0) * math.pi / 4
            gl, gr = math.cos(a) * math.sqrt(2) * lv, math.sin(a) * math.sqrt(2) * lv
            for v in range(len(pans)):
                self.core.slot_mix(self.k, v, float(pans[v][0]) * gl, float(pans[v][1]) * gr,
                                   (float(rev[v]) if v < len(rev) else 0.0) * lv,
                                   (float(dly[v]) if v < len(dly) else 0.0) * lv)
            return
        for s in self.sources():
            for v in range(len(pans)):
                self.core.pan(s, v, float(pans[v][0]), float(pans[v][1]))
                if v < len(rev):
                    self.core.sends(s, v, float(rev[v]), float(dly[v]))
            self.core.gain(s, gain)

    # ---- what's queued on the machine (settings, hits by hand), now
    def flush(self):
        m = self.m
        with m._lock:
            todo, m._pending = m._pending, []
        if not todo:
            return
        c = self.core
        for t in todo:
            what = t[0]
            if self.kind in ("lxr", "engine"):
                libs = [self.seq_lib] + ([self.live_lib] if self.live_lib is not self.seq_lib else [])
                if what == "hit":
                    lane = t[1]
                    if self.kind == "lxr":
                        c.trigger(self.live, lane, t[2])
                    elif 0 <= lane < m.lanes:
                        c.trigger(self.live, m.lane_voice[lane], t[2])
                elif what == "param":
                    for lib in libs:
                        if self.kind == "lxr":
                            c.call(lib.drums_set_param, t[1], t[2])
                        else:
                            m._set(_Calls(c, lib), t[1], t[2])
                    if self.kind == "lxr":
                        m._pans = None
                elif what == "bpm" and self.kind == "lxr":
                    for lib in libs:
                        c.call(lib.drums_set_bpm, t[1])
            else:
                insts = [m._seq] + ([m._live] if m._live is not m._seq else [])
                if what == "hit" and 0 <= t[1] < m.lanes:
                    note = sw_modules.FIRST_PAD + t[1]
                    at = c.now()
                    c.midi(self.live, 0x90, note, max(1, min(127, t[2])))
                    c.midi(self.live, 0x80, note, 0, at=at + NOTE_LEN)
                elif what == "on":
                    if self.arp.on:
                        self.arp.press(int(t[1]), max(1, min(127, int(t[2]))))
                    else:
                        c.midi(self.live, 0x90, max(0, min(127, t[1])), max(1, min(127, t[2])))
                elif what == "off":
                    if self.arp.on:
                        self.arp.release(int(t[1]))
                    else:
                        c.midi(self.live, 0x80, t[1], 0)
                elif what == "all_off":
                    now = c.now()
                    self.arp.stop(c.midi, self.live, now)
                    self.arp_seq.stop(c.midi, self.seq, now)
                    for s in self.sources():
                        c.midi(s, 0xB0, 64, 0)                  # the sustain pedal up
                        c.midi(s, 0xB0, 123, 0)                 # all notes off (some synths ignore it)...
                        for note in range(128):                 # ...so every note is let go one by one (they ring out)
                            c.midi(s, 0x80, note, 0)
                elif what == "param":
                    for inst in insts:
                        m._apply(_InstCalls(c, inst), t[1], t[2])
                elif what == "raw":                              # a module setting that isn't a knob (a bank)
                    for inst in insts:
                        _InstCalls(c, inst).set(t[1], t[2])
                elif what == "refresh":
                    self._refresh_after = c.now() + 2 * c.block
        self.sync_mix()

    def tick(self):
        """Call now and then: finishes jobs that wait for the core (a module re-reading its settings)."""
        if self._refresh_after is not None and self.core.now() >= self._refresh_after:
            self._refresh_after = None
            self.m._refresh()
        if self.kind == "synth":
            a = self.arp
            if a.on:
                a.tick(self.core.midi, self.live, self.core.now())
            elif a.held or a.next_t is not None:             # switched off while it was going: let go
                a.stop(self.core.midi, self.live, self.core.now())

    def set_arp(self, cfg, fpb, origin):
        """The synth's arp settings (a dict kept with its sequencer), the tempo, and where the sequencer's clock is."""
        was_hold = self.arp.cfg.get("hold")
        self.arp.cfg = self.arp_seq.cfg = cfg
        self.arp.fpb = self.arp_seq.fpb = fpb
        self.arp.origin = self.arp_seq.origin = origin
        if was_hold and not cfg.get("hold"):
            self.arp.unhold()

    # ---- the sequencer's steps, at their frames
    def _base(self, p):
        """A setting's value between locks: the recorded automation's, or the knob's."""
        return getattr(self.m, "_auto", {}).get(p, self.m.values[p])

    def automate(self, events, base):
        """Recorded automation: [(offset, AUTO, 0, {setting: value, or None: the knob's own})] (autom.events)."""
        m, c = self.m, self.core
        if m is None or not hasattr(m, "values"):
            return
        auto = m.__dict__.setdefault("_auto", {})
        for offset, _lane, _vel, d in events:
            at = int(base + offset)
            for p, v in d.items():
                if not (isinstance(p, int) and 0 <= p < len(m.values)):
                    continue
                if isinstance(v, autom.Glide) and getattr(m, "params", None) and p < len(m.params) \
                        and m.params[p].get("kind") in ("menu", "onoff"):
                    continue                                 # (a menu jumps from step to step)
                if v is None:
                    auto.pop(p, None)
                    v = m.values[p]
                else:
                    auto[p] = v
                if self.kind == "lxr":
                    _Calls(c, self.seq_lib, at).drums_set_param(p, v)
                    m._pans = None
                elif self.kind == "engine":
                    m._set(_Calls(c, self.seq_lib, at), p, v)
                else:
                    m._apply(_InstCalls(c, m._seq, at), p, v)

    def auto_reset(self):
        """Stopped: the settings back to the knobs."""
        m = self.m
        auto = getattr(m, "_auto", None)
        if auto:
            self.automate([(0, "auto", 0, {p: None for p in list(auto)})], self.core.now())

    def play(self, events, base):
        """events: from the sequencer, [(offset, lane or note, velocity, locks)]; base: the core frame offset 0
        is at."""
        m, c = self.m, self.core
        chords = []                                          # (at, [notes], velocity, gate) when the arp is on
        for offset, lane, vel, locks in events:
            at = int(base + offset)
            if self.kind == "lxr":
                voice = min(lane, drums.VOICES - 1)
                lib = _Calls(c, self.seq_lib, at)
                for p in m._locked[voice] - set(locks):
                    lib.drums_set_param(p, self._base(p))
                for p, v in locks.items():
                    lib.drums_set_param(p, v)
                if locks or m._locked[voice]:
                    m._pans = None
                m._locked[voice] = set(locks)
                c.trigger(self.seq, lane, vel, at=at)
            elif self.kind == "engine":
                if not 0 <= lane < m.lanes:
                    continue
                voice = m.lane_voice[lane]
                lib = _Calls(c, self.seq_lib, at)
                for p in m._locked[voice] - set(locks):
                    m._set(lib, p, self._base(p))
                for p, v in locks.items():
                    if 0 <= p < m.param_count:
                        m._set(lib, p, v)
                m._locked[voice] = set(p for p in locks if 0 <= p < m.param_count)
                c.trigger(self.seq, voice, vel, at=at)
            elif self.kind == "module":
                if not 0 <= lane < m.lanes:
                    continue
                inst = _InstCalls(c, m._seq, at)
                for p in m._locked[lane] - set(locks):
                    m._apply(inst, p, self._base(p))
                for p, v in locks.items():
                    if 0 <= p < m.param_count:
                        m._apply(inst, p, v)
                m._locked[lane] = set(p for p in locks if 0 <= p < m.param_count)
                note = sw_modules.FIRST_PAD + lane
                c.midi(self.seq, 0x90, note, max(1, min(127, vel)), at=at)
                c.midi(self.seq, 0x80, note, 0, at=at + NOTE_LEN)
            else:                                            # a synth: lane is the note
                if not 0 <= lane <= 127:
                    continue
                locks = dict(locks)
                gate = max(1, int(locks.pop("gate", 4410)))
                inst = _InstCalls(c, m._seq, at)
                for p in m._locked[0] - set(locks):
                    m._apply(inst, p, self._base(p))
                for p, v in locks.items():
                    if isinstance(p, int) and 0 <= p < m.param_count:
                        m._apply(inst, p, v)
                m._locked[0] = set(p for p in locks if isinstance(p, int) and 0 <= p < m.param_count)
                if self.arp_seq.on:
                    if chords and abs(chords[-1][0] - at) <= 64:
                        chords[-1][1].append(lane)
                        chords[-1][3] = max(chords[-1][3], gate)
                    else:
                        chords.append([at, [lane], max(1, min(127, vel)), gate])
                else:
                    c.midi(self.seq, 0x90, lane, max(1, min(127, vel)), at=at)
                    c.midi(self.seq, 0x80, lane, 0, at=at + gate)
        if chords:
            self.arp_seq.expand(c.midi, self.seq, [tuple(g) for g in chords])


class Scheduler:
    """Plays sequencers through the core: every few milliseconds, the steps falling in the next LOOKAHEAD
    frames are sent with their exact frames.

        sched = Scheduler(core)
        sched.start(slots_and_sequencers, frames_per_beat)   # at the next moment possible
    """

    LOOKAHEAD = 4410                       # 100 ms

    def __init__(self, core):
        self.core = core
        self.playing = False
        self.start_frame = 0               # the core frame the sequencer's frame 0 is at
        self.sent = 0                      # sequencer frames sent so far

    def start(self, delay=1024):
        self.start_frame = self.core.now() + delay
        self.sent = 0
        self.playing = True

    def stop(self):
        self.playing = False

    def seq_frame(self):
        """Where the sequencer is now, in its own frames."""
        return max(0, self.core.now() - self.start_frame)

    def tick(self, plays, frames_per_beat, on_events=None):
        """plays: [(Slot, sequencer)]. Sends what falls before now + LOOKAHEAD. on_events(slot, events, base):
        told about each batch (the screen flashes the hits)."""
        if not self.playing:
            return
        want = self.core.now() + self.LOOKAHEAD - self.start_frame
        if want <= self.sent:
            return
        n = int(want - self.sent)
        for slot, seq in plays:
            ev = seq.events(self.sent, n, frames_per_beat)
            try:
                au = autom.events(seq, self.sent, n, frames_per_beat)
                if au:
                    slot.automate(au, self.start_frame + self.sent)    # (before the notes: a note's lock wins)
            except Exception as e:                       # noqa: BLE001
                print("Automation:", e)
            if ev:
                slot.play(ev, self.start_frame + self.sent)
                if on_events:
                    on_events(slot, ev, self.start_frame + self.sent)
        self.sent += n


def run_forever(core, slots, plays_fn, fpb_fn, sched, stop, period=0.005):
    """A simple loop for tests: flushes each slot and drives the scheduler until stop() is true."""
    while not stop():
        for s in slots:
            s.flush()
            s.tick()
        sched.tick(plays_fn(), fpb_fn())
        time.sleep(period)
