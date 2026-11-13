"""Step 1 test on the Move: the console's audio engine playing through JACK, with no screen or controls yet.

Plays a song from /data/UserData/console/data/projects (copied over from the Pi), or, if there's no song
with that name, makes a short test beat on tracks 1-3 and loops it. Prints a status line every 2 seconds.
Ctrl+C quits.

    python3 /data/UserData/console/move/play_test.py              (the test beat)
    python3 /data/UserData/console/move/play_test.py "Song 3"     (a song copied from the Pi)
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("CONSOLE_PLATFORM", "move")
os.environ.setdefault("CONSOLE_DATA", "/data/UserData/console/data")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pi-app"))

import numpy as np   # noqa: E402
import audio         # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "Move test"
have = os.path.isdir(os.path.join(audio.DATA, "projects", name))
e = audio.Engine(song=name if have else None, bpm=120.0)

if not have:
    rate, fpb = e.rate, int(e.rate * 60 / 120)
    bars = 4
    n = fpb * 4 * bars
    t = np.arange(fpb) / rate
    kick = np.sin(2 * np.pi * (50 + 120 * np.exp(-t * 30)) * t) * np.exp(-t * 9)
    hat = np.random.default_rng(1).standard_normal(fpb // 8) * np.exp(-np.arange(fpb // 8) / 300) * 0.3
    for beat in range(4 * bars):
        a = beat * fpb
        e.tracks[0][a:a + fpb] += kick.astype(np.float32) * 0.9
        h = a + fpb // 2
        e.tracks[1][h:h + len(hat)] += hat.astype(np.float32)
    notes = [41, 41, 44, 39]                       # one per bar
    for bar, note in enumerate(notes):
        f = 440 * 2 ** ((note - 69) / 12)
        tt = np.arange(fpb * 4) / rate
        e.tracks[2][bar * fpb * 4:(bar + 1) * fpb * 4] += (np.sin(2 * np.pi * f * tt) * 0.4 *
                                                          np.exp(-(tt % (fpb / rate)) * 4)).astype(np.float32)
    e.loop_a, e.loop_b, e.loop_on = 0, n, True
    print("No song called %r: playing a test beat (kick, hats, bass) on a 4-bar loop" % name)
else:
    print("Playing %r" % name)

e.start()
deadline = time.time() + 10
while e.port is None and time.time() < deadline:
    time.sleep(0.1)
if e.port is None:
    sys.exit("No sound output: is console mode running? (" + e.status + ")")
print("Output:", e.output_label, "| volume", e.phones_volume)
with e.lock:
    e.playing = True

try:
    while True:
        time.sleep(2)
        p = e.port
        bar = e.pos / e.frames_per_beat() / 4 + 1
        print("bar %5.2f   buffer %5d frames   dropouts %d   %s" %
              (bar, p.fill() if p else -1, p.underruns if p else -1, e.status))
except KeyboardInterrupt:
    pass
finally:
    with e.lock:
        e.playing = False
    time.sleep(0.2)
    e.stop()
    print("Stopped.")
