"""Step 3 of the C sound core, on the Move (console mode running): record onto the tape, then hear it back.

    python3 /data/UserData/console/move/tape_test.py

1. The LXR plays a beat for 2 bars (120 BPM) and the core records it onto track 1, looping.
2. Then the drum machine stops and you hear track 1 play back from the tape, looping: the same beat, now
   coming off tape. Play pads 1-8 (bottom row) on top: they're heard but not recorded.
The screen says which part it's in. After about 10 seconds it prints what each part of the sound (the
instruments, the tape, the reverb, the delay) was doing, to find where any odd sound comes from. Ctrl+C quits.
"""
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "pi-app")
os.environ.setdefault("CONSOLE_PLATFORM", "move")
os.environ.setdefault("CONSOLE_DATA", "/data/UserData/console/data")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "core"))

import drums       # noqa: E402
import effects     # noqa: E402
import sequencer   # noqa: E402
import core as K   # noqa: E402
from core import Core                     # noqa: E402
from instruments import Slot, Scheduler   # noqa: E402

src = open(os.path.join(HERE, "move_test.py")).read()
ns = {"LAYOUT": "pages"}
exec(src[src.index("FONT = {"):src.index("# ---------------------------------------------------------------- shared state")], ns)
render_screen = ns["render"]

BPM = 120.0
FPB = 44100 * 60 / BPM
BAR = int(FPB * 4)

c = Core()
d = drums.Drums()
rv, dl = effects.Reverb(c.rate), effects.Delay(c.rate)
rv.set(0.5, 0.5)
dl.set(0.75 * FPB, 0.4)
c.effects(effects._lib.rev_process, rv.h, effects._lib.dly_process, dl.h)
c.effect_levels(0.8 * effects.REVERB_MAKEUP, 0.7)

lxr = d.get("lxr")
lxr.set_bpm(BPM)
slot = Slot(c, lxr, 0)
c.slot_monitor(0, 0.8)

frames = 60 * 44100
chans = [np.zeros(frames, np.float32) for _ in range(8)] + [None] * 8
c.tape(chans, frames)
for t in range(8):
    c.tape_track(t, 0.8, 0.0, 0.0, 0.0, True, False)
c.tape_loop(True, 0, 2 * BAR)

seq = sequencer.Sequencer()
seq.bar_beats = 4
for lane in range(6):
    for step in range(lane % 2, 16, 2 if lane < 3 else 3):
        seq.toggle(lane, step)

lines = ["TAPE TEST", "RECORDING TRACK 1", "2 BARS...", ""]
c.display(render_screen(lines))

c.capture(True)                                     # listen in, to say afterwards what made which sound
cap_start = c.now()
switch = [None]
c.tape_arm(0, True, (K.DRUM_KIT + 2, -1))          # slot 1's kit, mono
at = (c.now() // c.block + 40) * c.block            # the start of a cycle, a moment from now
c.transport(K.T_PLAY, 0, at=at)
c.transport(K.T_RECORD, at=at)
sched = Scheduler(c)
sched.start_frame, sched.sent, sched.playing = at, 0, True
stop = False
phase = ["record"]
recorded = [0]


def loop():
    while not stop:
        for frame, msg in c.read_midi():
            kind, note, vel = msg[0] & 0xF0, msg[1], msg[2]
            if kind == 0x90 and 68 <= note < 76 and vel:
                lxr.hit(note - 68, vel)
            if kind in (0x80, 0x90) and 68 <= note < 100:
                c.send_midi(bytes((0x9F, note, 127 if (kind == 0x90 and vel) else 0)))
            elif kind == 0xB0 and note == 79:                  # the volume knob
                c.volume_knob(vel)
        slot.flush()
        if phase[0] == "record":
            sched.tick([(slot, seq)], FPB)
            r = c.recorded(0)
            if r:
                recorded[0] = max(recorded[0], r[1])
            if c.now() >= at + 2 * BAR:                  # two bars done: stop recording and the machine
                c.transport(K.T_RECORD_OFF)
                c.tape_arm(0, False)
                sched.stop()
                phase[0] = "play"
                switch[0] = c.now()
                lines[1:4] = ["PLAYING TRACK 1", "FROM THE TAPE", "PADS 1-8: DRUMS"]
                c.display(render_screen(lines))
        time.sleep(0.003)


threading.Thread(target=loop, daemon=True).start()

def report():
    """What each part of the sound was doing while recording and while playing back."""
    total = int(c.now() - cap_start)
    split = int(switch[0] - cap_start) if switch[0] else total
    print("\nWhat was heard (steady near 1 = a drone, near 0 = drums):")
    for p, name in enumerate(c.PARTS):
        x = c.captured(p, total)
        print("  %-12s while recording: %s" % (name, c.describe(x[:split])))
        print("  %-12s playing back:    %s" % ("", c.describe(x[split:])))
    print()


reported = False
try:
    last = c.cycles()
    while True:
        time.sleep(2)
        if not reported and switch[0] and c.now() - switch[0] > 6 * c.rate:
            report()
            reported = True
        cyc = c.cycles()
        print("%-6s  tape bar %4.2f   JACK load %5.1f%%   cycles a second %5.1f" %
              (phase[0], c.tape_pos() / BAR + 1, c.load(), (cyc - last) / 2))
        last = cyc
except KeyboardInterrupt:
    pass
finally:
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    stop = True
    time.sleep(0.05)
    for n in range(68, 100):
        c.send_midi(bytes((0x9F, n, 0)))
    c.display(render_screen([]))
    time.sleep(0.1)
    c.close()
    print("Recorded up to frame %d of %d." % (recorded[0], 2 * BAR))
