"""Schwung sound generators as Console instruments (drums.py's machines: same methods, same pages).

A module (built by build.py into schwung/modules/<id>/) is loaded twice through libschwunghost.so: one copy
for the sequencer and one for your hits by hand, like the other drum machines (the sequencer's sound is
made ahead of time; your hits are made now). Each copy is its own dsp.so file, so a module that keeps its
engine in globals still gets two.

Settings: whatever the module lists in chain_params (asked for at start, else module.json). A setting
named pad3_..., v3_..., pv3_... (or, from catalog.py, a drum's prefix like bd_) belongs to drum 3; the
rest are the kit's. Each drum's own settings make its SOUND pages; the kit's come after, in the module's
own page order where it has one. Values are kept as knob positions (0..steps), as the other machines
keep 0..127, and sent to the module as text.

All talking to a module happens in the audio thread (render), as the plugin API asks: changes wait in
_pending until then.
"""
import math
import ctypes
import json
import os
import re
import shutil
import threading

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(HERE, "modules")
HOST_LIB = os.path.join(HERE, "libschwunghost.so")
import catalog  # noqa: E402  (schwung/ is on sys.path: drums.py puts it there)

FIRST_PAD = catalog.FIRST_PAD
VOICE_KEY = re.compile(r"^(pad|pv|v)(\d+)_(.+)$")
SKIP = {"focused_voice", "state", "kit_query", "note_map", "mutes", "octave_transpose"}   # not knobs: they'd
                                    # change which pad is which, or are the module's own bookkeeping
MAX_STEPS = 200                     # a float setting gets at most this many knob positions
_host = None
_host_lock = threading.Lock()


def host():
    global _host
    with _host_lock:
        if _host is None and os.path.exists(HOST_LIB):
            try:
                h = ctypes.CDLL(HOST_LIB)
            except OSError as e:
                print("Schwung host: %s" % e)
                return None
            vp, cp, i = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
            for name, args, res in [("sh_open", [cp, cp, cp], vp), ("sh_error", [], cp), ("sh_close", [vp], None),
                                    ("sh_midi", [vp, i, i, i], None), ("sh_set", [vp, cp, cp], None),
                                    ("sh_get", [vp, cp, cp, i], i), ("sh_bpm", [ctypes.c_float], None),
                                    ("sh_render", [vp, ctypes.POINTER(ctypes.c_float), i], None),
                                    ("sh_module_error", [vp, cp, i], i),
                                    ("sh_fx_open", [cp, cp, cp], vp), ("sh_fx_close", [vp], None),
                                    ("sh_fx_set", [vp, cp, cp], None), ("sh_fx_get", [vp, cp, cp, i], i),
                                    ("sh_fx_midi", [vp, i, i, i], None),
                                    ("sh_fx_process", [vp, ctypes.POINTER(ctypes.c_float),
                                                       ctypes.POINTER(ctypes.c_float), i], None)]:
                fn = getattr(h, name, None)
                if fn is None:                     # an older host library without the effect functions: the synths still work
                    continue
                fn.argtypes, fn.restype = args, res
            _host = h
        return _host


building = False                    # True while build_missing() is at work


def build_missing():
    """Build any module that isn't built yet (or whose version catalog.py changed), at low priority, so
    the app can carry on. Each one is fetched from GitHub the first time, so it needs the internet."""
    global building
    import subprocess
    import build as builder
    if all(builder.built(m) for m in catalog.MODULES) and os.path.exists(HOST_LIB):
        return
    import shutil
    if not shutil.which("nice"):
        return                       # the Move: its modules come ready-made with the update (GitHub builds them)
    building = True
    try:
        subprocess.run(["nice", "-n", "19", "python3", os.path.join(HERE, "build.py")],
                       capture_output=True, timeout=3 * 3600)
    except (OSError, subprocess.SubprocessError) as e:
        print("Schwung modules: %s" % e)
    finally:
        building = False


def built_ids():
    """The modules that are built here, in catalog order."""
    return [m["id"] for m in catalog.MODULES
            if os.path.exists(os.path.join(MODULES_DIR, m["id"], "dsp.so"))]


class Instance:
    """One running copy of a module."""

    def __init__(self, dsp, folder, defaults):
        h = host()
        if h is None:
            raise RuntimeError("the Schwung host isn't built (run setup.sh)")
        self.h = h
        self.ptr = h.sh_open(dsp.encode(), folder.encode(), json.dumps(defaults or {}).encode())
        if not self.ptr:
            raise RuntimeError((h.sh_error() or b"couldn't start").decode(errors="replace"))
        self._buf = ctypes.create_string_buffer(1 << 16)

    def get(self, key, big=False):
        buf = ctypes.create_string_buffer(1 << 20) if big else self._buf
        r = self.h.sh_get(self.ptr, key.encode(), buf, len(buf))
        return buf.value.decode(errors="replace") if r >= 0 else None

    def error(self):
        """What the module says is wrong (no ROM...), or ""."""
        buf = ctypes.create_string_buffer(512)
        self.h.sh_module_error(self.ptr, buf, len(buf))
        return buf.value.decode(errors="replace").strip()

    def set(self, key, value):
        self.h.sh_set(self.ptr, key.encode(), str(value).encode())

    def midi(self, b0, b1, b2):
        self.h.sh_midi(self.ptr, b0, b1, b2)

    def render(self, out):
        """out: (frames, 2) float32, C-contiguous."""
        self.h.sh_render(self.ptr, out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(out))


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


LIVE_TAIL = 8 * 44100      # the hand-played copy sleeps this long (frames) after your last hit or key


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


class Module:
    asleep = asleep
    _live_left = 0
    _seq_left = 0
    """A Schwung drum machine, with the methods drums.py's machines have."""

    channels = 8                     # DRUM 1-8 inputs (these modules only give stereo: they stay empty)

    def __init__(self, mid):
        spec = catalog.BY_ID[mid]
        self.id, self.title, self.spec = mid, spec["title"], spec
        self.available = False
        folder = os.path.join(MODULES_DIR, mid)
        dsp = os.path.join(folder, "dsp.so")
        info = json.load(open(os.path.join(folder, "module.json")))
        defaults = info.get("defaults") or {}
        self._seq = Instance(dsp, folder, defaults)
        live = os.path.join(folder, "dsp_live.so")
        try:
            if spec.get("one_copy"):
                raise RuntimeError("one copy")
            import drums as _drums
            if _drums.stale_copy(dsp, live):
                _drums.make_copy(dsp, live)
            self._live = Instance(live, folder, defaults)
        except (OSError, RuntimeError):
            self._live = self._seq                    # one copy: your hits are made ahead too
        self._lock = threading.Lock()
        self._pending = []
        self._offs = []                               # notes to let go at the start of the next block
        self.fx_sends = [0, 0]                        # its sends to the shared REVERB and DELAY (0-127; the SENDS page)
        self._read_settings(info)
        self.available = True

    # ------------------------------------------------------------ what it has
    def _read_settings(self, info):
        s = self._seq
        caps = info.get("capabilities") or {}
        try:
            chain = json.loads(s.get("chain_params", big=True) or "null") or caps.get("chain_params") or []
        except ValueError:
            chain = caps.get("chain_params") or []
        try:
            ui = json.loads(s.get("ui_hierarchy", big=True) or "null") or caps.get("ui_hierarchy") or {}
        except ValueError:
            ui = caps.get("ui_hierarchy") or {}
        if not chain:
            # some modules only describe their settings in their pages (Hush One)
            levels = list((ui.get("levels") or {}).values()) + \
                list(((caps.get("ui_hierarchy") or {}).get("levels") or {}).values())
            for lvl in levels:
                for p in lvl.get("params") or []:
                    if isinstance(p, dict) and p.get("key") and p.get("type"):
                        q = dict(p)
                        q["name"] = p.get("label") or p.get("name") or p["key"]
                        if "max_param" in p and "max" not in p:
                            n = _number(s.get(p["max_param"]))
                            q["max"] = max(0, (n or 1) - 1)
                        if p["key"] not in {c.get("key") for c in chain}:
                            chain.append(q)
        list_skip = set()
        self.preset_info = None                       # the preset list (and banks) the module says it has
        levels_all = list((ui.get("levels") or {}).values()) + list(((caps.get("ui_hierarchy") or {}).get("levels") or {}).values())
        for lvl in levels_all:
            if lvl.get("list_param") in ("preset", "patch") and lvl.get("count_param") and self.preset_info is None:
                self.preset_info = {"list": lvl["list_param"], "count": lvl.get("count_param"),
                                    "name": lvl.get("name_param")}
        for lvl in levels_all:
            if self.preset_info is not None and lvl.get("items_param") and lvl.get("select_param"):
                self.preset_info.update(items=lvl["items_param"], select=lvl["select_param"])
                break
        # a preset / kit list the module says the length of (OB-Xd: 0-9999 in chain_params, but 128 real presets)
        for lvl in list((ui.get("levels") or {}).values()) + list(((caps.get("ui_hierarchy") or {}).get("levels") or {}).values()):
            lp, cp = lvl.get("list_param"), lvl.get("count_param")
            n = _number(s.get(cp)) if cp else None
            if lp:
                for k in (cp, lvl.get("name_param")):
                    if k:
                        list_skip.add(k)             # the count and name are read-outs, not knobs
                for c in chain:
                    if c.get("key") == lp and c.get("type", "float") in ("int", "float"):
                        if n and n >= 1:
                            c["min"], c["max"] = 0, int(n) - 1
                        elif _number(c.get("max")) is None:
                            continue
                        c["step"], c["type"], c["list"] = 1, "int", True
                        if c.get("access") == "write":
                            c.pop("access")          # (Amino's preset is write-only, but it is the knob we want)
        prefixes = self.spec.get("voice_prefixes")
        self.params = []                              # {key, label, kind, options, lo, hi, steps, voice}
        voices = set()
        for p in chain:
            key = p.get("key")
            if not key or p.get("access") == "write" or key.startswith(("ui_", "cv_", "midi")) \
                    or key in SKIP or key in list_skip or key in self.spec.get("skip", ()):
                continue
            voice, label = None, p.get("name") or key
            m = VOICE_KEY.match(key)
            if m:
                voice = int(m.group(2)) - 1
                label = re.sub(r"^(pad|pv|v)\s*\d+\s*", "", label, flags=re.I) or m.group(3)
            elif prefixes:
                head = key.split("_")[0]
                if head in prefixes:
                    voice = prefixes.index(head)
                    label = re.sub(r"^%s\s+" % re.escape(head), "", label, flags=re.I)
            kind = p.get("type", "float")
            entry = {"key": key, "label": label.replace("_", " ").upper()[:12], "voice": voice, "unit": p.get("unit", "")}
            if kind == "enum":
                opts = [str(o) for o in p.get("options") or []]
                if not opts:
                    continue
                entry.update(kind="menu", options=[o.upper() for o in opts], raw=opts, steps=len(opts) - 1)
            else:
                lo, hi = _number(p.get("min")), _number(p.get("max"))
                if lo is None or hi is None or hi <= lo:
                    lo, hi = 0.0, 1.0
                if kind == "int" and lo == 0 and hi == 1:     # a switch (OB-Xd's OSC1 SAW): OFF / ON
                    entry.update(kind="menu", options=["OFF", "ON"], raw=["0", "1"], steps=1)
                elif kind == "int":
                    steps = int(hi - lo)
                    entry.update(kind="num", int=True, lo=lo, hi=hi, steps=max(1, steps), one=bool(p.get("list")))
                    if lo > 0 and hi / lo >= 100:             # a frequency (20-20000): even steps by octave, not by Hz
                        entry.update(log=True, steps=127)
                else:
                    step = _number(p.get("step")) or 0
                    steps = int(round((hi - lo) / step)) if step > 0 else 127
                    entry.update(kind="num", int=False, lo=lo, hi=hi, steps=max(1, min(MAX_STEPS, steps)))
            if voice is not None:
                voices.add(voice)
            self.params.append(entry)
        self.sample_param_index, self.files = None, []
        sk = self.spec.get("sample_key")
        if sk:                                        # a one-sample instrument (MrSample): its sample is a file in the
            try:                                      # Move's samples (index 1.. = files[0..], 0 = none), as the drum sampler's
                import sampler
                files = sampler.list_samples(("wav", "mp3", "flac", "aif", "aiff"))      # (it reads them all itself)
            except Exception:                         # noqa: BLE001
                files = []
            entry = next((p for p in self.params if p["key"] == sk), None)
            if entry is None:
                entry = {"key": sk, "voice": None, "unit": ""}
                self.params.append(entry)
            entry.update(label="SAMPLE", kind="menu", int=False, raw=[""] + files, steps=len(files),
                         options=["-"] + [os.path.splitext(os.path.basename(f))[0].upper() for f in files])
            self.files, self.sample_param_index = files, self.params.index(entry)
        self.index = {p["key"]: i for i, p in enumerate(self.params)}
        # the drums: 16 pads (fewer if the module says), each on a voice
        nv = max(voices) + 1 if voices else 1
        names = self.spec.get("pads")
        if not names:
            try:
                split = json.loads(s.get("split_voices") or "null") or []
                names = [v.get("label", "") for v in split] if len(split) >= 8 else None
            except ValueError:
                names = None
        if not names:
            for lvl in (ui.get("levels") or {}).values():
                if lvl.get("child_names"):
                    names = lvl["child_names"]
                    break
        self.lanes = min(16, self.spec.get("lanes", 16))
        self.voices = max(nv, self.lanes)
        self.lane_voice = list(range(self.lanes))
        self._param_voice = lambda lane: lane % nv
        self.names = [(names[i] if names and i < len(names) and names[i] else "PAD %d" % (i + 1)).upper()
                      for i in range(self.voices)]
        self.short = [re.sub(r"[^A-Z0-9]", "", n)[:4] or str(i + 1) for i, n in enumerate(self.names)]
        self.lane_names = self.names[:self.lanes]
        for p in self.params:                         # "KICK TUNE" on the kick's page is just TUNE
            v = p["voice"]
            if v is not None and v < len(self.names) and p["label"].startswith(self.names[v] + " "):
                p["label"] = p["label"][len(self.names[v]) + 1:]
        self.lane_short = self.short[:self.lanes]
        # pages: each drum's own settings, 8 to a page, then the kit's
        per = {}
        for i, p in enumerate(self.params):
            if p["voice"] is not None:
                per.setdefault(p["voice"], []).append(i)
        self._voice_pages = {}
        for v, idx in per.items():
            chunks = [idx[k:k + 8] for k in range(0, len(idx), 8)]
            self._voice_pages[v] = [("SOUND" if k == 0 else "SOUND %d" % (k + 1), c) for k, c in enumerate(chunks)]
        kit = [i for i, p in enumerate(self.params) if p["voice"] is None]
        self._kit_pages, used = [], set()
        for name, lvl in (ui.get("levels") or {}).items():
            knobs = lvl.get("knobs") or [p["key"] for p in lvl.get("params") or []
                                         if isinstance(p, dict) and p.get("key")]
            if lvl.get("child_count") or not knobs:
                continue
            idx = [self.index[k] for k in knobs if k in self.index and self.index[k] in kit
                   and self.index[k] not in used]
            if idx:
                used |= set(idx)
                label = (lvl.get("name") or lvl.get("label") or name).upper().replace("_", " ")
                for k in range(0, len(idx), 8):
                    page = ("KIT" if name == "root" else label[:10]) if k == 0 else "%s %d" % (label[:8], k // 8 + 1)
                    self._kit_pages.append((page, idx[k:k + 8]))
        rest = [i for i in kit if i not in used]
        for k in range(0, len(rest), 8):
            self._kit_pages.append(("MORE" if self._kit_pages or k else "KIT", rest[k:k + 8]))
        self.param_count = self.engine_params = len(self.params)
        self.values = [self._position(i, s.get(p["key"])) for i, p in enumerate(self.params)]
        self.init_values = list(self.values)
        self._locked = [set() for _ in range(self.lanes)]

    def _position(self, i, text):
        """A setting's text (from the module) as a knob position."""
        p = self.params[i]
        if p["kind"] == "menu":
            if text in p["raw"]:
                return p["raw"].index(text)
            n = _number(text)
            return max(0, min(p["steps"], int(n))) if n is not None else 0
        n = _number(text)
        if n is None:
            return 0
        if p.get("log"):
            n = max(p["lo"], min(p["hi"], n))
            f = math.log(n / p["lo"]) / math.log(p["hi"] / p["lo"])
        else:
            f = (n - p["lo"]) / (p["hi"] - p["lo"])
        return max(0, min(p["steps"], int(round(f * p["steps"]))))

    @staticmethod
    def _at(p, pos):
        """The setting's value at a knob position (log for frequencies)."""
        if p.get("log"):
            return p["lo"] * (p["hi"] / p["lo"]) ** (pos / p["steps"])
        return p["lo"] + (p["hi"] - p["lo"]) * pos / p["steps"]

    def _text(self, i, pos):
        """A knob position as the text the module takes."""
        p = self.params[i]
        if p["kind"] == "menu":
            return p["raw"][max(0, min(p["steps"], pos))]
        v = self._at(p, pos)
        return str(int(round(v))) if p["int"] else "%.4f" % v

    def problem(self):
        """The module's own complaint, for the screen (e.g. JE-8086 without its ROM), or ""."""
        return self._seq.error()

    # ------------------------------------------------------------ what the screens ask
    def pages(self, voice):
        own = self._voice_pages.get(self._param_voice(voice), [])
        return (own + self._kit_pages) or [("KIT", [])]

    def label(self, param):
        return self.params[param]["label"] if 0 <= param < len(self.params) else "?"

    def kind(self, param):
        return self.params[param]["kind"] if 0 <= param < len(self.params) else "num"

    def value_text(self, param, v=None):
        v = self.get_param(param) if v is None else v
        p = self.params[param]
        if p["kind"] == "menu":
            return p["options"][max(0, min(p["steps"], v))]
        x = self._at(p, v)
        unit = p.get("unit") or ""
        if p["int"]:
            return "%d%s" % (round(x), (" " + unit.upper()) if unit else "")
        if p["lo"] == 0 and p["hi"] == 1:
            return "%d%%" % round(x * 100)
        return ("%.2f" % x if abs(x) < 10 else "%.1f" % x if abs(x) < 100 else "%d" % round(x)) + \
            ((" " + unit.upper()) if unit else "")

    def fraction(self, param, v=None):
        v = self.get_param(param) if v is None else v
        return v / max(1, self.params[param]["steps"])

    @staticmethod
    def lockable(param):
        return True

    def stepped(self, param, v, clicks):
        p = self.params[param]
        if p["kind"] == "menu":
            return max(0, min(p["steps"], v + (1 if clicks > 0 else -1)))
        # about 128 clicks end to end, whatever the range (a click is one step on short ones)
        per = 1 if p.get("one") else max(1, p["steps"] // 128)
        return max(0, min(p["steps"], v + clicks * per))

    def step(self, param, clicks):
        v = self.stepped(param, self.get_param(param), clicks)
        self.set_param(param, v)
        return v

    # ------------------------------------------------------------ settings
    def set_param(self, index, value):
        if not 0 <= index < self.param_count:
            return
        value = max(0, min(self.params[index]["steps"], int(value)))
        with self._lock:
            if value == self.values[index]:
                return                    # (a knob turned on past the end: sending it again crashed Noisemaker)
            self.values[index] = value
            if self.params[index]["key"] in self.spec.get("quiet_first", ()):
                self._pending.append(("all_off",))    # this setting can't change under sounding notes
            self._pending.append(("param", index, value))
            p = self.params[index]
            if p["voice"] is None and (p["kind"] == "menu" or p.get("int")):
                self._pending.append(("refresh",))     # a kit or preset choice changes the rest

    def get_param(self, index):
        return self.values[index] if 0 <= index < self.param_count else 0

    # ------------------------------------------------------------ the module's own presets (the PRESETS page)
    def has_presets(self):
        if self.preset_info is None and "preset" in self.index:
            p = self.params[self.index["preset"]]
            if p.get("kind") == "menu" and len(p.get("options") or []) > 2:
                self.preset_info = {"list": "preset", "count": None, "name": None, "menu": True}   # names in the menu
            elif p.get("int"):
                self.preset_info = {"list": "preset", "count": None, "name": None}     # a preset knob, no names
        return self.preset_info is not None

    def preset_param(self):
        pi = self.preset_info
        return self.index.get(pi["list"]) if pi else None

    def set_preset(self, n):
        """The module's own preset n (the rest of the settings follow it)."""
        pi = self.preset_info
        if not pi:
            return
        i = self.preset_param()
        if pi.get("menu"):
            self.set_param(i, n)
            return
        with self._lock:
            if i is not None:
                self.values[i] = n
            self._pending.append(("raw", pi["list"], str(int(n))))
            self._pending.append(("refresh",))

    def preset_now(self):
        pi = self.preset_info
        if pi and pi.get("menu"):
            return self.values[self.preset_param()]
        n = _number(self._seq.get(pi["list"])) if pi else None
        if n is None and pi and self.preset_param() is not None:
            n = self.values[self.preset_param()]
        return int(n or 0)

    def preset_count(self):
        pi = self.preset_info
        if not pi:
            return 0
        if pi.get("menu"):
            return len(self.params[self.preset_param()]["options"])
        n = _number(self._seq.get(pi["count"])) if pi.get("count") else None
        i = self.preset_param()
        if n is None and i is not None:
            n = self.params[i]["steps"] + 1
        n = int(n or 0)
        if i is not None and n >= 1:
            self.params[i]["steps"] = max(1, n - 1)  # (a bank change changes how many there are)
        return n

    def preset_name(self):
        pi = self.preset_info
        if pi and pi.get("menu"):
            opts = self.params[self.preset_param()]["options"]
            n = self.values[self.preset_param()]
            return opts[n].title() if 0 <= n < len(opts) else None
        name = self._seq.get(pi["name"]) if pi and pi.get("name") else None
        return (name or "").strip() or None

    def banks(self):
        """[(label, index)] of the module's banks, or []."""
        pi = self.preset_info
        if not pi or not pi.get("items"):
            return []
        try:
            items = json.loads(self._seq.get(pi["items"], big=True) or "[]")
        except ValueError:
            return []
        out = []
        for n, it in enumerate(items if isinstance(items, list) else []):
            if isinstance(it, dict):
                out.append((str(it.get("label") or it.get("name") or n + 1), int(_number(it.get("index")) if it.get("index") is not None else n)))
            else:
                out.append((str(it), n))
        return out

    def bank(self):
        pi = self.preset_info
        n = _number(self._seq.get(pi["select"])) if pi and pi.get("select") else None
        return int(n or 0)

    def set_bank(self, index):
        pi = self.preset_info
        if pi and pi.get("select"):
            with self._lock:
                self._pending.append(("all_off",))
                self._pending.append(("raw", pi["select"], str(int(index))))
                self._pending.append(("refresh",))

    # kept after the module's own settings in kit(): SENDS_MARK, reverb, delay (an older kit just hasn't got them)
    SENDS_MARK = -9

    def kit(self):
        return list(self.values) + [self.SENDS_MARK] + list(self.fx_sends)

    def set_send(self, kind, value):
        self.fx_sends[0 if kind == "reverb" else 1] = max(0, min(127, int(value)))
        with self._lock:
            self._pending.append(("mix",))          # (the core picks the sends up after its next pending batch)

    def load_kit(self, values):
        values = list(values)
        if len(values) >= 3 and values[-3] == self.SENDS_MARK:
            self.fx_sends = [max(0, min(127, int(v))) for v in values[-2:]]
            values = values[:-3]
        else:
            self.fx_sends = [0, 0]
        values = [int(v) for v in list(values)[:self.param_count]]
        values += self.init_values[len(values):]
        with self._lock:
            self.values = values
            self._pending.extend(("param", i, v) for i, v in enumerate(values))

    def hear(self, note=60):
        """The sample browser's preview for a one-sample instrument: a note, let go a moment later."""
        with self._lock:
            self._pending.append(("on", note, 100))

        def off():
            with self._lock:
                self._pending.append(("off", note))
        t = threading.Timer(0.8, off)
        t.daemon = True
        t.start()

    def init_kit(self):
        self.load_kit(self.init_values)

    def sends(self):
        """Its sends to the shared REVERB and DELAY (the SENDS page), on its stereo output (voices 0 and 1)."""
        r, d = np.zeros(self.voices, np.float32), np.zeros(self.voices, np.float32)
        r[:2], d[:2] = self.fx_sends[0] / 127, self.fx_sends[1] / 127
        return r, d

    def channel_sends(self):
        z = np.zeros(self.channels, np.float32)
        return z, z

    def set_bpm(self, bpm):
        h = host()
        if h:
            h.sh_bpm(float(bpm))

    # ------------------------------------------------------------ sound
    def hit(self, lane, velocity=100):
        with self._lock:
            self._pending.append(("hit", lane, velocity))

    @property
    def two_engines(self):
        return self._live is not self._seq

    def _apply(self, inst, i, pos):
        inst.set(self.params[i]["key"], self._text(i, pos))

    def _refresh(self):
        vals = [self._position(i, self._seq.get(p["key"])) for i, p in enumerate(self.params)]
        with self._lock:
            self.values = vals

    def render(self, frames, events=(), with_live=True):
        """As the other machines: (sequencer, by hand), each (frames, voices); here only columns 0 and 1
        (left and right) have sound."""
        with self._lock:                     # settings changes always; hits by hand only with_live
            todo = [t for t in self._pending if with_live or t[0] != "hit"]
            self._pending = [] if with_live else [t for t in self._pending if t[0] == "hit"]
        seq = np.zeros((frames, self.voices), np.float32)
        live = np.zeros((frames, self.voices), np.float32)
        engines = (self._seq, self._live) if self.two_engines else (self._seq,)
        refresh = False
        for t in todo:
            if t[0] == "hit":
                if 0 <= t[1] < self.lanes:
                    self._live.midi(0x90, FIRST_PAD + t[1], max(1, min(127, t[2])))
                    self._offs.append((self._live, FIRST_PAD + t[1]))
                    self._live_left = LIVE_TAIL
            elif t[0] == "param":
                for inst in engines:
                    self._apply(inst, t[1], t[2])
            elif t[0] == "raw":
                for inst in engines:
                    inst.set(t[1], t[2])
            elif t[0] == "refresh":
                refresh = True
        if refresh:
            self._refresh()
        offs, self._offs = self._offs, []
        buf = np.zeros((frames, 2), np.float32)
        pos = 0
        for offset, lane, vel, locks in events:
            if not 0 <= lane < self.lanes:
                continue
            offset = max(pos, min(frames, offset))
            if offset > pos:
                self._seq.render(buf[pos:offset])
                pos = offset
            for inst, note in offs:                       # last block's hits let go first
                inst.midi(0x80, note, 0)
            offs = []
            for p in self._locked[lane] - set(locks):
                self._apply(self._seq, p, self.values[p])
            for p, v in locks.items():
                if 0 <= p < self.param_count:
                    self._apply(self._seq, p, v)
            self._locked[lane] = set(p for p in locks if 0 <= p < self.param_count)
            self._seq.midi(0x90, FIRST_PAD + lane, max(1, min(127, vel)))
            self._offs.append((self._seq, FIRST_PAD + lane))
        for inst, note in offs:
            inst.midi(0x80, note, 0)
        if pos < frames and seq_awake(self, frames, bool(events)):
            self._seq.render(buf[pos:])
        seq[:, :2] = buf
        if self.two_engines and with_live and self._live_left > 0:     # asleep until your next hit
            lbuf = np.zeros((frames, 2), np.float32)
            self._live.render(lbuf)
            live[:, :2] = lbuf
            self._live_left -= frames
        return seq, live

    def pans(self):
        p = np.zeros((self.voices, 2), np.float32)    # column 0 is the left, 1 the right
        p[0, 0] = p[1, 1] = 1.0
        return p

    def stereo(self, voices):
        return voices @ self.pans()

    def multi(self, voices):
        """No drum on its own: these modules give one stereo mix (the KIT inputs)."""
        return np.zeros((len(voices), self.channels), np.float32)


class SynthModule(Module):
    """A Schwung synth: played with notes. Its pages are the module's own; the drum page shows them, and
    track keys 1-8 play the notes the synth sequencer shows (note_on / note_off, from console.py). The
    synth sequencer's events carry each note's length in their locks as "gate" (frames)."""

    def __init__(self, mid):
        super().__init__(mid)
        self.lanes = 8                       # the keys on the sound page: 8 notes of the scale
        self.voices = 1
        self.lane_voice = [0] * self.lanes
        self.names = [self.title]
        self.short = [self.title[:4]]
        self.lane_names = [self.title] * self.lanes
        self.lane_short = [str(i + 1) for i in range(self.lanes)]
        self._param_voice = lambda lane: 0
        self._held = []                      # [frames left, note]: the sequencer's notes still sounding
        self._live_on = set()                # notes held by hand
        for p in self.params:
            p["voice"] = None
        self._voice_pages = {}
        self._locked = [set()]
        self.fx_sends = [0, 0]               # its sends to the shared REVERB and DELAY (0-127; the SENDS page)

    # kept after the module's own settings in kit(): SENDS_MARK, reverb, delay (an older kit just hasn't got them)
    SENDS_MARK = -9

    def kit(self):
        return list(self.values) + [self.SENDS_MARK] + list(self.fx_sends)

    def load_kit(self, values):
        values = list(values)
        if len(values) >= 3 and values[-3] == self.SENDS_MARK:
            self.fx_sends = [max(0, min(127, int(v))) for v in values[-2:]]
            values = values[:-3]
        else:
            self.fx_sends = [0, 0]
        super().load_kit(values)

    def set_send(self, kind, value):
        self.fx_sends[0 if kind == "reverb" else 1] = max(0, min(127, int(value)))
        with self._lock:
            self._pending.append(("mix",))          # (the core picks the sends up after its next pending batch)

    def pages(self, voice=0):
        pages = self._kit_pages or [("SOUND", [])]
        return [("MAIN" if n == "KIT" else n, idx) for n, idx in pages]

    def note_on(self, note, velocity=100):
        with self._lock:
            self._pending.append(("on", int(note), int(velocity)))

    def note_off(self, note):
        with self._lock:
            self._pending.append(("off", int(note)))

    def all_off(self):
        """Every note let go (the sequencer stopped, or this synth stopped sounding)."""
        with self._lock:
            self._pending.append(("all_off",))

    def hit(self, lane, velocity=100):
        pass                                 # synths are played with note_on / note_off

    def render(self, frames, events=(), with_live=True):
        with self._lock:
            todo = [t for t in self._pending if with_live or t[0] not in ("on", "off")]
            self._pending = [] if with_live else [t for t in self._pending if t[0] in ("on", "off")]
        seq = np.zeros((frames, self.voices), np.float32)
        live = np.zeros((frames, self.voices), np.float32)
        engines = (self._seq, self._live) if self.two_engines else (self._seq,)
        refresh = False
        for t in todo:
            if t[0] == "on":
                if t[1] in self._live_on:
                    self._live.midi(0x80, t[1], 0)
                self._live.midi(0x90, max(0, min(127, t[1])), max(1, min(127, t[2])))
                self._live_on.add(t[1])
                self._live_left = LIVE_TAIL
            elif t[0] == "off":
                if t[1] in self._live_on:
                    self._live.midi(0x80, t[1], 0)
                    self._live_on.discard(t[1])
            elif t[0] == "param":
                for inst in engines:
                    self._apply(inst, t[1], t[2])
            elif t[0] == "raw":
                for inst in engines:
                    inst.set(t[1], t[2])
            elif t[0] == "refresh":
                refresh = True
            elif t[0] == "all_off":
                for _, note in self._held:
                    self._seq.midi(0x80, note, 0)
                self._held = []
                for note in list(self._live_on):
                    self._live.midi(0x80, note, 0)
                self._live_on.clear()
        if refresh:
            self._refresh()
        # what happens in this block, in order: notes let go (0) before notes played (1) at the same time
        acts, keep = [], []
        for left, note in self._held:
            if left < frames:
                acts.append((max(0, int(left)), 0, note, 0, None))
            else:
                keep.append([left - frames, note])
        self._held = keep
        for offset, note, vel, locks in events:
            if not 0 <= note <= 127:
                continue
            locks = dict(locks)
            gate = max(1, int(locks.pop("gate", 4410)))
            acts.append((offset, 1, note, vel, locks))
            if offset + gate < frames:
                acts.append((offset + gate, 0, note, 0, None))
            else:
                self._held.append([offset + gate - frames, note])
        acts.sort(key=lambda a: (a[0], a[1]))
        buf = np.zeros((frames, 2), np.float32)
        pos = 0
        for offset, kind, note, vel, locks in acts:
            offset = max(pos, min(frames, offset))
            if offset > pos:
                self._seq.render(buf[pos:offset])
                pos = offset
            if kind == 0:
                self._seq.midi(0x80, note, 0)
                continue
            for p in self._locked[0] - set(locks):
                self._apply(self._seq, p, self.values[p])
            for p, v in locks.items():
                if isinstance(p, int) and 0 <= p < self.param_count:
                    self._apply(self._seq, p, v)
            self._locked[0] = set(p for p in locks if isinstance(p, int) and 0 <= p < self.param_count)
            self._seq.midi(0x90, note, max(1, min(127, vel)))
        if pos < frames and seq_awake(self, frames, bool(acts or self._held)):     # notes still held: awake
            self._seq.render(buf[pos:])
        seq = np.zeros((frames, 2), np.float32)
        seq[:] = buf
        if self._live_on:
            self._live_left = LIVE_TAIL                  # a key is down: stay awake until it's let go, plus the tail
        if self.two_engines and with_live and self._live_left > 0:
            live = np.zeros((frames, 2), np.float32)
            self._live.render(live)
            self._live_left -= frames
        else:
            live = np.zeros((frames, 2), np.float32)
        return seq, live

    def pans(self):
        return np.eye(2, dtype=np.float32)

    def sends(self):
        r, d = self.fx_sends
        return np.full(2, r / 127, np.float32), np.full(2, d / 127, np.float32)


def make(mid):
    """The instrument for a module id: a drum machine or a synth."""
    return SynthModule(mid) if catalog.BY_ID[mid]["kind"] == "synth" else Module(mid)
