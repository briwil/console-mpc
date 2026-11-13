"""The SAMPLER: a drum machine of 16 samples, one per drum, each loaded from the Move's sample folders (or any
folder in CONSOLE_SAMPLES, colon separated). Nothing to build: it is plain numpy, so it works anywhere.

Each drum has 8 settings: SAMPLE (the file), LEVEL, PITCH (0.5 semitone a click, 64 = as recorded), START (where in
the sample it begins), DECAY (127: the whole sample; lower: faded out sooner), PAN, REVERB and DELAY; and after
all of those (so older songs and presets still line up) a second sample (SAMPLE 2) and BLEND for each drum:
0 only the first sample, 64 both at full volume, 127 only the second. Pitch, start, decay etc. are shared.
After those: RANDOM (on: each hit plays one of up to five samples at random, BLEND off) and SAMPLES 3-5 (only
heard with RANDOM on).
It looks like the other drum machines to the rest of the app (drums.py's Drums class).

A song keeps a sample as its place in the sorted list of files, so adding or removing samples can change which
one a drum points at (the list is sorted by path: put new samples in a new folder to keep the old order).
"""
import ctypes
import glob
import os
import shutil
import struct
import threading

import numpy as np

RATE = 44100
LANES = 16
PER = 8                                   # settings per drum
KEYS = ["sample", "level", "pitch", "start", "decay", "pan", "reverb", "delay"]
LABELS = ["SAMPLE", "LEVEL", "PITCH", "START", "DECAY", "PAN", "REVERB", "DELAY"]
DEFAULTS = [0, 100, 64, 0, 127, 64, 0, 0]
SAMPLE2 = LANES * PER                     # settings 128-143: each drum's second sample
BLEND = SAMPLE2 + LANES                   # settings 144-159: each drum's BLEND
RANDOM = BLEND + LANES                    # settings 160-175: each drum's RANDOM (0 off, 1 on)
SAMPLE3 = RANDOM + LANES                  # settings 176-223: each drum's samples 3, 4 and 5 (RANDOM's)
ALL = SAMPLE3 + 3 * LANES
SAMPLES = 5                               # a drum's samples with RANDOM on (2 with it off)
SOLO = 10000                              # (not a setting: the browser's preview, only one sample heard)


def sample_param(voice, which=0):
    """The setting that holds drum voice's sample which (0-4)."""
    if which == 0:
        return voice * PER
    if which == 1:
        return SAMPLE2 + voice
    return SAMPLE3 + (which - 2) * LANES + voice


def is_sample(param):
    return (param < SAMPLE2 and param % PER == 0) or SAMPLE2 <= param < BLEND or SAMPLE3 <= param < ALL


def sample_slot(param):
    """(drum, which sample 0-4) for a sample setting."""
    if param < SAMPLE2:
        return param // PER, 0
    if param < BLEND:
        return param - SAMPLE2, 1
    w, v = divmod(param - SAMPLE3, LANES)
    return v, w + 2
MAX_SECONDS = 12
MAX_FILES = 4000
LIVE_TAIL = RATE * 4
DEFAULT_DIRS = ["/data/UserData/UserLibrary/Samples", "/data/UserData/console/samples",
                os.path.expanduser("~/console-samples")]


def lib_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "drums", "sampler", "libsampler.so")


def _load(path):
    if not path or not os.path.exists(path):
        return None
    try:
        lib = ctypes.CDLL(path)
    except OSError as e:
        print("Sampler: couldn't load %s: %s" % (path, e))
        return None
    i, v, c = ctypes.c_int, None, ctypes.c_char_p
    for name, args, res in [("sw_init", [ctypes.c_float], i), ("sw_voices", [], i), ("sw_set", [c, i], v),
                            ("sw_get", [c], i), ("sw_trigger", [i, i], v), ("sw_load", [i, ctypes.c_void_p, i], v),
                            ("sw_render", [ctypes.POINTER(ctypes.c_float), i], v)]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res
    return lib


def sample_dirs():
    env = os.environ.get("CONSOLE_SAMPLES")
    return [d for d in (env.split(":") if env else DEFAULT_DIRS) if d]


def list_samples(exts=("wav", "aif", "aiff")):
    """The sample files (paths) in the sample folders: the .wav files sorted first (so a song's places in the list
    stay as they were), then the other kinds in exts, sorted. Hidden files and folders are left out."""
    found = {}
    for d in sample_dirs():
        for root, dirs, names in os.walk(d):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for n in names:
                ext = n.rsplit(".", 1)[-1].lower() if "." in n and not n.startswith(".") else ""
                if ext in exts:
                    found.setdefault(ext == "wav", set()).add(os.path.join(root, n))
    return (sorted(found.get(True, ())) + sorted(found.get(False, ())))[:MAX_FILES]


def _aiff(data):
    """(float32 samples, channels, rate) of an AIFF / AIFC file (uncompressed, 8-32 bit, or 32-bit float), or None."""
    pos, comm, raw, ctype = 12, None, None, b"NONE"
    aifc = data[8:12] == b"AIFC"
    while pos + 8 <= len(data):
        tag, size = data[pos:pos + 4], struct.unpack(">I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if tag == b"COMM":
            ch, _frames, bits = struct.unpack(">hIh", body[:8])
            exp, hi, lo = struct.unpack(">HII", body[8:18])               # (an 80-bit float: the rate)
            rate = ((hi << 32) | lo) * 2.0 ** ((exp & 0x7FFF) - 16383 - 63)
            if aifc and len(body) >= 22:
                ctype = body[18:22]
            comm = (ch, bits, rate)
        elif tag == b"SSND":
            raw = body[8 + struct.unpack(">I", body[:4])[0]:]
        pos += 8 + size + (size & 1)
    if comm is None or raw is None:
        return None
    ch, bits, rate = comm
    little = ctype == b"sowt"                                               # (little-endian 16 bit, from Macs)
    if ctype in (b"fl32", b"FL32") and bits == 32:
        x = np.frombuffer(raw[:len(raw) // 4 * 4], ">f4").astype(np.float32)
    elif ctype not in (b"NONE", b"sowt", b"twos", b"in24", b"in32", b"raw "):
        return None                                                         # (u-law, MP4... not read)
    elif bits == 8:
        x = np.frombuffer(raw, np.int8).astype(np.float32) / 128
    elif bits == 16:
        x = np.frombuffer(raw[:len(raw) // 2 * 2], "<i2" if little else ">i2").astype(np.float32) / 32768
    elif bits == 24:
        b = np.frombuffer(raw[:len(raw) // 3 * 3], np.uint8).reshape(-1, 3).astype(np.int32)
        v = (b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) if little else ((b[:, 0] << 16) | (b[:, 1] << 8) | b[:, 2])
        x = np.where(v >= 1 << 23, v - (1 << 24), v).astype(np.float32) / (1 << 23)
    elif bits == 32:
        x = np.frombuffer(raw[:len(raw) // 4 * 4], "<i4" if little else ">i4").astype(np.float32) / (1 << 31)
    else:
        return None
    return x, max(1, ch), rate


def read_wav(path):
    """(mono float32 samples at RATE) or None. Reads PCM 8/16/24/32 and float32 WAVs, any rate."""
    try:
        data = open(path, "rb").read()
        if data[:4] == b"FORM" and data[8:12] in (b"AIFF", b"AIFC"):
            got = _aiff(data)
            if got is None:
                return None
            x, ch, rate = got
            x = x[:len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
            if rate != RATE and rate > 0:
                n = int(len(x) * RATE / rate)
                x = np.interp(np.linspace(0, len(x) - 1, max(1, n)), np.arange(len(x)), x).astype(np.float32)
            return np.ascontiguousarray(x[:RATE * MAX_SECONDS], np.float32)
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return None
        pos, fmt, raw = 12, None, None
        while pos + 8 <= len(data):
            tag, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
            body = data[pos + 8:pos + 8 + size]
            if tag == b"fmt ":
                fmt = struct.unpack("<HHIIHH", body[:16])
                if fmt[0] == 0xFFFE and len(body) >= 26:
                    fmt = (struct.unpack("<H", body[24:26])[0],) + fmt[1:]
            elif tag == b"data":
                raw = body
                break
            pos += 8 + size + (size & 1)
        if fmt is None or raw is None:
            return None
        tag, ch, rate, _br, _ba, bits = fmt
        ch = max(1, ch)
        if tag == 3 and bits == 32:
            x = np.frombuffer(raw[:len(raw) // 4 * 4], "<f4").astype(np.float32)
        elif tag == 1 and bits == 16:
            x = np.frombuffer(raw[:len(raw) // 2 * 2], "<i2").astype(np.float32) / 32768
        elif tag == 1 and bits == 8:
            x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
        elif tag == 1 and bits == 24:
            b = np.frombuffer(raw[:len(raw) // 3 * 3], np.uint8).reshape(-1, 3).astype(np.int32)
            v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            x = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / (1 << 23)
        elif tag == 1 and bits == 32:
            x = np.frombuffer(raw[:len(raw) // 4 * 4], "<i4").astype(np.float32) / (1 << 31)
        else:
            return None
        x = x[:len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
        if rate != RATE and rate > 0:
            n = int(len(x) * RATE / rate)
            x = np.interp(np.linspace(0, len(x) - 1, max(1, n)), np.arange(len(x)), x).astype(np.float32)
        return np.ascontiguousarray(x[:RATE * MAX_SECONDS], np.float32)
    except (OSError, ValueError, struct.error):
        return None


class Sampler:
    id = "sampler"
    title = "SAMPLER"
    channels = 8
    voices = LANES
    lanes = LANES

    def __init__(self):
        self.files = list_samples()
        self.available = False
        self._lib = _load(lib_path())
        if not self._lib:
            return
        live = lib_path()[:-3] + "_live.so"
        try:
            shutil.copy2(lib_path(), live + ".tmp")
            os.replace(live + ".tmp", live)
        except OSError:
            live = None
        self._live = (_load(live) if live else None) or self._lib
        self._lib.sw_init(float(RATE))
        if self._live is not self._lib:
            self._live.sw_init(float(RATE))
        self.available = True
        self._cache = {}
        self.params = [{"key": "%s%d" % (KEYS[i % PER], i // PER + 1), "label": LABELS[i % PER],
                        "voice": i // PER, "kind": "menu" if i % PER == 0 else "num"} for i in range(LANES * PER)]
        self.params += [{"key": "sample2_%d" % (v + 1), "label": "SAMPLE 2", "voice": v, "kind": "menu"}
                        for v in range(LANES)]
        self.params += [{"key": "blend%d" % (v + 1), "label": "BLEND", "voice": v, "kind": "num"} for v in range(LANES)]
        self.params += [{"key": "random%d" % (v + 1), "label": "RANDOM", "voice": v, "kind": "menu"} for v in range(LANES)]
        self.params += [{"key": "sample%d_%d" % (w + 3, v + 1), "label": "SAMPLE %d" % (w + 3), "voice": v,
                         "kind": "menu"} for w in range(3) for v in range(LANES)]
        self.param_count = self.engine_params = len(self.params)
        self.init_values = [DEFAULTS[i % PER] for i in range(LANES * PER)] + [0] * (ALL - SAMPLE2)
        self.values = list(self.init_values)
        self.lane_voice = list(range(LANES))
        self.fast_params = {i * PER for i in range(LANES)} | set(range(SAMPLE2, BLEND)) | set(range(SAMPLE3, ALL))
        self._send_keys = [(v * PER + 6, v * PER + 7) for v in range(LANES)]
        self._lock = threading.Lock()
        self._pending = []
        self._locked = [set() for _ in range(LANES)]
        self.load_kit(self.init_values)

    # ------------------------------------------------------------ names
    def random_on(self, v):
        return bool(self.values[RANDOM + v])

    def sample_name(self, v, which=None):
        """The drum's sample name (which None: the first one set)."""
        order = (which,) if which is not None else range(SAMPLES if self.random_on(v) else 2)
        for w in order:
            i = self.values[sample_param(v, w)]
            if 0 < i <= len(self.files):
                return os.path.splitext(os.path.basename(self.files[i - 1]))[0].upper()
        return "EMPTY"

    @property
    def names(self):
        return [self.sample_name(v) for v in range(LANES)]

    @property
    def lane_names(self):
        return self.names

    @property
    def short(self):
        return [n[:4] for n in self.names]

    @property
    def lane_short(self):
        return [str(v + 1) for v in range(LANES)]

    def problem(self):
        return "" if self.files else "NO SAMPLES: PUT .WAV FILES IN THE MOVE'S SAMPLES"

    # ------------------------------------------------------------ what the screens ask
    def pages(self, voice):
        v = max(0, min(LANES - 1, voice))
        return [("SOUND", [v * PER + k for k in range(1, PER)] + [BLEND + v])]   # (the samples: push the wheel)

    def label(self, param):
        return self.params[param]["label"] if 0 <= param < len(self.params) else "?"

    def kind(self, param):
        return self.params[param]["kind"] if 0 <= param < len(self.params) else "num"

    def _top(self, param):
        if RANDOM <= param < SAMPLE3:
            return 1
        return len(self.files) if is_sample(param) else 127

    def value_text(self, param, v=None):
        v = self.get_param(param) if v is None else v
        if RANDOM <= param < SAMPLE3:
            return "ON" if v else "OFF"
        if BLEND <= param < RANDOM:                   # BLEND: which sample, and how loud the other one is
            if self.random_on(param - BLEND):
                return "OFF (RANDOM)"
            if v == 0:
                return "S1"
            if v == 127:
                return "S2"
            if v == 64:
                return "BOTH"
            return ("S2 %d%%" % round(v / 64 * 100)) if v < 64 else ("S1 %d%%" % round((127 - v) / 63 * 100))
        k = 0 if is_sample(param) else param % PER
        if k == 0:
            if 0 < v <= len(self.files):
                return os.path.splitext(os.path.basename(self.files[v - 1]))[0].upper()
            return "EMPTY"
        if k == 2:
            return "%+.1f" % ((v - 64) / 2)
        if k == 5:
            return "C" if v == 64 else ("L%d" % (64 - v) if v < 64 else "R%d" % (v - 64))
        if k in (6, 7):
            return "%d%%" % round(v / 127 * 100)
        return str(v)

    def fraction(self, param, v=None):
        v = self.get_param(param) if v is None else v
        return v / max(1, self._top(param))

    @staticmethod
    def lockable(param):
        if param >= SAMPLE2:
            return BLEND <= param < RANDOM            # BLEND can be locked on a step (the samples, RANDOM can't)
        return 1 <= param % PER <= 4                  # level, pitch, start, decay (not the sample, pan or sends)

    def stepped(self, param, v, clicks):
        return max(0, min(self._top(param), v + clicks))

    def step(self, param, clicks):
        v = self.stepped(param, self.get_param(param), clicks)
        self.set_param(param, v)
        return v

    def set_param(self, index, value):
        if not 0 <= index < self.param_count:
            return
        value = max(0, min(self._top(index), int(value)))
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
            self.values = [max(0, min(self._top(i), v)) for i, v in enumerate(values)]
            self._pending.extend(("param", i, v) for i, v in enumerate(self.values))

    def init_kit(self):
        self.load_kit(self.init_values)

    def sends(self):
        rev = np.array([self.values[r] for r, _ in self._send_keys], np.float32) / 127
        dly = np.array([self.values[d] for _, d in self._send_keys], np.float32) / 127
        return rev, dly

    def channel_sends(self):
        rev, dly = self.sends()
        return rev[:self.channels], dly[:self.channels]

    def set_bpm(self, bpm):
        pass

    _seq_left = _live_left = 0

    # ------------------------------------------------------------ sound
    def solo(self, v, which):
        """The sample browser's preview: hear only sample which (0-4) of drum v; None: all again."""
        with self._lock:
            self._pending.append(("param", SOLO + v, 0 if which is None else which + 1))

    def hit(self, lane, velocity=100):
        with self._lock:
            self._pending.append(("hit", lane, velocity))

    def _sample(self, index):
        if not 0 < index <= len(self.files):
            return None
        if index not in self._cache:
            if len(self._cache) > 48:
                used = set(self.values[0:SAMPLE2:PER]) | set(self.values[SAMPLE2:BLEND]) | set(self.values[SAMPLE3:ALL])
                self._cache = {k: v for k, v in self._cache.items() if k in used}
            self._cache[index] = read_wav(self.files[index - 1])
        return self._cache[index]

    def _set(self, lib, index, value):
        """One setting into a copy of the engine (lib: the library, or a stand-in that queues the call for the
        sound core)."""
        if index >= SOLO:
            lib.sw_set(("solo%d" % (index - SOLO + 1)).encode(), int(value))
            return
        if BLEND <= index < RANDOM:
            lib.sw_set(("blend%d" % (index - BLEND + 1)).encode(), int(value))
            return
        if RANDOM <= index < SAMPLE3:
            lib.sw_set(("random%d" % (index - RANDOM + 1)).encode(), int(value))
            return
        if is_sample(index):
            v, w = sample_slot(index)
            k, slot = 0, w * LANES + v                    # (the engine's 0-15 first samples, 16-31 second... 64-79)
        else:
            v, k = divmod(index, PER)
            slot = v
        if k == 0:
            x = self._sample(int(value))
            if x is None or not len(x):
                lib.sw_load(slot, 0, 0)
            else:
                lib.sw_load(slot, int(x.ctypes.data), len(x))     # (the cache keeps x alive)
        elif k <= 4:
            lib.sw_set(("%s%d" % (KEYS[k], v + 1)).encode(), int(value))

    def render(self, frames, events=(), with_live=True):
        """Not used: the sound core plays this machine through its library (see core/instruments.py)."""
        z = np.zeros((frames, LANES), np.float32)
        return z, z.copy()

    def pans(self):
        p = np.zeros((LANES, 2), np.float32)
        for v in range(LANES):
            a = self.values[v * PER + 5] / 127 * (np.pi / 2)
            p[v] = (np.cos(a) * 1.4142, np.sin(a) * 1.4142)
        return p * 0.7071

    def stereo(self, voices):
        return voices @ self.pans()

    def multi(self, voices):
        out = np.zeros((len(voices), self.channels), np.float32)
        for lane in range(LANES):
            out[:, lane % self.channels] += voices[:, lane]
        return out
