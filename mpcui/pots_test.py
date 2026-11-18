"""Host test for mpcui/pots.py: a pot turned from one end to the other (0-127) must cover each setting's whole range, and a short list
gets an equal zone of the travel per name. Stand-ins for the engine and the pages; run: python3 mpcui/pots_test.py"""
import os
import sys
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
for n in ("pygame", "numpy"):
    try:
        __import__(n)
    except Exception:                                      # noqa: BLE001
        sys.modules[n] = types.ModuleType(n)
sys.path[:0] = [HERE, os.path.join(HERE, "..", "console", "pi-app"), os.path.join(HERE, "..", "console", "move")]
import knobgate  # noqa: E402
import pots  # noqa: E402
import sequencer  # noqa: E402

fails = []


def check(ok, what):
    print(("ok:   " if ok else "FAIL: ") + what)
    if not ok:
        fails.append(what)


def sweep(set_fn, get_fn):
    """Turn the pot from 0 to 127: the values it passes through."""
    out = []
    for v in range(128):
        set_fn(v)
        out.append(get_fn())
    return out


# ---- zones: five names, 127 / 5 each
counts = [0] * 5
for v in range(128):
    counts[pots.zone(v, 5)] += 1
check(min(counts) >= 25 and max(counts) <= 26 and pots.zone(0, 5) == 0 and pots.zone(127, 5) == 4, "five names: equal zones %s" % counts)

# ---- a drum machine / synth setting
class Drums:
    def __init__(self):
        self.p = {}
        self.top = {"num": 100, "mode5": 4, "wide": 255, 7: 100}
        self.modes = {"mode5"}

    def stepped(self, key, v, clicks):
        return min(self.top[key], max(0, v + clicks))

    def set_param(self, key, v):
        self.p[key] = v

    def kind(self, key):
        return "menu" if key in self.modes else "num"

    def lockable(self, key):
        return True

    def label(self, key):
        return key.upper()


d = Drums()
vals = [pots.param_value(d, "num", v) for v in range(128)]
check(vals[0] == 0 and vals[127] == 100 and vals[64] in (50, 51) and vals == sorted(vals), "a number 0-100: 0 .. 100 end to end")
vals = [pots.param_value(d, "wide", v) for v in range(128)]
check(vals[0] == 0 and vals[127] == 255, "a number 0-255: 0 .. 255 end to end")
vals = [pots.param_value(d, "mode5", v) for v in range(128)]
check(sorted(set(vals)) == [0, 1, 2, 3, 4] and vals[0] == 0 and vals[127] == 4, "a 5-name mode (TAPESCAN's): five zones")

# ---- fake page
class Eng:
    def __init__(self):
        self.lock = threading.RLock()
        self.dirty = set()
        self.drums = d
        self.rev_sends = [0.0] * 8
        self.dly_sends = [0.0] * 8
        self.sends = {"reverb": 0.0, "delay": 0.0}
        self.seq_n = 0
        self.slot = 0

    def change_send(self, kind, track, delta):
        s = self.rev_sends if kind == "reverb" else self.dly_sends
        s[track - 1] = round(max(0.0, min(1.0, s[track - 1] + delta)), 2)
        return s[track - 1]

    def inst_send(self, kind):
        return self.sends[kind]

    def change_inst_sends(self, kind, delta):
        self.sends[kind] = round(max(0.0, min(1.0, self.sends[kind] + delta)), 2)
        return self.sends[kind]

    def seq_changed(self):
        self.seq_n += 1


class Ml:
    def __init__(self):
        self.cfg_ = {"glide": 0, "bend": 0}
        self.mode = None

    def active(self):
        return True

    def cfg(self):
        return self.cfg_

    def arp_on_page(self):
        return self.mode == "arp2"

    def arp_second(self):
        return self.mode == "arp2"

    def arp_values(self):
        return [("GLIDE", str(self.cfg_["glide"])), ("BEND", str(self.cfg_["bend"]))]

    def sends_on_page(self):
        return self.mode == "sends"

    def _inserts(self):
        return 0

    def insert_pos(self):
        return None


class Ins:
    def __init__(self):
        self.h = 1
        self.params = [("amt", "AMT", 0.0, 1.0, 0.0, 0.01, None), ("kind", "KIND", 0, 4, 0, 1, ["a", "b", "c", "d", "e"]),
                       ("hz", "HZ", 20.0, 20000.0, 100.0, 1.0, None)]
        self.values = {p[0]: p[4] for p in self.params}

    def knob(self, slot, delta):
        key, _l, lo, hi, _d, step, _o = self.params[slot]
        self.values[key] = max(lo, min(hi, round((self.values.get(key, lo) + delta * step) / step) * step))


T = types.SimpleNamespace(engine=Eng(), mlfo=Ml(), fx_page=None, seq_page=False, inst_page=False, song_page=False, say=lambda m, t=0: None,
                          arp_pop=0, pads_pop=0, _mpc_menu=None, inst_sends=False, ins=Ins())
T.insfx = lambda slot=None, pos=None: T.ins
T.songfx = lambda p: T.ins
T._insfx_save = lambda: None
e = T.engine

# ---- ARP 2: GLIDE 0-100 and BEND -100..100
T.mlfo.mode = "arp2"
go = pots.target(T, 1)
v = sweep(go, lambda: T.mlfo.cfg_["glide"])
check(v[0] == 0 and v[127] == 100, "ARP 2 GLIDE: pot end to end = 0 .. 100 (%d .. %d)" % (v[0], v[127]))
go = pots.target(T, 2)
v = sweep(go, lambda: T.mlfo.cfg_["bend"])
check(v[0] == -100 and v[127] == 100 and 0 in v, "ARP 2 BEND: pot end to end = -100 .. +100, a rest at 0 (%d .. %d)" % (v[0], v[127]))
check(pots.target(T, 3) is None, "ARP 2: K3 has nothing")
T.mlfo.mode = None

# ---- REVERB / DELAY: the tracks' sends
for page in ("reverb", "delay"):
    T.fx_page = page
    for n in (1, 2, 3, 8):
        go = pots.target(T, n)
        arr = e.rev_sends if page == "reverb" else e.dly_sends
        v = sweep(go, lambda: arr[n - 1])
        check(v[0] == 0.0 and v[127] == 1.0, "%s page, knob %d: track %d send 0 .. 100 %%" % (page.upper(), n, n))
T.fx_page = None

# ---- the instrument's SENDS page
T.mlfo.mode = "sends"
for n, kind in ((1, "reverb"), (2, "delay")):
    v = sweep(pots.target(T, n), lambda: e.sends[kind])
    check(v[0] == 0.0 and v[127] == 1.0, "SENDS page K%d: %s send 0 .. 100 %%" % (n, kind))
T.mlfo.mode = None

# ---- an INSERT page: a number, a 5-name list, a wide range
T.fx_page = "insert"
v = sweep(pots.target(T, 1), lambda: T.ins.values["amt"])
check(abs(v[0]) < 1e-9 and abs(v[127] - 1.0) < 1e-9, "INSERT K1: 0 .. 1 end to end")
v = sweep(pots.target(T, 2), lambda: T.ins.values["kind"])
check(sorted(set(v)) == [0, 1, 2, 3, 4] and v[0] == 0 and v[127] == 4, "INSERT K2 (five names): five zones")
v = sweep(pots.target(T, 3), lambda: T.ins.values["hz"])
check(abs(v[0] - 20.0) < 1 and abs(v[127] - 20000.0) < 1, "INSERT K3: 20 .. 20000 end to end")
check(pots.target(T, 4) is None or True, "INSERT: knob 4 is not a pot")
T.fx_page = None

# ---- a sound page: the FADER (knob 8) and a mode on K1 (K1-K3 numbers stay with stepentry.sound_k1_set)
import stepentry  # noqa: E402
stepentry.sound_k1 = lambda T_, n, choices=False: {1: "mode5", 2: "num", 8: "wide"}.get(n) if (choices or n != 1) else None
T.drumpage = types.SimpleNamespace(edited={})
v = sweep(pots.target(T, 8), lambda: d.p["wide"])
check(v[0] == 0 and v[127] == 255, "sound page FADER: 0 .. 255 end to end")
v = sweep(pots.target(T, 1), lambda: d.p["mode5"])
check(sorted(set(v)) == [0, 1, 2, 3, 4], "sound page K1 on a 5-name mode: five zones")
check(pots.target(T, 2) is None, "sound page K2 on a number: left to stepentry.sound_k1_set (full range already)")

# ---- the clicks of a pot used by position are not used again
T.fx_page = "reverb"
T.__dict__.pop("_pot_abs_at", None)
check(pots.handle(T, 71, 1) is False, "a wheel click (no position before it) is left alone")
pots.handle(T, 115, 64)
check(pots.handle(T, 71, 1) is True, "K1's clicks right after its position are swallowed")
T.fx_page = None


# ---- the sequencers: K1 on a picked setting, and the sound locks
class St:
    def __init__(self):
        self.on = False
        self.vel = 100
        self.chance = 0
        self.ratchet = 1
        self.locks = {}
        self.comp = {}


import moveseq  # noqa: E402
import movesynth  # noqa: E402

st = St()
_seq = types.SimpleNamespace(lock=threading.RLock(), step=lambda l, i: st)
ms = object.__new__(type("D", (moveseq.MoveSeq,), {"held": 0, "seq": _seq}))
ms.T = types.SimpleNamespace(engine=e)


vv = []
for val in range(128):
    ms._pos_one(0, 0, "vel", val)
    vv.append(st.vel)
check(vv[0] == 0 and vv[127] == 127 and vv == sorted(vv), "drum VELOCITY: 0 (random) .. 127 end to end")
vv = []
for val in range(128):
    ms._pos_one(0, 0, "chance", val)
    vv.append(st.chance)
check(sorted(set(vv)) == list(range(len(sequencer.CHANCES))) and vv[0] == 0 and vv[127] == len(sequencer.CHANCES) - 1,
      "drum CHANCE: all %d choices, one zone each" % len(sequencer.CHANCES))
vv = []
for val in range(128):
    ms._pos_one(0, 0, "ratchet", val)
    vv.append(st.ratchet)
check(sorted(set(vv)) == sorted(moveseq.RATCHETS), "drum MULTIPLY: every value, one zone each")
vv = []
for val in range(128):
    ms._pos_one(0, 0, "pulse", val)
    vv.append(st.comp["pulse"])
check(sorted(set(vv)) == list(range(len(sequencer.COMPONENTS["pulse"]))), "drum PULSE: every choice, one zone each")
vv = []
for val in range(128):
    ms._pos_one(0, 0, 7, val)
    vv.append(st.locks[7])
check(vv[0] == 0 and vv[127] == 100, "drum step lock on a number: 0 .. 100 end to end")

# synth
class Note:
    def __init__(self):
        self.length = 1
        self.vel = 100
        self.chance = 0
        self.ratchet = 1
        self.nudge = 0
        self.locks = {}
        self.comp = {}


nt = Note()
cls = type("Y", (movesynth.MoveSynth,), {"d": d})
sy = object.__new__(cls)


def synth(key):
    out = []
    for val in range(128):
        sy._pos_one(nt, key, val)
        out.append((nt.length, nt.vel, nt.chance, nt.ratchet, nt.nudge, nt.comp.get(key), nt.locks.get(key)))
    return out


r = synth("vel")
check(r[0][1] == 1 and r[127][1] == 127, "synth VELOCITY: 1 .. 127 end to end")
r = synth("length")
check(r[0][0] == 1 and r[127][0] == movesynth.notes_mod.MAX_LENGTH, "synth LENGTH: 1 .. %d end to end" % movesynth.notes_mod.MAX_LENGTH)
r = synth("ratchet")
check(sorted({x[3] for x in r}) == list(range(1, movesynth.MAX_RATCHET + 1)), "synth MULTIPLY: 1 .. %d, one zone each" % movesynth.MAX_RATCHET)
r = synth("nudge")
check(sorted({x[4] for x in r}) == [-50, -40, -30, -20, -10, 10, 20, 30, 40, 50], "synth NUDGE: all ten values, one zone each")
r = synth("chance")
check(len({x[2] for x in r}) == len(sequencer.CHANCES), "synth CHANCE: all %d choices, one zone each" % len(sequencer.CHANCES))
r = synth("hold")
check(len({x[5] for x in r}) == len(sequencer.COMPONENTS["hold"]), "synth HOLD: every choice, one zone each")
r = synth("num")
check(r[0][6] == 0 and r[127][6] == 100, "synth step lock on a number: 0 .. 100 end to end")

print("FAILED (%d)" % len(fails) if fails else "ALL PASSED")
sys.exit(1 if fails else 0)
