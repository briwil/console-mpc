"""The send effects: a reverb (ported from Mutable Instruments Elements/Rings) and a tape delay.

The sound work happens in fx/fx.c, compiled to fx/libconsolefx.so. setup.sh builds it; if it's
missing (or older than fx.c) this tries to build it with gcc, and if that isn't possible the
effects are simply off and AVAILABLE is False.
"""
import ctypes
import os
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "fx", "fx.c")
LIB = os.path.join(HERE, "fx", "libconsolefx.so")

# Delay times the delay knob steps through, in beats (a beat is a quarter note)
DELAY_TIMES = [("1/16", 0.25), ("1/8T", 1 / 3), ("1/8", 0.5), ("1/8.", 0.75), ("1/4T", 2 / 3),
               ("1/4", 1.0), ("1/4.", 1.5), ("1/2", 2.0)]
DELAY_TIMES.sort(key=lambda t: t[1])
DEFAULTS = {"rev_size": 0.5, "rev_tone": 0.5, "rev_level": 0.8, "rev_width": 1.0,
            "dly_time": "1/8.", "dly_feedback": 0.4, "dly_level": 0.7}
REVERB_MAKEUP = 4.0       # the reverb comes out quieter than it goes in; this brings it up to match
PROBLEM = ""              # why the effects are off, if they are


def _build():
    try:
        r = subprocess.run(["gcc", "-O2", "-shared", "-fPIC", "-o", LIB, SRC, "-lm"],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0, r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def _load():
    global PROBLEM
    stale = os.path.exists(LIB) and os.path.exists(SRC) and os.path.getmtime(SRC) > os.path.getmtime(LIB)
    if not os.path.exists(LIB) or stale:
        ok, err = _build()
        if not ok and not os.path.exists(LIB):
            PROBLEM = "EFFECTS NEED BUILDING: RUN ~/console/pi-app/setup.sh"
            print("Effects: couldn't build fx/libconsolefx.so (%s). Run pi-app/setup.sh." % err)
            return None
    try:
        lib = ctypes.CDLL(LIB)
    except OSError as e:
        PROBLEM = "EFFECTS NEED BUILDING: RUN ~/console/pi-app/setup.sh"
        print("Effects: couldn't load %s: %s" % (LIB, e))
        return None
    f, p, i = ctypes.c_float, ctypes.c_void_p, ctypes.c_int
    fp = ctypes.POINTER(ctypes.c_float)
    for name, args, res in [("rev_new", [f], p), ("rev_free", [p], None), ("rev_clear", [p], None),
                            ("rev_params", [p, f, f, f, f], None), ("rev_room", [p, f], None), ("rev_process", [p, p, p, p, p, i], None),
                            ("dly_new", [f, f], p), ("dly_free", [p], None), ("dly_clear", [p], None),
                            ("dly_params", [p, f, f, f], None), ("dly_process", [p, p, p, p, p, i], None)]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res
    if hasattr(lib, "punch_new"):                     # (an older library has no punch-in effects)
        lib.punch_new.argtypes, lib.punch_new.restype = [f], p
        lib.punch_free.argtypes, lib.punch_free.restype = [p], None
        lib.punch_prepare.argtypes, lib.punch_prepare.restype = [p, i], None
        lib.punch_process.argtypes, lib.punch_process.restype = [p, p, i, i, i, f, ctypes.c_double], i
    if hasattr(lib, "rev_width"):                     # (an older library has no WIDTH: the reverb stays as it was)
        lib.rev_width.argtypes, lib.rev_width.restype = [p, f], None
    return lib


_lib = _load()
AVAILABLE = _lib is not None


class _Effect:
    def __init__(self, handle, process, free):
        self.h, self._process, self._free = handle, process, free

    def process(self, x):
        """x: (frames, 2) float32 send signal -> (frames, 2) wet signal."""
        n = len(x)
        buf = np.empty((4, n), np.float32)            # rows: in left, in right, out left, out right
        buf[0] = x[:, 0]
        buf[1] = x[:, 1]
        if n:
            base = buf.ctypes.data                    # plain addresses (void*): cheaper than ctypes pointers
            step = buf.strides[0]
            self._process(self.h, base, base + step, base + 2 * step, base + 3 * step, n)
        return buf[2:].T                              # (frames, 2) view: no copy

    def __del__(self):
        try:
            if self.h:
                self._free(self.h)
                self.h = None
        except Exception:
            pass


class Reverb(_Effect):
    def __init__(self, rate):
        super().__init__(_lib.rev_new(rate), _lib.rev_process, _lib.rev_free)

    def set(self, size, tone, width=1.0):
        if (size, tone, width) == getattr(self, "_set", None):
            return
        self._set = (size, tone, width)
        if hasattr(_lib, "rev_width"):
            _lib.rev_width(self.h, width)                 # 0 mono .. 1 the reverb's own stereo
        """size and tone 0..1. SIZE sets the room (its lines shrink to an eighth at 0) and the tail
        together: fully down is a small, short room, fully up the Elements hall. Tone as on Elements."""
        _lib.rev_room(self.h, 0.125 + 0.875 * size ** 1.5)
        _lib.rev_params(self.h, 0.2 + 0.68 * size, 0.3 + 0.6 * tone, 0.625, 0.2)

    def clear(self):
        _lib.rev_clear(self.h)


class Delay(_Effect):
    def __init__(self, rate, max_seconds=8.0):
        super().__init__(_lib.dly_new(rate, max_seconds), _lib.dly_process, _lib.dly_free)

    def set(self, samples, feedback, tone=0.55):
        if (samples, feedback, tone) == getattr(self, "_set", None):
            return
        self._set = (samples, feedback, tone)
        _lib.dly_params(self.h, samples, feedback, tone)

    def clear(self):
        _lib.dly_clear(self.h)


def delay_beats(name):
    return dict(DELAY_TIMES).get(name, 0.75)


def step_delay_time(name, delta):
    names = [n for n, _ in DELAY_TIMES]
    i = names.index(name) if name in names else names.index("1/8.")
    return names[max(0, min(len(names) - 1, i + delta))]


PUNCH = AVAILABLE and hasattr(_lib, "punch_new")


class Punch:
    """One instrument's punch-in effect (see punch.py), on its voices, in place."""
    def __init__(self, rate):
        self.h = _lib.punch_new(rate)

    def prepare(self, channels):
        """Make its history for this many channels now (else the first effect does, in the audio thread)."""
        _lib.punch_prepare(self.h, int(channels))

    def process(self, x, fx, frames_per_beat, beat=-1.0):
        """x: (frames, channels) float32, C order: changed in place. Returns True while an effect sounds."""
        if not len(x) or not x.shape[1]:
            return False
        return bool(_lib.punch_process(self.h, x.ctypes.data, len(x), x.shape[1], int(fx),
                                       float(frames_per_beat), float(beat)))

    def __del__(self):
        try:
            if self.h:
                _lib.punch_free(self.h)
                self.h = None
        except Exception:
            pass
