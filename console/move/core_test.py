"""Step 1 of the C sound core, on the Move (console mode running): play the instruments from the pads.

    python3 /data/UserData/console/move/core_test.py           pads: bottom row = LXR drums, the rest = a synth
    python3 /data/UserData/console/move/core_test.py jam       the LXR and three synths playing busy patterns
                                                               (the same test as bench.py), with JACK's load

Every couple of seconds it prints JACK's load: how busy the audio cycle is (all of it, ours included).
Ctrl+C quits.
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "pi-app")
os.environ.setdefault("CONSOLE_PLATFORM", "move")
os.environ.setdefault("CONSOLE_DATA", "/data/UserData/console/data")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "core"))

import drums     # noqa: E402
import effects   # noqa: E402
from core import Core  # noqa: E402

JAM = "jam" in sys.argv
SYNTHS = ["dexed", "plaits", "braids"] if JAM else ["dexed"]

# ---------------------------------------------------------------- the screen (the hardware test's font)
src = open(os.path.join(HERE, "move_test.py")).read()
ns = {"LAYOUT": "pages"}
exec(src[src.index("FONT = {"):src.index("# ---------------------------------------------------------------- shared state")], ns)
render_screen = ns["render"]

c = Core()
print("Core running: %d Hz, %d frames a cycle" % (c.rate, c.block))
d = drums.Drums()


def add_engine(lib, machine, gain=0.8):
    s = c.add_engine(lib.drums_render, lib.drums_trigger, drums.VOICES)
    pans = machine.pans()
    rev, dly = machine.sends()
    for v in range(drums.VOICES):
        c.pan(s, v, float(pans[v][0]), float(pans[v][1]))
        c.sends(s, v, float(rev[v]), float(dly[v]))
    c.gain(s, gain)
    c.on(s)
    return s


def add_synth(inst, gain=0.8):
    h = drums.schwung_modules.host()
    s = c.add_module(h.sh_render, h.sh_midi, inst.ptr)
    c.gain(s, gain)
    c.on(s)
    return s


lxr = d.get("lxr")
lxr_live = add_engine(drums._live, lxr)
lxr_seq = add_engine(drums._lib, lxr) if JAM else None
synths = {}
for name in SYNTHS:
    m = d.get(name)
    if m is None:
        print("(no %s)" % name)
        continue
    synths[name] = (add_synth(m._live), add_synth(m._seq) if JAM else None)
print("Instruments:", "lxr", *synths)

rv, dl = effects.Reverb(c.rate), effects.Delay(c.rate)
rv.set(0.5, 0.5)
dl.set(0.75 * c.rate * 60 / 120, 0.4)
c.effects(effects._lib.rev_process, rv.h, effects._lib.dly_process, dl.h)
c.effect_levels(0.8 * effects.REVERB_MAKEUP, 0.7)

lines = ["CORE TEST", "BOTTOM ROW: DRUMS", "OTHER PADS: SYNTH", ""]
c.display(render_screen(lines))
stop = False

# ---------------------------------------------------------------- the pads
PAD0 = 68
synth_live = next(iter(synths.values()))[0] if synths else None


def pads():
    while not stop:
        for frame, m in c.read_midi():
            kind, note, vel = m[0] & 0xF0, m[1], m[2]
            if kind == 0x80:
                kind, vel = 0x90, 0
            if kind == 0x90 and PAD0 <= note < PAD0 + 32:
                pad = note - PAD0
                if pad < 8:
                    if vel:
                        c.trigger(lxr_live, min(pad, 6), vel)
                elif synth_live is not None:
                    c.midi(synth_live, 0x90 if vel else 0x80, 36 + pad, vel)
                c.send_midi(bytes((0x9F, note, 127 if vel else 0)))
                if vel:
                    lines[3] = "PAD %d  VEL %d" % (pad + 1, vel)
                    c.display(render_screen(lines))
            elif kind == 0xB0 and note == 79:                  # the volume knob
                c.volume_knob(vel)
        time.sleep(0.001)


threading.Thread(target=pads, daemon=True).start()

# ---------------------------------------------------------------- jam: patterns, scheduled ahead
STEP = c.rate * 60 / 120 / 4                       # a 16th at 120 BPM, in frames


def jam():
    start = c.now() + c.rate // 10
    step = 0
    while not stop:
        horizon = c.now() + c.rate // 10            # keep 100 ms of steps queued
        while start + step * STEP < horizon:
            at = int(start + step * STEP)
            s16 = step % 16
            for lane in range(6):
                if s16 % (2 if lane < 3 else 3) == lane % 2:
                    c.trigger(lxr_seq, lane, 100, at=at)
            for _name, (_live, sq) in synths.items():
                if s16 % 4 == 0:
                    for note in (48, 55, 60, 64):
                        c.midi(sq, 0x90, note, 100, at=at)
                        c.midi(sq, 0x80, note, 0, at=at + int(3 * STEP))
                n = 72 + (s16 * 5) % 12
                c.midi(sq, 0x90, n, 100, at=at)
                c.midi(sq, 0x80, n, 0, at=at + int(STEP * 0.9))
            step += 1
        time.sleep(0.01)


if JAM:
    threading.Thread(target=jam, daemon=True).start()

try:
    last = c.cycles()
    while True:
        time.sleep(2)
        cyc = c.cycles()
        print("JACK load %5.1f%%   cycles a second %5.1f" % (c.load(), (cyc - last) / 2))
        last = cyc
except KeyboardInterrupt:
    pass
finally:
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)       # a second Ctrl+C can't stop the tidying up
    stop = True
    for n in range(PAD0, PAD0 + 32):
        c.send_midi(bytes((0x9F, n, 0)))
    c.display(render_screen([]))
    time.sleep(0.1)
    c.close()
    print("Stopped.")
