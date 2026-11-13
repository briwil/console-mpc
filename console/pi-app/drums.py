"""The drum synth, one of the console's inputs. Three drum machines, picked per song in SETTINGS:

- LXR-02: the six drum voices of the Erica Synths LXR-02 (its open-source firmware, GPL-3.0). Class LXR.
- TR-606 and TR-808: 6W6 and 8W8 from Schwung (Ableton Move), GPL-3.0, in drums/schwung/. Class Schwung.

Drums (at the bottom) holds the one in use and passes everything to it, so the rest of the app talks to
whichever machine the song has. Each machine has lanes (what the drum keys play: keys 1-8, and with SHIFT
9-16 when a machine has more than 8) and voices (its sounds, each with its settings pages).

The sound engine is the LXR's own code, in drums/lxr/, compiled with the console's glue
(drums/console_drums.c) into drums/libdrums.so. setup.sh builds it; if it's missing or older than the
code, this builds it with gcc, and if that isn't possible the drum synth is simply off (AVAILABLE False).

Lanes (voices): 0-2 DRUM 1-3, 3 SNARE, 4 CYMBAL, 5 HI-HAT. Hitting lane 6 plays the hi-hat open.
"""
import ctypes
import glob
import math
import os
import shutil
import subprocess
import sys
import threading

import numpy as np

import drumparams as dp

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "drums")
LIB = os.path.join(DIR, "libdrums.so")
LIVE_LIB = os.path.join(DIR, "libdrums_live.so")    # a second copy: its own engine, for playing by hand
VOICES = 6
NAMES = ["DRUM 1", "DRUM 2", "DRUM 3", "SNARE", "CYMBAL", "HI-HAT"]
SHORT = ["DR1", "DR2", "DR3", "SN", "CY", "HH"]
OPEN_HAT = 6
VEL_TO_VOLUME = range(137, 143)     # each voice's VEL>VOL setting
PROBLEM = ""              # why the drum synth is off, if it is
LIVE_TAIL = 8 * 44100     # the hand-played copy of an instrument sleeps this long after your last hit (frames)



def stale_copy(src, copy):
    """True if copy (a second copy of a library, for its own engine) isn't the same as src: missing, or a
    different size or time. (Older than wasn't enough: an update brings libraries built earlier than the
    copies made before it, and the old copy then kept running, bugs and all.)"""
    try:
        a, b = os.stat(src), os.stat(copy)
    except OSError:
        return True
    return a.st_size != b.st_size or int(a.st_mtime) != int(b.st_mtime)


def make_copy(src, copy):
    shutil.copy2(src, copy + ".tmp")                 # (copy2: the same time as src, for stale_copy)
    os.replace(copy + ".tmp", copy)

def asleep(machine):
    """True if neither copy of the instrument has anything to sound and nothing is waiting to be done."""
    return machine._seq_left <= 0 and machine._live_left <= 0 and not machine._pending


def seq_awake(machine, frames, busy):
    """The sequencer's copy of an instrument sleeps too, LIVE_TAIL frames after its last note, so an
    instrument with nothing to play costs nothing. busy: it has something to play in this block."""
    if busy:
        machine._seq_left = LIVE_TAIL
    awake = machine._seq_left > 0
    machine._seq_left -= frames
    return awake


def _newest_source():
    files = [f for f in glob.glob(os.path.join(DIR, "**", "*.[ch]"), recursive=True)
             if os.sep + "schwung" + os.sep not in f] + [os.path.join(DIR, "build.sh")]
    return max((os.path.getmtime(f) for f in files), default=0)


def _build():
    try:
        r = subprocess.run(["bash", os.path.join(DIR, "build.sh")], capture_output=True, text=True, timeout=600)
        return r.returncode == 0, r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def _load(path=LIB):
    global PROBLEM
    if path == LIB and (not os.path.exists(LIB) or _newest_source() > os.path.getmtime(LIB)):
        ok, err = _build()
        if not ok and not os.path.exists(LIB):
            PROBLEM = "DRUM SYNTH NEEDS BUILDING: RUN ~/console/pi-app/setup.sh"
            print("Drums: couldn't build drums/libdrums.so (%s). Run pi-app/setup.sh." % err[-500:])
            return None
    if path != LIB:
        # the same library under another name loads as a separate engine with its own settings and voices
        try:
            if stale_copy(LIB, path):
                make_copy(LIB, path)
        except OSError as e:
            print("Drums: couldn't copy the library for a second engine: %s" % e)
            return None
    try:
        lib = ctypes.CDLL(path)
    except OSError as e:
        PROBLEM = "DRUM SYNTH NEEDS BUILDING: RUN ~/console/pi-app/setup.sh"
        print("Drums: couldn't load %s: %s" % (LIB, e))
        return None
    i, v = ctypes.c_int, None
    for name, args, res in [("drums_init", [], i), ("drums_param_count", [], i),
                            ("drums_set_param", [i, i], v), ("drums_get_param", [i], i),
                            ("drums_load_init_kit", [], v), ("drums_set_bpm", [i], v),
                            ("drums_trigger", [i, i], v), ("drums_pan", [i], i),
                            ("drums_render", [ctypes.POINTER(ctypes.c_float), i], v)]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res
    return lib


_lib = _load()
AVAILABLE = _lib is not None
# The sequencer plays _lib; your fingers play _live. Two engines, so the sequencer's hits can be recorded
# exactly on the beat and yours exactly where you pressed (they reach the tape with different delays).
_live = (_load(LIVE_LIB) if AVAILABLE else None) or _lib


class LXR:
    asleep = asleep
    _seq_left = 0           # the same for the sequencer's engine
    _live_left = 0          # frames the hand-played engine still has to sound (see LIVE_TAIL)
    """The LXR-02's drum synth (the library holds a single engine, so make one of these)."""

    id, title = "lxr", "LXR-02"
    voices, channels, lanes = VOICES, VOICES, 7
    names, short = NAMES, SHORT
    lane_voice = [0, 1, 2, 3, 4, 5, 5]          # lane 6 plays the hi-hat open
    lane_short = ["D1", "D2", "D3", "SN", "CY", "HHc", "HHo"]
    lane_names = ["DRUM 1", "DRUM 2", "DRUM 3", "SNARE", "CYMBAL", "CLOSED HAT", "OPEN HAT"]

    def pages(self, voice):
        return dp.PAGES[voice]

    @staticmethod
    def label(param):
        return dp.LABELS.get(param, "?")

    @staticmethod
    def kind(param):
        return dp.KINDS.get(param, ("num",))[0]

    def multi(self, voices):
        """Voices -> its DRUM n input channels (one per drum): the voices as they are."""
        return voices

    def channel_sends(self):
        return self.sends()

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = []         # things to do at the start of the next render, in order
        self._locked = [set() for _ in range(VOICES)]     # parameters the sequencer engine has locked now
        if AVAILABLE:
            _lib.drums_init()
            if _live is not _lib:
                _live.drums_init()
            self.engine_params = _lib.drums_param_count()
        else:
            self.engine_params = 0
        # after the engine's settings come Console's own: each voice's reverb and delay sends
        self.param_count = self.engine_params + (dp.EXTRA_PARAMS if AVAILABLE else 0)
        # what each setting is now, kept here so the screen can read it any time (the engine catches up
        # at the start of its next block); and the LXR's Init Kit, to go back to
        self.values = ([_lib.drums_get_param(i) for i in range(self.engine_params)] + [0] * dp.EXTRA_PARAMS
                       if AVAILABLE else [])
        # Console's starting kit: like the LXR's Init Kit, but with velocity turning the volume up and down
        # on every drum (the LXR's has it off, so velocity would do nothing until you switched it on)
        for p in VEL_TO_VOLUME:
            if p < self.engine_params:
                self.values[p] = 1
        self.init_values = list(self.values)
        with self._lock:
            self._pending.extend(("param", p, 1) for p in VEL_TO_VOLUME if p < self.engine_params)

    # These can be called from any thread: they take effect at the start of the next block of sound.
    def hit(self, lane, velocity=100):
        with self._lock:
            self._pending.append(("hit", lane, velocity))

    def set_param(self, index, value):
        if not 0 <= index < self.param_count:
            return
        value = max(0, min(127, int(value)))
        with self._lock:
            self.values[index] = value
            if index < self.engine_params:
                self._pending.append(("param", index, value))

    def get_param(self, index):
        return self.values[index] if 0 <= index < self.param_count else 0

    def kit(self):
        """The current sound settings, to save in the project."""
        return list(self.values)

    def load_kit(self, values):
        """Settings saved by kit(); missing ones (from an older save) come from the Init Kit."""
        values = [int(v) for v in values[:self.param_count]]
        if len(values) == dp.NOISE_DECAY and len(values) > 56:
            values.append(values[56])                  # saved before the snare noise had its own decay
        values += self.init_values[len(values):]
        with self._lock:
            self.values = values
            self._pending.extend(("param", i, v) for i, v in enumerate(values) if i < self.engine_params)

    def init_kit(self):
        self.load_kit(self.init_values)

    # ------------------------------------------------------------ editing with the knobs

    def target_range(self, param):
        """For a velocity or LFO destination: (first, last) entry of TARGETS it may point at."""
        if dp.KINDS[param] == ("vel_target",):
            voice = param - 149                        # VEL TO params are 149-154, one per voice
        else:
            voice = self.get_param(param - 6) - 1      # the LFO's own voice setting sits 6 below its target
        return dp.VOICE_TARGETS[max(0, min(5, voice))]

    @staticmethod
    def lockable(param):
        """Settings a step can lock: not the velocity and LFO destinations (they pick what's modulated)."""
        return dp.KINDS.get(param, ("num",))[0] in ("num", "pm", "menu", "onoff")

    @staticmethod
    def stepped(param, v, clicks):
        """A lockable setting's value v turned by some clicks."""
        kind = dp.KINDS.get(param, ("num",))
        if kind[0] == "menu":
            return max(0, min(len(dp.MENUS[kind[1]]) - 1, v + (1 if clicks > 0 else -1)))
        if kind[0] == "onoff":
            return 1 if clicks > 0 else 0
        return max(0, min(127, v + clicks))

    def step(self, param, clicks):
        """Turn a setting by some knob clicks. Returns the new value."""
        kind, v = dp.KINDS.get(param, ("num",)), self.get_param(param)
        if kind[0] == "menu":
            v = max(0, min(len(dp.MENUS[kind[1]]) - 1, v + (1 if clicks > 0 else -1)))
        elif kind[0] == "onoff":
            v = 1 if clicks > 0 else 0
        elif kind[0] == "voice":
            old = self.get_param(param + 6)            # keep the LFO's target on the same kind of setting
            first, _ = dp.VOICE_TARGETS[max(0, min(5, v - 1))]
            v = max(1, min(6, v + (1 if clicks > 0 else -1)))
            if old:
                nf, nl = dp.VOICE_TARGETS[v - 1]
                self.set_param(param + 6, min(nl, nf + max(0, old - first)))
        elif kind[0] in ("vel_target", "lfo_target"):
            first, last = self.target_range(param)
            order = [0] + list(range(first, last + 1))     # nothing, then the voice's own settings
            i = order.index(v) if v in order else 0
            v = order[max(0, min(len(order) - 1, i + (1 if clicks > 0 else -1)))]
        else:
            v = max(0, min(127, v + clicks))
        self.set_param(param, v)
        return v

    def value_text(self, param, v=None):
        kind = dp.KINDS.get(param, ("num",))
        v = self.get_param(param) if v is None else v
        if kind[0] == "menu":
            names = dp.MENUS[kind[1]]
            return names[v] if v < len(names) else str(v)
        if kind[0] == "pm":
            return "%+d" % (v - kind[1]) if v != kind[1] else "0"
        if kind[0] == "onoff":
            return "ON" if v else "OFF"
        if kind[0] == "send":
            return "%d%%" % round(v / 127 * 100)
        if kind[0] == "voice":
            return NAMES[max(0, min(5, v - 1))]
        if kind[0] in ("vel_target", "lfo_target"):
            target = dp.TARGETS[v] if v < len(dp.TARGETS) else 0
            if not target:
                return "OFF"
            voice = next((i for i, (a, b) in enumerate(dp.VOICE_TARGETS) if a <= v <= b), None)
            label = dp.LABELS.get(target, "FX %d" % (target - 237))
            return label if voice is None else "%s %s" % (SHORT[voice], label)
        return str(v)

    def fraction(self, param, v=None):
        """How far round the setting is, 0..1, for the screen's bars."""
        kind = dp.KINDS.get(param, ("num",))
        v = self.get_param(param) if v is None else v
        if kind[0] == "menu":
            return v / max(1, len(dp.MENUS[kind[1]]) - 1)
        if kind[0] == "voice":
            return (v - 1) / 5
        if kind[0] in ("vel_target", "lfo_target"):
            return 1.0 if v else 0.0
        return v / 127

    def sends(self):
        """Each voice's reverb and delay sends, 0..1: two arrays of 6."""
        if not AVAILABLE:
            return np.zeros(VOICES, np.float32), np.zeros(VOICES, np.float32)
        rev = np.array([self.values[p] for p in dp.REVERB_SEND], np.float32) / 127
        dly = np.array([self.values[p] for p in dp.DELAY_SEND], np.float32) / 127
        return rev, dly

    def set_bpm(self, bpm):
        with self._lock:
            self._pending.append(("bpm", int(round(bpm))))

    @property
    def two_engines(self):
        return _live is not _lib

    def render(self, frames, events=(), with_live=True):
        """The next frames of sound (audio thread): (sequencer, by hand), each (frames, 6) float32, one mono
        channel per voice. events: the sequencer's hits in this block, [(offset, lane, velocity, locks)].
        With only one engine (the copy failed), everything is in the first and the second is silent."""
        with self._lock:                     # settings changes always; hits by hand only with_live
            todo = [t for t in self._pending if with_live or t[0] != "hit"]
            self._pending = [] if with_live else [t for t in self._pending if t[0] == "hit"]
        seq = np.zeros((frames, VOICES), np.float32)
        live = np.zeros((frames, VOICES), np.float32)
        if not AVAILABLE:
            return seq, live
        engines = (_lib, _live) if self.two_engines else (_lib,)
        for t in todo:
            if t[0] == "hit":
                _live.drums_trigger(t[1], t[2])
                self._live_left = LIVE_TAIL
            elif t[0] == "param":
                for lib in engines:
                    lib.drums_set_param(t[1], t[2])
                self._pans = None
            elif t[0] == "bpm":
                for lib in engines:
                    lib.drums_set_bpm(t[1])
        pos = 0
        ptr = lambda a: a.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        for offset, lane, vel, locks in events:
            if lane >= self.lanes:
                continue                     # a lane another machine used (patterns keep all 16)
            offset = max(pos, min(frames, offset))
            if offset > pos:
                _lib.drums_render(ptr(seq[pos:offset]), offset - pos)
                pos = offset
            self._apply_locks(min(lane, VOICES - 1), locks)
            _lib.drums_trigger(lane, vel)
        if pos < frames and seq_awake(self, frames, bool(events)):
            _lib.drums_render(ptr(seq[pos:]), frames - pos)
        if self.two_engines and with_live and self._live_left > 0:    # asleep until your next hit
            _live.drums_render(ptr(live), frames)
            self._live_left -= frames
        return seq, live

    def _apply_locks(self, voice, locks):
        """Before a sequencer hit: put back the voice's settings the last step locked, then lock this step's."""
        for p in self._locked[voice] - set(locks):
            _lib.drums_set_param(p, self.values[p])
        for p, v in locks.items():
            _lib.drums_set_param(p, v)
        if locks or self._locked[voice]:
            self._pans = None                # a locked pan changes them
        self._locked[voice] = set(locks)

    _pans = None

    def pans(self):
        """Each voice's left and right gain from the kit's pan settings: (6, 2). Kept until a setting changes."""
        if self._pans is not None:
            return self._pans
        g = np.zeros((VOICES, 2), np.float32)
        for v in range(VOICES):
            p = (_lib.drums_pan(v) if AVAILABLE else 64) / 127.0
            g[v] = math.cos(p * math.pi / 2), math.sin(p * math.pi / 2)
        g *= math.sqrt(2)            # centre = 1.0 in each side
        if AVAILABLE:
            self._pans = g
        return g

    def stereo(self, voices):
        """(frames, 6) voices -> (frames, 2), panned the way the kit says."""
        return voices @ self.pans()


# ---------------------------------------------------------------- the TR-606 and TR-808 (Schwung)

SW_DIR = os.path.join(DIR, "schwung")
# lane order: what keys 1-8 play, then with SHIFT 9-16. The common drums are on the first eight.
SPECS = {
    "606": {"title": "TR-606", "header": "606/sd606_params.h", "prefix": "sd606",
            "voices": ["bd", "sd", "lt", "ht", "ch", "oh", "cy", "cp"],
            "lanes": ["bd", "sd", "lt", "ht", "ch", "oh", "cy", "cp"]},
    "808": {"title": "TR-808", "header": "808/w8_params.h", "prefix": "w8",
            "voices": ["bd", "sd", "lt", "mt", "ht", "lc", "mc", "hc", "rs", "cl", "ma", "cp", "cb", "ch", "oh", "cy"],
            "lanes": ["bd", "sd", "lt", "mt", "ht", "cp", "ch", "oh", "lc", "mc", "hc", "rs", "cl", "ma", "cb", "cy"]},
}
# the machines' own effects and master stage aren't used (Console has its own effects and mixes the voices)
SKIP_KEYS = {"master_dist", "master_drive", "comp", "note_map", "ui_focus", "mutes", "rev_decay", "rev_tone",
             "rev_hpf", "rev_level", "dly_time", "dly_fdbk", "dly_tone", "dly_hpf", "dly_level", "dly_bpm"}
LABEL_WORDS = {"Rev": "REVERB", "Dly": "DELAY", "Distortion": "DIST", "Velocity": "VELOCITY"}


def _c_json(path, name):
    """A JSON text the machine's header keeps as a C string (split over many lines)."""
    import json
    import re
    s = open(path).read()
    body = s[s.index(name + "[] ="):]
    pos, parts = body.index("=") + 1, []
    lit = re.compile(r'\s*"((?:[^"\\]|\\.)*)"')
    while True:
        m = lit.match(body, pos)
        if not m:
            break
        parts.append(m.group(1))
        pos = m.end()
    return json.loads("".join(parts).encode().decode("unicode_escape"))


_sw_building = threading.Lock()


def _sw_build(mid):
    """drums/schwung/lib<mid>.so, built with g++ if it's missing or older than its code."""
    with _sw_building:
        return _sw_build_now(mid)


def _sw_build_now(mid):
    lib = os.path.join(SW_DIR, "lib%s.so" % mid)
    srcs = glob.glob(os.path.join(SW_DIR, mid, "*")) + glob.glob(os.path.join(SW_DIR, "glue*"))
    newest = max((os.path.getmtime(f) for f in srcs), default=0)
    if os.path.exists(lib) and os.path.getmtime(lib) >= newest:
        return lib
    if not shutil.which("g++"):
        return lib if os.path.exists(lib) else None      # the Move: GitHub builds them (an update brings them)
    try:
        r = subprocess.run(["g++", "-O2", "-shared", "-fPIC", "-w", "-o", lib + ".tmp",
                            os.path.join(SW_DIR, "glue%s.cpp" % mid)], capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            os.replace(lib + ".tmp", lib)
        else:
            print("Drums: couldn't build the %s (%s)" % (mid, r.stderr.strip()[-400:]))
    except (OSError, subprocess.SubprocessError) as e:
        print("Drums: couldn't build the %s (%s)" % (mid, e))
    return lib if os.path.exists(lib) else None


def _sw_load(path):
    try:
        lib = ctypes.CDLL(path)
    except OSError as e:
        print("Drums: couldn't load %s: %s" % (path, e))
        return None
    i, v, s = ctypes.c_int, None, ctypes.c_char_p
    for name, args, res in [("sw_init", [ctypes.c_float], i), ("sw_voices", [], i), ("sw_set", [s, i], v),
                            ("sw_get", [s], i), ("sw_trigger", [i, i], v),
                            ("sw_render", [ctypes.POINTER(ctypes.c_float), i], v)]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res
    return lib


class Schwung:
    asleep = asleep
    _live_left = 0
    _seq_left = 0
    """The TR-606 (6W6) or TR-808 (8W8), each voice coming out on its own (see drums/schwung/glue*.cpp)."""

    channels = 8                     # DRUM 1-8 inputs: lanes 1-8; with 16, lanes 9-16 share them

    def __init__(self, mid):
        spec = SPECS[mid]
        self.id, self.title = mid, spec["title"]
        lib = _sw_build(mid)
        self.available = False
        self._lib = _sw_load(lib) if lib else None
        live_path = lib[:-3] + "_live.so" if lib else None
        if self._lib and live_path:
            try:
                if stale_copy(lib, live_path):
                    make_copy(lib, live_path)
            except OSError:
                live_path = None
        self._live = (_sw_load(live_path) if live_path else None) or self._lib
        if not self._lib:
            return
        self.voices = self._lib.sw_init(44100.0)
        if self._live is not self._lib:
            self._live.sw_init(44100.0)
        self.available = self.voices == len(spec["voices"])
        # the settings, from the machine's own tables
        header = os.path.join(SW_DIR, spec["header"])
        chain = _c_json(header, spec["prefix"] + "_chain_params_json")
        levels = _c_json(header, spec["prefix"] + "_ui_pages_json")["levels"]
        info = {p["key"]: p for p in chain}
        self.params = []             # [{key, label, kind, count/options, default, voice}]
        self.index = {}
        def add(key, label, voice):
            p = info[key]
            entry = {"key": key, "label": LABEL_WORDS.get(label, label).upper(), "voice": voice,
                     "kind": "menu" if p["type"] == "enum" else "num",
                     "options": [o.upper() for o in p.get("options", [])], "default": int(p.get("default", 0))}
            self.index[key] = len(self.params)
            self.params.append(entry)
        self._pages = []
        self.names = []
        for v, vk in enumerate(spec["voices"]):
            lvl = levels[vk]
            self.names.append(lvl["name"].upper())
            labels = {q["key"]: q["label"] for q in lvl["params"] if "key" in q}
            for key in lvl["knobs"]:
                if key not in self.index and key not in SKIP_KEYS:
                    add(key, labels.get(key, key), v)
        root_labels = {q["key"]: q["label"] for q in levels["root"]["params"] if "key" in q}
        kit_keys = [k for k in ("volume", "vel_depth", "hh_choke") if k in info]
        for key in kit_keys:
            if key not in self.index:
                add(key, root_labels.get(key, key), None)
        # (volume, velocity depth and choke keep their defaults: no page of their own. Each drum's LEVEL
        # sets its loudness, velocity always counts fully, and CHOKE is on the closed hat's page.)
        for v, vk in enumerate(spec["voices"]):
            knobs = [self.index[k] for k in levels[vk]["knobs"] if k in self.index]
            self._pages.append([("SOUND", knobs)])
        self.short = [vk.upper() for vk in spec["voices"]]
        self.lane_voice = [spec["voices"].index(k) for k in spec["lanes"]]
        self.lanes = len(self.lane_voice)
        self.lane_short = [self.short[v] for v in self.lane_voice]
        self.lane_names = [self.names[v] for v in self.lane_voice]
        self.param_count = self.engine_params = len(self.params)
        self.init_values = [p["default"] for p in self.params]
        self.values = list(self.init_values)
        self._send_keys = [(self.index.get(vk + "_rev"), self.index.get(vk + "_dly")) for vk in spec["voices"]]
        self._lock = threading.Lock()
        self._pending = []
        self._locked = [set() for _ in range(self.voices)]
        self.load_kit(self.init_values)

    # ------------------------------------------------------------ what the screens ask
    def pages(self, voice):
        return self._pages[voice]

    def label(self, param):
        return self.params[param]["label"] if 0 <= param < len(self.params) else "?"

    def kind(self, param):
        return self.params[param]["kind"] if 0 <= param < len(self.params) else "num"

    def value_text(self, param, v=None):
        v = self.get_param(param) if v is None else v
        p = self.params[param]
        if p["kind"] == "menu":
            return p["options"][v] if 0 <= v < len(p["options"]) else str(v)
        return str(v)

    def fraction(self, param, v=None):
        v = self.get_param(param) if v is None else v
        p = self.params[param]
        if p["kind"] == "menu":
            return v / max(1, len(p["options"]) - 1)
        return v / 127

    @staticmethod
    def lockable(param):
        return True

    def stepped(self, param, v, clicks):
        p = self.params[param]
        if p["kind"] == "menu":
            return max(0, min(len(p["options"]) - 1, v + (1 if clicks > 0 else -1)))
        return max(0, min(127, v + clicks))

    def step(self, param, clicks):
        v = self.stepped(param, self.get_param(param), clicks)
        self.set_param(param, v)
        return v

    # ------------------------------------------------------------ settings
    def set_param(self, index, value):
        if not 0 <= index < self.param_count:
            return
        top = len(self.params[index]["options"]) - 1 if self.params[index]["kind"] == "menu" else 127
        value = max(0, min(top, int(value)))
        with self._lock:
            self.values[index] = value
            self._pending.append(("param", index, value))

    def get_param(self, index):
        return self.values[index] if 0 <= index < self.param_count else 0

    def kit(self):
        return list(self.values)

    def load_kit(self, values):
        values = [int(v) for v in list(values)[:self.param_count]]
        values += self.init_values[len(values):]
        with self._lock:
            self.values = values
            self._pending.extend(("param", i, v) for i, v in enumerate(values))

    def init_kit(self):
        self.load_kit(self.init_values)

    def sends(self):
        """Each voice's reverb and delay sends (its REVERB and DELAY knobs), 0..1."""
        rev = np.array([self.values[r] if r is not None else 0 for r, _ in self._send_keys], np.float32) / 127
        dly = np.array([self.values[d] if d is not None else 0 for _, d in self._send_keys], np.float32) / 127
        return rev, dly

    def channel_sends(self):
        rev, dly = self.sends()
        first = [self.lane_voice[c] for c in range(min(self.channels, self.lanes))]
        return rev[first], dly[first]

    def set_bpm(self, bpm):
        pass                         # nothing here follows the tempo (their delays aren't used)

    # ------------------------------------------------------------ sound
    def hit(self, lane, velocity=100):
        with self._lock:
            self._pending.append(("hit", lane, velocity))

    @property
    def two_engines(self):
        return self._live is not self._lib

    def _set(self, lib, index, value):
        lib.sw_set(self.params[index]["key"].encode(), int(value))

    def render(self, frames, events=(), with_live=True):
        """As LXR.render: (sequencer, by hand), each (frames, voices)."""
        with self._lock:                     # settings changes always; hits by hand only with_live
            todo = [t for t in self._pending if with_live or t[0] != "hit"]
            self._pending = [] if with_live else [t for t in self._pending if t[0] == "hit"]
        seq = np.zeros((frames, self.voices), np.float32)
        live = np.zeros((frames, self.voices), np.float32)
        engines = (self._lib, self._live) if self.two_engines else (self._lib,)
        for t in todo:
            if t[0] == "hit":
                if 0 <= t[1] < self.lanes:
                    self._live.sw_trigger(self.lane_voice[t[1]], t[2])
                    self._live_left = LIVE_TAIL
            elif t[0] == "param":
                for lib in engines:
                    self._set(lib, t[1], t[2])
        pos = 0
        ptr = lambda a: a.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        for offset, lane, vel, locks in events:
            if not 0 <= lane < self.lanes:
                continue
            offset = max(pos, min(frames, offset))
            if offset > pos:
                self._lib.sw_render(ptr(seq[pos:offset]), offset - pos)
                pos = offset
            voice = self.lane_voice[lane]
            for p in self._locked[voice] - set(locks):
                self._set(self._lib, p, self.values[p])
            for p, v in locks.items():
                if 0 <= p < self.param_count:
                    self._set(self._lib, p, v)
            self._locked[voice] = set(p for p in locks if 0 <= p < self.param_count)
            self._lib.sw_trigger(voice, vel)
        if pos < frames and seq_awake(self, frames, bool(events)):
            self._lib.sw_render(ptr(seq[pos:]), frames - pos)
        if self.two_engines and with_live and self._live_left > 0:
            self._live.sw_render(ptr(live), frames)
            self._live_left -= frames
        return seq, live

    def pans(self):
        return np.ones((self.voices, 2), np.float32)          # these machines are mono: every voice centred

    def stereo(self, voices):
        return voices @ self.pans()

    def multi(self, voices):
        """Voices -> the 8 DRUM n input channels: lane n (and with SHIFT, lane n + 8) on channel n."""
        out = np.zeros((len(voices), self.channels), np.float32)
        for lane, v in enumerate(self.lane_voice):
            out[:, lane % self.channels] += voices[:, v]
        return out


# ---------------------------------------------------------------- the Machinedrum (OP-XY-MNMD)

MD_DIR = os.path.join(DIR, "md")
MD_PER_LANE = 12                     # MACHINE, the 8 controls, LEVEL, REVERB, DELAY
MD_MACHINE, MD_LEVEL, MD_REV, MD_DLY = 0, 9, 10, 11
_md_building = threading.Lock()


def _md_build():
    """drums/md/libmd.so, built with g++ if it's missing or older than its code."""
    with _md_building:
        lib = os.path.join(MD_DIR, "libmd.so")
        srcs = glob.glob(os.path.join(MD_DIR, "*.*")) + glob.glob(os.path.join(MD_DIR, "vendor", "*.hpp"))
        newest = max((os.path.getmtime(f) for f in srcs if not f.endswith(".so")), default=0)
        if os.path.exists(lib) and os.path.getmtime(lib) >= newest:
            return lib
        if not shutil.which("g++"):
            return lib if os.path.exists(lib) else None  # the Move: GitHub builds it (an update brings it)
        try:
            r = subprocess.run(["g++", "-O2", "-std=c++11", "-shared", "-fPIC", "-w", "-I" + os.path.join(MD_DIR, "vendor"),
                                "-I" + MD_DIR, "-o", lib + ".tmp", os.path.join(MD_DIR, "glue_md.cpp")],
                               capture_output=True, text=True, timeout=600)
            if r.returncode == 0:
                os.replace(lib + ".tmp", lib)
            else:
                print("Drums: couldn't build the Machinedrum (%s)" % r.stderr.strip()[-400:])
        except (OSError, subprocess.SubprocessError) as e:
            print("Drums: couldn't build the Machinedrum (%s)" % e)
        return lib if os.path.exists(lib) else None


def _md_load(path):
    try:
        lib = ctypes.CDLL(path)
    except OSError as e:
        print("Drums: couldn't load %s: %s" % (path, e))
        return None
    i, v, s = ctypes.c_int, None, ctypes.c_char_p
    for name, args, res in [("sw_init", [ctypes.c_float], i), ("sw_voices", [], i), ("sw_trigger", [i, i], v),
                            ("sw_render", [ctypes.POINTER(ctypes.c_float), i], v), ("md_set", [i, i, i], v),
                            ("md_count", [], i), ("md_name", [i], s), ("md_short", [i], s), ("md_label", [i, i], s),
                            ("md_default", [i, i], i), ("md_kit_machine", [i], i), ("md_kit_value", [i, i], i),
                            ("md_kit_role", [i], s)]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res
    return lib


class Machinedrum(Schwung):
    """The Elektron Machinedrum, as OP-XY-MNMD wrote its sounds from scratch (drums/md, MIT): 16 lanes, each
    any TRX, EFM, P-I or GND machine with that machine's eight controls, starting as the Machinedrum's own
    default kit (BD SD HT MT LT CP RS CB CH OH RC CC M1-M4). Each lane is one voice, as on the original.

    Settings: each lane has 12, at lane * 12: MACHINE, the machine's 8 controls (labelled as its page on the
    original; a machine with fewer leaves the rest unused), LEVEL, REVERB and DELAY. Changing the machine
    puts its controls at its own defaults. Everything else (hits, locks, the two engines) is as the 606/808."""

    def __init__(self):
        self.id, self.title = "md", "MACHINEDRUM"
        self.available = False
        lib = _md_build()
        self._lib = _md_load(lib) if lib else None
        live_path = lib[:-3] + "_live.so" if lib else None
        if self._lib and live_path:
            try:
                if stale_copy(lib, live_path):
                    make_copy(lib, live_path)
            except OSError:
                live_path = None
        self._live = (_md_load(live_path) if live_path else None) or self._lib
        if not self._lib:
            return
        L = self._lib
        self.voices = L.sw_init(44100.0)
        if self._live is not L:
            self._live.sw_init(44100.0)
        self.available = self.voices == 16
        n = L.md_count()
        self.machines = [L.md_name(m).decode() for m in range(n)]
        self._short = [L.md_short(m).decode() for m in range(n)]
        self._labels = [[L.md_label(m, s).decode() for s in range(8)] for m in range(n)]
        self._defaults = [[L.md_default(m, s) for s in range(8)] for m in range(n)]
        self.roles = [L.md_kit_role(lane).decode() for lane in range(self.voices)]
        self.params = []
        for lane in range(self.voices):
            self.params.append({"key": "machine", "label": "MACHINE", "voice": lane, "kind": "menu",
                                "options": self.machines, "default": L.md_kit_machine(lane)})
            for s in range(8):
                self.params.append({"key": "c%d" % s, "label": "", "voice": lane, "kind": "num", "options": [],
                                    "default": L.md_kit_value(lane, s)})
            for key, label, default in (("level", "LEVEL", 100), ("rev", "REVERB", 0), ("dly", "DELAY", 0)):
                self.params.append({"key": key, "label": label, "voice": lane, "kind": "num", "options": [],
                                    "default": default})
        self.index = {}
        self.lane_voice = list(range(self.voices))
        self.lanes = self.voices
        self.param_count = self.engine_params = len(self.params)
        self.init_values = [p["default"] for p in self.params]
        self.values = list(self.init_values)
        self._send_keys = [(lane * MD_PER_LANE + MD_REV, lane * MD_PER_LANE + MD_DLY) for lane in range(self.voices)]
        self._lock = threading.Lock()
        self._pending = []
        self._locked = [set() for _ in range(self.voices)]
        self.load_kit(self.init_values)

    # ------------------------------------------------------------ names follow each lane's machine
    def machine_of(self, lane):
        return max(0, min(len(self.machines) - 1, self.values[lane * MD_PER_LANE + MD_MACHINE]))

    @property
    def names(self):
        return [self.machines[self.machine_of(v)] for v in range(self.voices)]

    @property
    def short(self):
        """Each lane's tag: the kit's name for it (HT, MT, LT, RC, CC, M1...) while it has the kit's machine,
        else its machine's (BD, XT, CY...)."""
        kit = self.init_values
        return [self.roles[v] if self.machine_of(v) == kit[v * MD_PER_LANE + MD_MACHINE]
                else self._short[self.machine_of(v)] for v in range(self.voices)]

    lane_names = names
    lane_short = short

    def pages(self, voice):
        base = voice * MD_PER_LANE
        labels = self._labels[self.machine_of(voice)]
        sound = [base + 1 + s for s in range(8) if labels[s]]
        return [("SOUND", sound), ("MACHINE", [base + MD_MACHINE, base + MD_LEVEL, base + MD_REV, base + MD_DLY])]

    def label(self, param):
        if not 0 <= param < self.param_count:
            return "?"
        lane, k = divmod(param, MD_PER_LANE)
        if 1 <= k <= 8:
            return self._labels[self.machine_of(lane)][k - 1] or "-"
        return self.params[param]["label"]

    @staticmethod
    def lockable(param):
        return param % MD_PER_LANE != MD_MACHINE        # a step can't change the machine, only its settings

    # ------------------------------------------------------------ settings
    def set_param(self, index, value):
        if not 0 <= index < self.param_count:
            return
        lane, k = divmod(index, MD_PER_LANE)
        if k != MD_MACHINE:
            super().set_param(index, value)
            return
        m = max(0, min(len(self.machines) - 1, int(value)))
        with self._lock:
            changed = m != self.values[index]
            self.values[index] = m
            self._pending.append(("param", index, m))
            if changed:                                     # a new machine starts from its own settings
                for s in range(8):
                    self.values[index + 1 + s] = self._defaults[m][s]
                    self._pending.append(("param", index + 1 + s, self._defaults[m][s]))

    def load_kit(self, values):
        values = [int(v) for v in list(values)[:self.param_count]]
        values += self.init_values[len(values):]
        with self._lock:
            self.values = values
            # each lane's machine first, then its settings
            order = sorted(range(len(values)), key=lambda i: i % MD_PER_LANE != MD_MACHINE)
            self._pending.extend(("param", i, values[i]) for i in order)

    def _set(self, lib, index, value):
        lane, k = divmod(index, MD_PER_LANE)
        if k == MD_MACHINE:
            lib.md_set(lane, 8, int(value))
        elif 1 <= k <= 8:
            lib.md_set(lane, k - 1, int(value))
        elif k == MD_LEVEL:
            lib.md_set(lane, 9, int(value))
        # REVERB and DELAY are Console's sends, read by sends()

    def multi(self, voices):
        """Voices -> the 8 DRUM n input channels: lane n and lane n + 8 on channel n."""
        out = np.zeros((len(voices), self.channels), np.float32)
        for lane in range(self.lanes):
            out[:, lane % self.channels] += voices[:, lane]
        return out


MACHINES = [("lxr", "LXR-02"), ("606", "TR-606"), ("808", "TR-808"), ("md", "MACHINEDRUM")]


def _prebuild():
    """At start-up, build the 606 and 808 in the background if they need it (setup.sh normally has), so
    picking one in SETTINGS doesn't wait for the compiler."""
    for mid in SPECS:
        _sw_build(mid)
    _md_build()
    if schwung_modules:
        schwung_modules.build_missing()      # the Schwung modules (fetched from GitHub the first time)


# ---------------------------------------------------------------- Schwung modules (schwung/)

try:
    sys.path.insert(0, os.path.join(os.path.dirname(DIR), "schwung"))
    import modules as schwung_modules
except Exception as _e:                      # carry on without them
    print("Drums: no Schwung modules: %s" % _e)
    schwung_modules = None

threading.Thread(target=_prebuild, daemon=True, name="drum builds").start()


class Drums:
    """The song's drum machines. Everything is passed on to the one being edited (use() picks it); get()
    gives any of them (each instrument slot plays its own)."""

    def __init__(self, machine="lxr"):
        self.__dict__["_machines"] = {}
        self.__dict__["m"] = None
        self.__dict__["saved_kits"] = {}       # {machine: kit} from the song, for machines not started yet
        if not self.use(machine):
            self.use("lxr")

    def get(self, machine):
        """A machine ("lxr", "606", "808", "md"), started if it isn't yet, without switching to it (each
        instrument slot plays its own). None if it isn't there (not built or not working)."""
        ms = self._machines
        if machine not in ms:
            print("instrument: starting %s" % machine, flush=True)   # (in the crash log, if starting it crashes)
            try:
                if schwung_modules and machine in schwung_modules.catalog.BY_ID:
                    ms[machine] = schwung_modules.make(machine)       # a Schwung module (schwung/)
                else:
                    ms[machine] = (LXR() if machine == "lxr" else Machinedrum() if machine == "md"
                                   else _sampler() if machine == "sampler" else Schwung(machine))
            except Exception as e:
                print("Drums: the %s isn't available: %s" % (machine, e))
                return None
            if machine != "lxr" and not ms[machine].available:
                del ms[machine]
                return None
            if machine in self.saved_kits:
                ms[machine].load_kit(self.saved_kits[machine])
        return ms[machine]

    def use(self, machine):
        """Switch to a machine: the one the drum and sequencer pages show. Returns True if it's there."""
        m = self.get(machine)
        if m is None:
            return False
        self.__dict__["m"] = m
        return True

    def restore(self, machine, kits, kit=None):
        """Opening a song: its machine, every machine's kit as the song left it (the Init Kit if it has none)
        and kit for the song's own machine (older songs only have that one)."""
        kits = dict(kits or {})
        if kit is not None:
            kits[machine] = kit
        self.__dict__["saved_kits"] = kits
        for mid, m in self._machines.items():
            if mid in kits:
                m.load_kit(kits[mid])
            else:
                m.init_kit()
        return self.use(machine) or self.use("lxr")

    def is_init_kit(self, machine, kit):
        """Whether kit (saved for machine) is that machine's Init Kit (False if it can't tell)."""
        m = self._machines.get(machine)
        if m is None:
            return not kit
        if not kit:
            return True
        values = [int(v) for v in list(kit)[:m.param_count]]
        if machine == "lxr" and len(values) == dp.NOISE_DECAY and len(values) > 56:
            values.append(values[56])
        values += m.init_values[len(values):]
        return values == m.init_values

    @property
    def machine(self):
        return self.m.id

    def machine_kits(self):
        """{machine: kit} for every machine used so far (saved with the song)."""
        return {k: m.kit() for k, m in self._machines.items()}

    def __getattr__(self, name):
        return getattr(self.__dict__["m"], name)

    def __setattr__(self, name, value):
        setattr(self.m, name, value)


def _sampler():
    import sampler
    return sampler.Sampler()


def available_machines():
    """[(id, title)] of the machines that can run here."""
    out = [("lxr", "LXR-02")] if AVAILABLE else []
    if os.path.exists(os.path.join(DIR, "sampler", "libsampler.so")):
        out.append(("sampler", "SAMPLER"))
    for mid, spec in SPECS.items():
        lib = os.path.join(SW_DIR, "lib%s.so" % mid)
        if os.path.exists(lib) or os.path.exists(os.path.join(SW_DIR, "glue%s.cpp" % mid)):
            out.append((mid, spec["title"]))
    if os.path.exists(os.path.join(MD_DIR, "libmd.so")) or os.path.exists(os.path.join(MD_DIR, "glue_md.cpp")):
        out.append(("md", "MACHINEDRUM"))
    if schwung_modules:                      # Schwung modules built by schwung/build.py
        out += [(mid, schwung_modules.catalog.BY_ID[mid]["title"]) for mid in schwung_modules.built_ids()]
    return out
