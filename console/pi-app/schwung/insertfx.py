"""An instrument's INSERT effect: one Schwung audio effect (Tapescam, Ducker...) on that instrument's sound.

Every instrument (slot) has its own. It is picked on the FX key's third page (after REVERB and DELAY) for the
instrument you're on. Knob 1 picks the effect (NONE, Tapescam, Ducker...), knobs 2-4 change its first three settings.
The effect runs in the sound core (core_slot_insert) through libschwunghost's sh_fx_process, on the instrument's
direct sound, before the tape can record it: so what the tape records from that instrument (KIT inputs) has the
effect in it, and nothing is added to the tape afterwards.
"""
import ctypes
import json
import math
import os
import time

import catalog
import modules
import store

CHOICES_NONE = "NONE"
# Not offered as SONG INSERT 1 / 2 (still fine as an instrument's own insert): with a copy on every instrument they
# glitched or came close to it in the song insert load test (Nov 2026, 8 instruments: Tape Echo 2 and Dissolver
# dropped out, Dragonfly Hall and Cloudseed peaked near 90% and Cloudseed's copies took ~140 MB).
SONG_SKIP = {"tape-echo2", "dissolver", "dragonfly-hall", "cloudseed"}


# the settings knobs 1-8 are, for effects where the module's own order isn't the useful one (and names for settings
# the module calls the same thing): 4K EQ: the four bands' gains and frequencies (its filters need their on / off
# switches, which would not fit on the 8 knobs)
KNOBS = {"4k-eq": ["lf_gain", "lm_gain", "hm_gain", "hf_gain", "lf_freq", "lm_freq", "hm_freq", "hf_freq"]}
KNOB_LABELS = {"lf_gain": "LF GAIN", "lm_gain": "LM GAIN", "hm_gain": "HM GAIN", "hf_gain": "HF GAIN",
               "lf_freq": "LF FREQ", "lm_freq": "LM FREQ", "hm_freq": "HM FREQ", "hf_freq": "HF FREQ"}


def _params(folder, jsonname):
    """[(key, label, lo, hi, default, step, options)] from the module's module.json (ui_hierarchy and chain_params)."""
    try:
        info = json.load(open(os.path.join(folder, jsonname)))
    except (OSError, ValueError):
        return []
    found, seen = [], set()

    def add(p):
        if not isinstance(p, dict) or "key" not in p or p["key"] in seen:
            return
        t = p.get("type", "float")
        if t not in ("float", "int", "enum", "bool"):
            return
        seen.add(p["key"])
        opts = p.get("options") or ([] if t != "bool" else ["off", "on"])
        lo, hi = float(p.get("min", 0)), float(p.get("max", 1))
        if opts:
            lo, hi = 0.0, float(len(opts) - 1)
        step = float(p.get("step", 1 if t in ("int", "enum", "bool") else 0.05)) or 0.05
        if "step" not in p and t == "float" and not opts and hi - lo > 1.0:
            raw = (hi - lo) / 100.0                       # a wide range (4K EQ: -15..15 dB): about 100 clicks end to end
            mag = 10 ** math.floor(math.log10(raw))
            step = min((m for m in (1, 2, 5, 10) if m * mag >= raw * 0.7), key=lambda m: abs(m * mag - raw)) * mag
        found.append((p["key"], str(p.get("short_name") or p.get("name") or p["key"]).upper()[:12], lo, hi,
                      float(p.get("default", lo)) if not opts or isinstance(p.get("default"), (int, float)) else 0.0,
                      step, opts))

    caps = info.get("capabilities", {})
    for p in caps.get("chain_params", []) or []:
        add(p)
    for lvl in (caps.get("ui_hierarchy", {}).get("levels", {}) or {}).values():
        for p in lvl.get("params", []) or []:
            add(p)
    pick = KNOBS.get(os.path.basename(folder))
    if pick:                                              # an effect whose first 8 settings aren't the useful ones
        by = {q[0]: q for q in found}
        found = [(k, KNOB_LABELS.get(k, by[k][1]),) + by[k][2:] for k in pick if k in by]
    return found


class Insert:
    def __init__(self, core=None, slot=0, pos=0):
        self.core = core
        self.slot = slot
        self.pos = pos                      # 0: the first insert effect, 1: the second
        self.index = 0                      # 0 = none, else 1 + position in catalog.FX
        self.h = None
        self.params = []
        self.values = {}
        self.error = ""
        self.lib = None

    def choices(self):
        return [CHOICES_NONE] + [f["title"].upper() for f in catalog.FX]

    def name(self):
        return self.choices()[self.index] if self.index < len(self.choices()) else CHOICES_NONE

    def _lib(self):
        if self.lib is None:
            self.lib = modules.host()
        return self.lib

    def choose(self, index):
        index = max(0, min(len(catalog.FX), index))
        if index == self.index and (self.h or index == 0):
            return
        self.unload()
        self.index = index
        if index == 0:
            return
        f = catalog.FX[index - 1]
        folder = os.path.join(store.MODULES_DIR, f["id"])
        lib = self._lib()
        if lib is None:
            self.error = "THE MODULE HOST ISN'T BUILT"
            self.index = 0
            return
        print("insert effect: starting %s (instrument %d, insert %d)" % (f["id"], self.slot + 1, self.pos + 1),
              flush=True)                                  # (in the crash log, if starting it crashes)
        h = lib.sh_fx_open(os.path.join(folder, f["dsp"]).encode(), folder.encode(), b"")
        if not h:
            self.error = lib.sh_error().decode(errors="replace")[:60] or "COULDN'T START"
            self.index = 0
            return
        self.h, self.error = h, ""
        self.params = (_params(folder, f.get("json", "module.json")) or self._runtime_params(h))[:8]
        self.values = {p[0]: p[4] for p in self.params}
        for p in self.params:
            self._send(p[0])
        if self.core is not None:
            self.core.set_slot_insert(self.slot, self.pos, ctypes.cast(lib.sh_fx_process, ctypes.c_void_p).value, h)

    def _runtime_params(self, h):
        """Effects that don't list their settings in module.json: ask the effect itself (chain_params)."""
        try:
            buf = ctypes.create_string_buffer(8192)
            if self._lib().sh_fx_get(h, b"chain_params", buf, 8192) < 0:
                return []
            info = {"capabilities": {"chain_params": json.loads(buf.value.decode(errors="replace") or "[]")}}
        except (ValueError, OSError, AttributeError, ctypes.ArgumentError):
            return []
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            json.dump(info, open(os.path.join(tmp, "m.json"), "w"))
            return _params(tmp, "m.json")

    def unload(self):
        if self.core is not None:
            self.core.set_slot_insert(self.slot, self.pos, 0, 0)
            if self.h:
                # the sound core may be in the middle of running it right now: wait until it's let go before
                # closing it (closing it under the core's feet corrupted memory and crashed later)
                c = self.core
                time.sleep(max(0.01, 3.0 * getattr(c, "block", 128) / max(1, getattr(c, "rate", 44100))))
        if self.h and self.lib:
            self.lib.sh_fx_close(self.h)
        self.h, self.params, self.values = None, [], {}

    def _send(self, key):
        p = next((q for q in self.params if q[0] == key), None)
        if p is None or not self.h:
            return
        v = self.values[key]
        text = p[6][int(v)] if p[6] else ("%d" % v if p[5] >= 1 and float(v).is_integer() else "%.3f" % v)
        self._lib().sh_fx_set(self.h, key.encode(), str(text).encode())

    def modulate(self, slot, value):
        """An LFO moves setting `slot` (0-7) to this value, without changing the one kept on the page."""
        if slot >= len(self.params) or not self.h:
            return
        key = self.params[slot][0]
        self._lib().sh_fx_set(self.h, key.encode(), ("%.4f" % value).encode())

    def restore(self, slot):
        """An LFO lets go of setting `slot`: back to the page's value."""
        if slot < len(self.params) and self.h:
            self._send(self.params[slot][0])

    def knob(self, slot, delta):
        """slot 0-7 -> the effect's first eight settings."""
        if slot >= len(self.params) or not self.h:
            return
        key, _, lo, hi, _, step, _o = self.params[slot]
        self.values[key] = max(lo, min(hi, round((self.values[key] + delta * step) / step) * step))
        self._send(key)

    def text(self, slot):
        if slot >= len(self.params):
            return ("", "")
        key, label, lo, hi, _, step, opts = self.params[slot]
        v = self.values.get(key, 0)
        shown = opts[int(v)].upper() if opts else ("%d%%" % round(v * 100) if hi <= 1.0 else "%g" % v)
        return (label, shown)

    def midi(self, b0, b1, b2):
        """For effects that listen to notes: only the Ducker (its trigger). The others crash the whole app on a
        note (TAPESCAM did, in the stress test), so they never get one, whoever asks."""
        if self.h and self.name() == "DUCKER":
            self._lib().sh_fx_midi(self.h, b0, b1, b2)

    # a saved song's choice
    def to_json(self):
        return {"fx": catalog.FX[self.index - 1]["id"] if self.index and self.h else "", "values": self.values}

    def from_json(self, d):
        ids = [f["id"] for f in catalog.FX]
        if d and d.get("fx") in ids:
            self.choose(ids.index(d["fx"]) + 1)
            for k, v in (d.get("values") or {}).items():
                if k in self.values:
                    self.values[k] = v
                    self._send(k)


class SongInsert:
    """SONG INSERT 1 or 2 (left button 3, after REVERB and DELAY): one effect for the whole song. The tape records
    each instrument on its own track, so every loaded instrument gets its own copy of it (insert place 2 or 3,
    after its own two), all following the settings here: so it is recorded with each instrument, as the reverb
    and delay are. sync() keeps a copy on every loaded instrument (and none on an empty slot)."""

    def __init__(self, pos, get_copy):
        self.pos = pos                      # 0: SONG INSERT 1, 1: SONG INSERT 2
        self.slot = -1
        self.get_copy = get_copy            # (slot, place 2 / 3) -> that instrument's Insert
        self.index = 0
        self.params, self.values = [], {}
        self.error = ""
        self._have = {}                     # slot -> the effect index its copy runs
        self.mix = {}                       # slot -> how much of it that instrument hears, 0-100 (the SENDS page; 100)

    @property
    def h(self):
        return self.index > 0 and not self.error

    def name(self):
        names = [CHOICES_NONE] + [f["title"].upper() for f in catalog.FX]
        return names[self.index] if self.index < len(names) else CHOICES_NONE

    def choose(self, index, slots=None):
        index = max(0, min(len(catalog.FX), index))
        self.index, self.error = index, ""
        self.params, self.values = [], {}
        if slots is not None:
            self.sync(slots)

    def sync(self, slots):
        """slots: which of the 8 have an instrument. Starts / stops copies so each loaded one has this effect."""
        for k in range(8):
            want = self.index if slots[k] else 0
            if self._have.get(k, 0) == want:
                continue
            ins = self.get_copy(k, 2 + self.pos)
            ins.choose(want)
            self._have[k] = want                       # (one that failed to start isn't tried again and again)
            if ins.error:
                self.error = ins.error
            if want and ins.h:
                if not self.params:                 # the first copy tells the settings (and their defaults)
                    self.params = list(ins.params)
                    self.values = dict(ins.values) if not self.values else self.values
                for key, v in self.values.items():   # every copy follows the settings here
                    if key in ins.values:
                        ins.values[key] = v
                        ins._send(key)
        if self.index and not any(self._have.get(k) for k in range(8)) and not self.params:
            self._load_params()
        for k in range(8):
            self._apply_mix(k)

    def amount(self, slot):
        return int(self.mix.get(slot, 100))

    def set_amount(self, slot, value):
        """How much of this effect instrument slot hears, 0-100 (wet/dry, on its copy)."""
        self.mix[slot] = max(0, min(100, int(value)))
        self._apply_mix(slot)
        return self.mix[slot]

    def _apply_mix(self, k):
        if k not in self._have and k not in self.mix:
            return
        try:
            ins = self.get_copy(k, 2 + self.pos)
            if ins.core is not None and hasattr(ins.core, "set_slot_insert_mix"):
                ins.core.set_slot_insert_mix(k, 2 + self.pos, self.amount(k) / 100.0)
        except Exception:                          # noqa: BLE001
            pass

    def _load_params(self):
        """No instrument loaded yet: still show the effect's settings (from its module.json)."""
        f = catalog.FX[self.index - 1]
        folder = os.path.join(store.MODULES_DIR, f["id"])
        self.params = _params(folder, f.get("json", "module.json"))[:8]
        self.values = {p[0]: p[4] for p in self.params}

    def copies(self):
        return [self.get_copy(k, 2 + self.pos) for k, v in self._have.items() if v]

    def knob(self, slot, delta):
        if slot >= len(self.params):
            return
        key, _, lo, hi, _, step, _o = self.params[slot]
        self.values[key] = max(lo, min(hi, round((self.values.get(key, lo) + delta * step) / step) * step))
        for ins in self.copies():
            if key in ins.values:
                ins.values[key] = self.values[key]
                ins._send(key)

    text = Insert.text

    def to_json(self):
        return {"fx": catalog.FX[self.index - 1]["id"] if self.index else "", "values": self.values,
                "mix": {str(k): v for k, v in self.mix.items() if v != 100}}

    def from_json(self, d, slots):
        ids = [f["id"] for f in catalog.FX]
        try:
            self.mix = {int(k): max(0, min(100, int(v))) for k, v in ((d or {}).get("mix") or {}).items()}
        except (TypeError, ValueError, AttributeError):
            self.mix = {}
        self.choose(ids.index(d["fx"]) + 1 if d and d.get("fx") in ids else 0)
        if self.index:
            self._load_params()
            for k, v in (d.get("values") or {}).items():
                if k in self.values:
                    self.values[k] = v
        self.sync(slots)
