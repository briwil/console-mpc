"""Step 2 of the C sound core, on the Move (console mode running): the console's real sequencer playing the
instruments through the core, with your pads playing on top.

    python3 /data/UserData/console/move/seq_test.py                   (lxr + dexed, plaits, braids)
    python3 /data/UserData/console/move/seq_test.py lxr 808 obxd      (your choice)
    python3 /data/UserData/console/move/seq_test.py quiet             (no patterns: just the pads)

The drum machine plays a beat, each synth a chord on every beat and a 16th-note line. Pads 1-8 (one row: the
screen shows which pad you pressed): hits on the first drum machine; pads 9-32: notes on the first synth.
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

import drums       # noqa: E402
import effects     # noqa: E402
import notes       # noqa: E402
import sequencer   # noqa: E402
from core import Core                     # noqa: E402
from instruments import Slot, Scheduler   # noqa: E402

QUIET = "quiet" in sys.argv                 # no patterns: just the pads
names = [a for a in sys.argv[1:] if a != "quiet"] or ["lxr", "dexed", "plaits", "braids"]
BPM = 120.0
FPB = 44100 * 60 / BPM                    # frames per beat

src = open(os.path.join(HERE, "move_test.py")).read()
ns = {"LAYOUT": "pages"}
exec(src[src.index("FONT = {"):src.index("# ---------------------------------------------------------------- shared state")], ns)
render_screen = ns["render"]

c = Core()
d = drums.Drums()
rv, dl = effects.Reverb(c.rate), effects.Delay(c.rate)
rv.set(0.5, 0.5)
dl.set(0.75 * FPB, 0.4)
c.effects(effects._lib.rev_process, rv.h, effects._lib.dly_process, dl.h)
c.effect_levels(0.8 * effects.REVERB_MAKEUP, 0.7)

slots, plays = [], []
for name in names:
    m = d.get(name)
    if m is None:
        print("(no %s)" % name)
        continue
    m.set_bpm(BPM)
    slot = Slot(c, m)
    synth = slot.kind == "synth"
    seq = notes.NoteSequencer() if synth else sequencer.Sequencer()
    seq.bar_beats = 4
    if synth:
        for step in range(0, 16, 4):
            for note in (48, 55, 60, 64):
                seq.toggle(step, note, 3)
        for step in range(16):
            seq.toggle(step, 72 + (step * 5) % 12, 1)
    else:
        for lane in range(6):
            for step in range(lane % 2, 16, 2 if lane < 3 else 3):
                seq.toggle(lane, step)
    slots.append(slot)
    if not QUIET:
        plays.append((slot, seq))
print("Playing:", ", ".join(s.m.__class__.__name__ + " " + n for s, n in zip(slots, names)))

drum = next((s for s in slots if s.kind != "synth"), None)
synth = next((s for s in slots if s.kind == "synth"), None)
lines = ["SEQUENCER TEST", "%d BPM" % BPM, ", ".join(names)[:20].upper(), ""]
c.display(render_screen(lines))

sched = Scheduler(c)
sched.start()
stop = False


def loop():
    while not stop:
        for frame, msg in c.read_midi():
            kind, note, vel = msg[0] & 0xF0, msg[1], msg[2]
            if kind == 0x80:
                kind, vel = 0x90, 0
            if kind == 0x90 and 68 <= note < 100:
                pad = note - 68
                if pad < 8 and drum:
                    if vel:
                        drum.m.hit(min(pad, drum.m.lanes - 1), vel)
                elif synth:
                    if vel:
                        synth.m.note_on(36 + pad, vel)
                    else:
                        synth.m.note_off(36 + pad)
                c.send_midi(bytes((0x9F, note, 127 if vel else 0)))
                if vel:
                    lines[3] = "PAD %d: %s" % (pad + 1, "DRUM" if pad < 8 else "SYNTH")
                    c.display(render_screen(lines))
            elif kind == 0xB0 and note == 79:
                c.volume_knob(vel)
        for s in slots:
            s.flush()
            s.tick()
        sched.tick(plays, FPB)
        time.sleep(0.003)


threading.Thread(target=loop, daemon=True).start()
try:
    last = c.cycles()
    while True:
        time.sleep(2)
        cyc = c.cycles()
        bar = sched.seq_frame() / FPB / 4 + 1
        print("bar %6.2f   JACK load %5.1f%%   cycles a second %5.1f" % (bar, c.load(), (cyc - last) / 2))
        last = cyc
except KeyboardInterrupt:
    pass
finally:
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)       # a second Ctrl+C can't stop the tidying up
    stop = True
    time.sleep(0.05)
    for n in range(68, 100):
        c.send_midi(bytes((0x9F, n, 0)))
    c.display(render_screen([]))
    time.sleep(0.1)
    c.close()
    print("Stopped.")
