"""Python's side of the sound core (core.c): set it up, hand it the instruments, send it events, read the
Move's controls. The core runs in JACK's audio thread; nothing here does.

    c = Core()                                   # starts the JACK client (console mode must be running)
    s = c.add_engine(lib, voices=6)              # an engine library: lib.<prefix>_render / _trigger
    c.trigger(s, voice, velocity)                # as soon as possible (or at=frame)
    for frame, msg in c.read_midi(): ...         # pads, knobs, buttons
"""
import ctypes as C
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libconsolecore.so")
LIBJACK = os.environ.get("CONSOLE_LIBJACK", "/data/UserData/rnbo/lib/libjack.so.0")

EV_TRIGGER, EV_MIDI, EV_CALL, EV_TRANSPORT = 1, 2, 3, 4
T_PLAY, T_STOP, T_LOCATE, T_RECORD, T_RECORD_OFF = 1, 2, 3, 4, 5
SLOT_CH, DRUM_KIT = 11, 8      # as core.c and audio.py: each slot's recording inputs
BOX = None                     # numpy dtype of a box, made on first use (numpy only loaded if needed)
u64, vp, i32, f32, ip = C.c_uint64, C.c_void_p, C.c_int, C.c_float, C.c_ssize_t


def addr(fn):
    """The address of a ctypes function (to hand to the core)."""
    return C.cast(fn, vp).value


class Core:
    def __init__(self, name=b"console"):
        lib = self.lib = C.CDLL(LIB)
        for fname, args, res in [
                ("core_open", [C.c_char_p, C.c_char_p], i32), ("core_close", [], None),
                ("core_rate", [], i32), ("core_block", [], i32), ("core_now", [], u64), ("core_cycles", [], C.c_uint), ("core_load", [], f32),
                ("core_add_engine", [vp, vp, i32], i32), ("core_add_module", [vp, vp, vp], i32),
                ("core_source_on", [i32, i32], None), ("core_remove", [i32], None),
                ("core_set_pan", [i32, i32, f32, f32], None), ("core_set_sends", [i32, i32, f32, f32], None),
                ("core_set_gain", [i32, f32], None), ("core_set_master", [f32], None), ("core_slot_insert", [i32, i32, vp, vp], None),
                ("core_set_effects", [vp, vp, vp, vp], None), ("core_set_effect_levels", [f32, f32], None),
                ("core_push", [u64, i32, i32, ip, ip, ip, vp], i32), ("core_events_done", [], u64),
                ("core_read_midi", [C.c_char_p, i32], i32), ("core_send_midi", [C.c_char_p, i32], i32),
                ("core_set_display", [C.c_char_p], None),
                # slots
                ("core_slot", [i32, i32, i32, i32], i32), ("core_slot_clear", [i32], None),
                ("core_slot_lane", [i32, i32, i32], None), ("core_slot_mix", [i32, i32, f32, f32, f32, f32], None),
                ("core_slot_monitor", [i32, f32], None), ("core_slot_effects", [i32, vp, vp], None),
                ("core_input_peaks", [C.POINTER(f32)], i32), ("core_in_channels", [], i32),
                # the tape
                ("core_tape_frames", [C.c_int64], None), ("core_tape_channel", [i32, vp], None),
                ("core_tape_track", [i32, f32, f32, f32, f32, i32, i32], None),
                ("core_tape_arm", [i32, i32, i32, i32], None), ("core_tape_boxes", [i32, vp, i32], None),
                ("core_tape_heard", [i32], None), ("core_tape_undo", [i32, vp], None), ("core_tape_loop", [i32, C.c_int64, C.c_int64], None),
                ("core_tape_punch", [C.c_int64, C.c_int64], None), ("core_tape_overdub", [i32], None),
                ("core_tape_pos", [], C.c_int64), ("core_tape_state", [], i32),
                ("core_tape_recorded", [i32, C.POINTER(C.c_int64), C.POINTER(C.c_int64)], i32),
                ("core_ext_monitor", [C.c_float, i32], None), ("core_capture", [i32], None), ("core_capture_get", [i32, C.POINTER(f32), i32], i32)]:
            f = getattr(lib, fname)
            f.argtypes, f.restype = args, res
        try:                                   # (newer cores: the punch-in effects)
            lib.core_slot_punch.argtypes, lib.core_slot_punch.restype = [i32, vp, i32, i32, vp], None
            lib.core_punch_live.argtypes, lib.core_punch_live.restype = [i32, i32, f32], None
            lib.core_punch_seq.argtypes, lib.core_punch_seq.restype = [ip, ip, ip], None
            self.has_punch = True
        except AttributeError:
            self.has_punch = False
        try:                                   # (newer cores: an insert's wet/dry per instrument)
            lib.core_slot_insert_mix.argtypes, lib.core_slot_insert_mix.restype = [i32, i32, f32], None
        except AttributeError:
            pass
        r = lib.core_open(LIBJACK.encode(), name)
        if r != 0:
            raise RuntimeError({-1: "couldn't load libjack (%s)" % LIBJACK, -2: "libjack is missing functions",
                                -3: "JACK isn't running (is console mode on?)", -4: "couldn't make JACK ports",
                                -5: "couldn't start the JACK client"}.get(r, "error %d" % r))
        self.rate, self.block = lib.core_rate(), lib.core_block()
        self.vol = 0.4
        self.volume(self.vol)               # start quiet: the Move's speaker is loud and nothing else turns it down
        self._keep = []                     # (frame, object): kept alive until the core is past that frame
        self._pushed = 0
        self._lock = threading.Lock()       # pushes come from more than one Python thread
        self._midibuf = C.create_string_buffer(12 * 256)

    def close(self):
        self.lib.core_close()

    # ---- time
    def now(self):
        return self.lib.core_now()

    def cycles(self):
        return self.lib.core_cycles()

    def load(self):
        """JACK's measure of how busy the audio cycle is, in percent."""
        return self.lib.core_load()

    # ---- sources
    def add_engine(self, render, trigger, voices):
        """render(float *out, int n) writing n frames of `voices` interleaved; trigger(voice, velocity)."""
        s = self.lib.core_add_engine(addr(render), addr(trigger), voices)
        if s < 0:
            raise RuntimeError("no room for another source")
        return s

    def add_module(self, sh_render, sh_midi, inst_ptr):
        s = self.lib.core_add_module(addr(sh_render), addr(sh_midi), inst_ptr)
        if s < 0:
            raise RuntimeError("no room for another source")
        return s

    def on(self, s, on=True):
        self.lib.core_source_on(s, 1 if on else 0)

    def remove(self, s):
        """Stops it. Wait for the next cycle (cycles() goes up) before freeing anything it uses."""
        self.lib.core_remove(s)

    def pan(self, s, voice, left, right):
        self.lib.core_set_pan(s, voice, left, right)

    def sends(self, s, voice, rev, dly):
        self.lib.core_set_sends(s, voice, rev, dly)

    def gain(self, s, g):
        self.lib.core_set_gain(s, g)

    def set_slot_insert(self, slot, pos, fn, handle):
        """An instrument's insert effect, 1 or 2 (pos 0 or 1; schwung/insertfx.py): fn(handle, left, right, frames)."""
        try:
            self.lib.core_slot_insert(slot, pos, fn or None, handle or None)
        except AttributeError:
            pass                                    # an older sound core

    def set_slot_insert_mix(self, slot, pos, wet):
        """How much of insert pos (0-3; 2-3 the song's) slot hears, 0-1 (1: all of it, as before)."""
        try:
            self.lib.core_slot_insert_mix(slot, pos, float(wet))
        except AttributeError:
            pass                                    # an older sound core

    def master(self, g):
        self.lib.core_set_master(g)

    def volume(self, v):
        """The volume knob's position 0..1 (squared, as the Pi's headphone level, so it feels even)."""
        self.vol = max(0.0, min(1.0, v))
        self.lib.core_set_master(self.vol * self.vol)
        return self.vol

    def volume_knob(self, value):
        """A turn of the Move's volume knob (CC 79's value): one click = 2%."""
        step = value - 128 if value > 63 else value
        return self.volume(self.vol + step * 0.02)

    def effects(self, rev_process, reverb, dly_process, delay):
        self.lib.core_set_effects(addr(rev_process), reverb, addr(dly_process), delay)

    def effect_levels(self, rev, dly):
        self.lib.core_set_effect_levels(rev, dly)

    # ---- events
    def _push(self, at, kind, src, a=0, b=0, c=0, fn=None, keep=None):
        with self._lock:
            if self.lib.core_push(at or 0, kind, src, a, b, c, fn) != 0:
                return False
            self._pushed += 1
            now = self.lib.core_now()
            if keep is not None:
                # strings an event points at: kept until a while after its frame has gone by
                self._keep.append((max(at or 0, now) + self.rate // 5, keep))
            if self._keep and self._pushed % 64 == 0:
                self._keep = [k for k in self._keep if k[0] >= now]
            return True

    def trigger(self, s, voice, velocity, at=0):
        return self._push(at, EV_TRIGGER, s, voice, velocity)

    def midi(self, s, b0, b1, b2, at=0):
        return self._push(at, EV_MIDI, s, b0, b1, b2)

    def call(self, fn, *args, at=0):
        """fn(*args) in the audio thread, in order with the other events: for changing an instrument's
        settings while it plays. Up to 3 arguments, each an int or bytes (kept alive until used)."""
        vals, keep = [], []
        for a in args:
            if isinstance(a, (bytes, bytearray)):
                buf = C.create_string_buffer(bytes(a))
                keep.append(buf)
                vals.append(C.cast(buf, vp).value)
            else:
                vals.append(int(a))
        vals += [0] * (3 - len(vals))
        return self._push(at, EV_CALL, -1, vals[0], vals[1], vals[2], addr(fn), keep or None)

    # ---- the Move's controls, lights and screen
    def read_midi(self):
        """[(frame, bytes)] for every control message since the last call."""
        out = []
        while True:
            k = self.lib.core_read_midi(self._midibuf, 256)
            raw = self._midibuf.raw
            for i in range(k):
                rec = raw[12 * i:12 * i + 12]
                out.append((int.from_bytes(rec[:8], "little"), rec[8:11]))
            if k < 256:
                return out

    def send_midi(self, msg):
        return self.lib.core_send_midi(bytes(msg), len(msg)) == 0

    def display(self, frame):
        """frame: b"MOVEDISP" + 1024 bytes."""
        self.lib.core_set_display(bytes(frame))

    # ---- instrument slots (see core.c): their recording inputs and how they're heard
    def slot(self, k, seq, live, voices):
        if self.lib.core_slot(k, seq, live, voices) != 0:
            raise RuntimeError("bad slot")

    def slot_clear(self, k):
        self.lib.core_slot_clear(k)

    def slot_lane(self, k, voice, lane):
        self.lib.core_slot_lane(k, voice, lane)

    def slot_mix(self, k, voice, left, right, rev, dly):
        self.lib.core_slot_mix(k, voice, left, right, rev, dly)

    def slot_monitor(self, k, gain):
        """How loud slot k is heard (0: not heard; it still makes its recording inputs)."""
        self.lib.core_slot_monitor(k, gain)

    def slot_punch(self, k, fn, src, stage, h):
        if self.has_punch:
            self.lib.core_slot_punch(k, fn, src, stage, h)

    def punch_live(self, k, fx, fpb):
        if self.has_punch:
            self.lib.core_punch_live(k, int(fx), float(fpb))

    def punch_seq(self, k, fx, fpb, at=0):
        """Slot k's steps' punch-in effect from core frame `at` (0: now)."""
        if not self.has_punch:
            return
        if at:
            self.call(self.lib.core_punch_seq, k, int(fx), int(fpb), at=at)
        else:
            self.lib.core_punch_seq(k, int(fx), int(fpb))

    def slot_effects(self, k, reverb, delay):
        self.lib.core_slot_effects(k, reverb, delay)

    def input_peaks(self):
        """The loudest sample on each input channel since the last call."""
        n = self.lib.core_in_channels()
        buf = (f32 * n)()
        self.lib.core_input_peaks(buf)
        return list(buf)

    # ---- the tape (Python owns its memory: numpy float32 arrays, kept alive while the core has them)
    def tape(self, channels, frames):
        """channels: 16 arrays (or None), track t and its right side t + 8."""
        self._tape_refs = list(channels)
        self.lib.core_tape_frames(0)
        for c, a in enumerate(channels):
            self.lib.core_tape_channel(c, a.ctypes.data if a is not None else None)
        self.lib.core_tape_frames(int(frames))

    def tape_track(self, t, vol, pan, rev, dly, audible, stereo):
        self.lib.core_tape_track(t, vol, pan, rev, dly, 1 if audible else 0, 1 if stereo else 0)

    def ext_monitor(self, gain, stereo):
        self.lib.core_ext_monitor(float(gain), 1 if stereo else 0)

    def tape_arm(self, t, armed, src=(-1, -1)):
        """src: the input channel(s) it records (-1: the mix of every slot's kit)."""
        self.lib.core_tape_arm(t, 1 if armed else 0, int(src[0]), int(src[1]))

    def tape_boxes(self, c, shaped):
        """shaped: [(start, end, gain, fade in, fade out)] in frames, sorted."""
        global BOX
        import numpy as np
        if BOX is None:
            BOX = np.dtype([("a", "<i8"), ("b", "<i8"), ("fi", "<i8"), ("fo", "<i8"), ("g", "<f4"), ("u", "<f4")])
        arr = np.zeros(len(shaped), BOX)
        for i, (a, b, g, fi, fo) in enumerate(shaped):
            arr[i] = (a, b, fi, fo, g, 0.0)
        keep = self.__dict__.setdefault("_box_refs", {}).setdefault(c, [])
        keep.append(arr)
        del keep[:-3]                        # the core may still be reading the one before
        self.lib.core_tape_boxes(c, arr.ctypes.data if len(arr) else None, len(arr))

    def tape_undo(self, c, buf):
        """buf: a float32 array as long as the tape (kept alive by the caller), or None."""
        self.lib.core_tape_undo(c, buf.ctypes.data if buf is not None else None)

    def tape_heard(self, on):
        self.lib.core_tape_heard(1 if on else 0)

    def tape_loop(self, on, a, b):
        self.lib.core_tape_loop(1 if on else 0, int(a), int(b))

    def tape_punch(self, a, b):
        self.lib.core_tape_punch(int(a), int(b))

    def tape_overdub(self, on):
        self.lib.core_tape_overdub(1 if on else 0)

    def transport(self, what, pos=0, at=0):
        """what: T_PLAY (from pos), T_STOP, T_LOCATE (to pos), T_RECORD, T_RECORD_OFF; at: the frame (it
        happens at the start of the cycle that frame is in)."""
        return self._push(at, EV_TRANSPORT, -1, what, int(pos), 0)

    def tape_pos(self):
        return self.lib.core_tape_pos()

    def tape_state(self):
        """(playing, recording)."""
        s = self.lib.core_tape_state()
        return bool(s & 1), bool(s & 2)

    def recorded(self, c):
        """(start, end) recorded on channel c since the last call, or None."""
        a, b = C.c_int64(), C.c_int64()
        return (a.value, b.value) if self.lib.core_tape_recorded(c, C.byref(a), C.byref(b)) else None

    # ---- listening in: what's heard, in four parts (instruments, tape, reverb, delay)
    PARTS = ("instruments", "tape", "reverb", "delay")

    def capture(self, on=True):
        self.lib.core_capture(1 if on else 0)

    def captured(self, part, frames):
        """The last `frames` frames of a part, as a numpy array."""
        import numpy as np
        buf = np.zeros(frames, np.float32)
        n = self.lib.core_capture_get(part, buf.ctypes.data_as(C.POINTER(f32)), frames)
        return buf[:n]

    def describe(self, x):
        """A few numbers about a stretch of sound: loudness, how steady it is (a drone is near 1, drums near 0)
        and its strongest pitch."""
        import numpy as np
        if len(x) < 4096:
            return "too short"
        rms = float(np.sqrt((x ** 2).mean()))
        if rms < 1e-5:
            return "silent"
        env = np.array([np.sqrt((x[i:i + 1024] ** 2).mean()) for i in range(0, len(x) - 1024, 1024)])
        steady = float(np.percentile(env, 20) / max(1e-9, np.percentile(env, 90)))
        seg = x[:min(len(x), 1 << 17)]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1 / self.rate)
        k = int(np.argmax(spec[10:])) + 10
        return "level %6.4f   steady %.2f   strongest pitch %5.0f Hz" % (rms, steady, freqs[k])
