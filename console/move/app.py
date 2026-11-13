"""Console on the Ableton Move: the Pi app's own logic (console.Transport, the menus, the engine) with the
Move's controls and screen. Run in console mode:

    python3 /data/UserData/console/move/app.py

The engine makes its sound with the C sound core (core/bridge.py). The Pi app's drawing is never used: it runs
with the simulator's stand-in pygame, and pages.py draws the Move's screen from the app's state instead.

Controls (see MOVE-NOTES.md):
  Play / Record / Loop / Undo, Shift for their second jobs; Copy = LIFT, Delete = CUT, Capture = DROP,
  Sample = SPLICE, Mute = mute (Shift: solo); Menu = the project menu (Shift: export), Back = back; + / - = the Pi's knob 9;
  left buttons (top to bottom): instruments, song mode, FX, the recorder (again: the selected track zoomed); knobs 1-8; jog wheel = the
  big knob (push to choose; Shift + turn = knob 10); step buttons 1-8 select tracks (Shift: arm), on the drum sequencer the 16 steps
  (see moveseq.py), on song mode its rows; pads: drums on the left 4 x 4, the picked drum chromatically on the right (Shift + pad: pattern). Shift + touch a knob = push it. Shift + Back: save, quit and go back to the normal Move
  (Ctrl+C over SSH only quits the app).
"""
import faulthandler
import os
import re
import queue
import sys
import time

faulthandler.enable(all_threads=True)      # a crash inside an effect or synth (not Python's): app.log gets the Python line it was on

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
APP = os.path.join(REPO, "pi-app")
STUBS = os.path.join(REPO, "tools", "sim", "stubs")
sys.path[:0] = [STUBS, APP, HERE]
os.environ.setdefault("CONSOLE_PLATFORM", "move")
PIDFILE = os.environ.get("CONSOLE_PIDFILE", "/data/UserData/console/app.pid")


def already_running():
    """The pid of another copy of the app that's still running (the one the Move started), or None."""
    try:
        pid = int(open(PIDFILE).read().strip())
        if pid != os.getpid() and os.path.exists("/proc/%d" % pid) and \
                "app.py" in open("/proc/%d/cmdline" % pid).read():
            return pid
    except (OSError, ValueError):
        pass
    return None


if __name__ == "__main__" and not os.environ.get("CONSOLE_MALLOC_CHECKED") and \
        os.path.exists(os.path.join(os.environ.get("CONSOLE_HOME", "/data/UserData/console"), "stress")):
    # the stress test: start again with the C library checking memory, so a module that damages it is caught
    # where it does it (not later, somewhere else)
    os.environ.update(CONSOLE_MALLOC_CHECKED="1", MALLOC_CHECK_="3")
    for _lib in ("/lib/libc_malloc_debug.so.0", "/usr/lib/libc_malloc_debug.so.0",
                 "/lib/aarch64-linux-gnu/libc_malloc_debug.so.0",
                 "/usr/lib/aarch64-linux-gnu/libc_malloc_debug.so.0", "/usr/lib/x86_64-linux-gnu/libc_malloc_debug.so.0"):
        if os.path.exists(_lib):
            os.environ["LD_PRELOAD"] = _lib
            break
    os.execv(sys.executable, [sys.executable] + sys.argv)
import crashlog                   # noqa: E402  (console/crashes: what happened before a crash)
import stress                     # noqa: E402  (the stress test: console/stress)
# the stress test uses its own projects (stress-data): it has to say so before anything reads CONSOLE_DATA
STRESS_MINUTES = stress.prepare() if __name__ == "__main__" and not already_running() else None
os.environ.setdefault("CONSOLE_DATA", "/data/UserData/console/data")

import pygame                     # noqa: E402  (the simulator's stand-in: the app draws nothing real)
pygame.init()
import audio                      # noqa: E402
import ui                         # noqa: E402
import console                    # noqa: E402
import menu as menu_mod           # noqa: E402
import kitmenu                    # noqa: E402
import pages                      # noqa: E402
import moveseq                    # noqa: E402
import movesong                   # noqa: E402
import movesynth                  # noqa: E402
import movelfo                    # noqa: E402
import moveauto                   # noqa: E402
import movepresets                # noqa: E402
import movepunch                  # noqa: E402
import opening                    # noqa: E402
import samplebrowse              # noqa: E402
import fxpicker                  # noqa: E402
import pagefx                    # noqa: E402
import knobgate                   # noqa: E402
import moveupdater                # noqa: E402
import updater                    # noqa: E402
updater.Updater = moveupdater.Updater   # SETTINGS > SOFTWARE UPDATE: from GitHub with move-update.py
from screen import Frame, W       # noqa: E402

FPS_SCREEN = 20

# ---------------------------------------------------------------- the Move's controls -> the app's actions

PRESS = {85: ("PLAY", "REWIND"), 86: ("RECORD", "REC_MODE"), 58: ("LOOP", "CLEAR_REGION"),
         62: ("LEFT", "LOOP_IN"), 63: ("RIGHT", "LOOP_OUT"), 56: ("UNDO", "UNDO"),
         52: ("DROP", "DROP_INSERT"), 118: ("SPLICE", "SPLICE_ALL"), 88: ("MUTE", "SOLO"),
         50: ("FILE", "EXPORT"), 3: ("HOME", "HOME_PUSH_SHIFT"),
         43: ("DRUMS", "DRUMS_BACK"), 42: ("SONG", "SONG_TOGGLE"), 41: ("FX", "FX"), 40: ("TAPE", "ARM_ALL")}
HOLD = {60: "COPY", 119: "CUT"}            # hold and move to take several boxes (Shift + Copy: select)
SHIFT, BACK, PLUS, MINUS, WHEEL, VOLUME = 49, 51, 55, 54, 14, 79
# left buttons, top to bottom: 1 instruments (again: the sound, its sequencer, back to the instruments), 2 song, 3 FX,
# 4 the recorder (the tape; again: the selected track zoomed)
KNOBS = range(71, 79)                      # knobs 1-8
STEPS = range(16, 32)                      # step buttons 1-16 (notes)
PADS = range(68, 100)                      # pads, bottom row first
WHITE, RED, PURPLE = 120, 127, 22                      # the Move's light colours (velocity of the light message)


def _shuffled(colours, seed):
    import random
    out = list(colours)
    random.Random(seed).shuffle(out)                 # the same "random" order every time, so a pad keeps its colour
    return out


# the drum pads: bright colours, in a random order; the chromatic pads: pastels, in another random order
DRUM_COLOURS = [16] * 16        # the left 4x4: one bright colour
NOTE_COLOURS = [47] * 16        # the right 4x4: one pastel


class MoveBoard:
    def __init__(self, keys, T):
        self.keys, self.T = keys, T
        self.shift = False
        self.held = set()
        self.notes_down = {}               # pad -> the synth note it's playing
        self.rec_sound = {}                # pad -> the note it is recording into the pattern (from the sound page)

    def __call__(self, msg):
        kind, num, val = msg[0] & 0xF0, msg[1], msg[2]
        if kind == 0x80:
            kind, val = 0x90, 0
        if kind == 0xB0:
            self.cc(num, val)
        elif kind == 0x90:
            self.note(num, val)

    def cc(self, num, val):
        k = self.keys
        if num == SHIFT:
            self.shift = val > 0
            return
        if num in KNOBS or num in (WHEEL, VOLUME):
            step = val - 128 if val > 63 else val
            if not step:
                return
            if num == VOLUME:
                k.put(("SENS", step) if self.shift else ("VOLUME", step))
            elif num == WHEEL:
                k.put(("KNOB", 10, step, False) if self.shift else ("KNOB", 11, step, False))
            else:
                k.put(("KNOB", num - 70, step, self.shift))
            return
        if num in HOLD:
            name = HOLD[num]
            if val and self.shift and name == "COPY":
                k.put("SELECT")
            elif val and self.shift and name == "CUT" and self.T.auto.active():
                k.put("AUTO_CLEAR")                        # the automation page: this setting off every step
            elif val and self.shift and name == "CUT" and self.T.punch.active():
                k.put("PUNCH_CLEAR")                       # the punch FX page: every punch step off
            elif val and not self.shift:
                self.held.add(name)
                k.put(("HOLD", name))
            elif not val and name in self.held:
                self.held.discard(name)
                k.put(("RELEASE", name))
            return
        if not val:
            return
        if num in (PLUS, MINUS):
            k.put(("KNOB", 9, 1 if num == PLUS else -1, self.shift))
        elif num == BACK:
            k.put("QUIT" if self.shift else "BACK")
        elif num == 3 and "CUT" in self.held and self.T.sbrowse.active:
            k.put("SB_REMOVE")                             # Delete + push the wheel in the sample browser: take it out
        elif num in PRESS:
            k.put(PRESS[num][1 if self.shift else 0])

    def note(self, num, val):
        T, e, k = self.T, self.T.engine, self.keys
        if num in STEPS:
            n = num - 15                                   # 1-16
            if T.fx_page == "mixer":                       # the MIXER: step buttons 1-8 mute (Shift: solo) the instruments
                if val and n <= 8:
                    k.put(("ARM%d" if self.shift else "TRACK%d") % n)
                return
            if getattr(T, "song_page", False) and not T.seq_page:
                if val:
                    k.put(("ROW", n, "CUT" in self.held))  # song mode's rows (Delete + a row: take it out)
                return
            if T.seq_page and T.punch.active():
                k.put(("PUNCHSTEP", n, bool(val), self.shift, "CUT" in self.held))
                return
            if T.seq_page and T.auto.active():
                k.put(("AUTOSTEP", n, bool(val), "CUT" in self.held))   # hold: its value; Delete + step: off
                return
            if T.seq_page:
                k.put(("STEP", n, bool(val), self.shift))  # tap: on / off; Shift + taps: select to set
                return
            if (n - 1 in (ARP_ICON, PADS_ICON) and self.shift and T.drum_page and not T.seq_page
                    and (T.synth_shown() or n - 1 == PADS_ICON)
                    and not (T.fx_page or T.inst_page or T.song_page or T.sbrowse.active)):
                if val:
                    k.put("ARP_JUMP" if n - 1 == ARP_ICON else "PADS_JUMP")   # the icons: the arp page, the pads page
                return
            if T.mlfo.active():
                k.put(("LFOSTEP", n, bool(val)))               # the LFO's own steps
                return
            if not val:
                return
            if n <= 8:
                k.put(("ARM%d" if self.shift else "TRACK%d") % n)
            return
        if 0 <= num < 8 and val and self.shift:         # Shift + touch a knob: push it
            k.put("MUTE%d" % (num + 1))
            return
        if num in PADS:
            self.pad(num - PADS[0], val)

    def pad(self, p, vel):
        """The pads play the instrument you're on: a drum machine one drum a pad (bottom row first), a synth
        its scale up the pads."""
        T, e = self.T, self.T.engine
        if e is None or e.slot is None or not e.drums:
            return
        if not vel and p in T.punch.pads_down:
            T.punch.pad(p, vel)                            # a punch FX pad let go (even with Shift held)
            return
        if T.punch.active() and self.shift and p < 16:
            if vel:
                self.keys.put(("PUNCHPAT", p))             # the PUNCH FX page: Shift + pad picks a punch pattern
            return
        if self.shift and p < 16:                          # Shift + pad: the instrument's pattern 1-16
            if vel:
                self.keys.put(("PATTERN", p))
            return
        if T.punch.active() or (not vel and p in T.punch.pads_down):
            T.punch.pad(p, vel)                            # the PUNCH FX page: the pads are effects
            return
        mid = e.slots[e.slot]
        if e.is_synth(mid):
            if vel:
                vel = pad_velocity(T, vel)                 # PADS page: touch (with a curve) or a fixed velocity
            if T.msyn.active() and T.msyn.pad(p, vel):
                return                                     # a setting of selected steps, not a note
            if vel:
                seq = e.seqs.get(mid)
                try:
                    base = seq.note_row(seq.shown_notes()[0])
                    note = seq.row_note(base + p)
                except Exception:
                    note = 48 + p
                note = max(0, min(127, note + 12 * getattr(T, "octave", 0)))
                self.notes_down[p] = note
                if T.live_rec and e.playing and T.drum_page and not T.seq_page and seq is not None:
                    frame = e._heard_frame()                   # recording into the pattern from the sound page
                    try:
                        i = seq.live_place(note, frame, e.frames_per_beat(), vel=vel)
                        self.rec_sound[p] = (i, seq.pattern.notes[i][note], frame, seq)
                        e.seq_changed()
                    except Exception as ex:                    # noqa: BLE001
                        print("pad recording:", ex)
                (T.midi_note if T.drum_page else e.note_on)(note, vel)
            else:
                note = self.notes_down.pop(p, None)
                rec = self.rec_sound.pop(p, None)
                if rec and e.playing:                          # a recorded note lasts as long as you held the pad
                    i, nt, frame, seq = rec
                    with seq.lock:
                        step_frames = e.frames_per_beat() / seq.pattern.steps_per_beat(note)
                        nt.length = max(1, min(64, round((e._heard_frame() - frame) / step_frames)))
                    e.seq_changed()
                if note is not None:
                    (T.midi_note if T.drum_page else lambda n, v: e.note_off(n))(note, 0)
            return
        d = e.drums
        ms = T.mseq
        if ms.active() and ms.held is not None:            # steps selected: the pads are their settings
            if vel:
                self.keys.put(("STEP_PAD", p))
            return
        if vel:
            vel = pad_velocity(T, vel)                     # PADS page: touch (with a curve) or a fixed velocity
        r, c = divmod(p, 8)
        if c < 4:                                          # left 4 x 4: the drums, bottom left first
            lane = r * 4 + c
            if lane >= d.lanes:
                return
            if vel:
                if T.live_rec and e.playing and (T.seq_page or T.drum_page):
                    e.seq.live_place(lane, e._heard_frame(), e.frames_per_beat())
                    e.seq_changed()
                e.hit(lane, vel)
                if lane == 0:                                  # the kick triggers a Ducker on the other instruments
                    for j, ins in list((getattr(e, "insert_fx", None) or {}).items()):
                        if j[0] != e.slot and ins.h and ins.name() == "DUCKER":   # (only it listens: others crashed)
                            ins.midi(0x90, 36, vel)
                voice = d.lane_voice[lane] if lane < len(d.lane_voice) else 0
                T.drum_voice = voice
                T._drum_hits[voice % len(T._drum_hits)] = time.monotonic()
                self.keys.put(("PICK_LANE", lane))
            return
        if not vel:
            ms.chrom.pop(p, None)                          # (a chromatic pad let go)
            return
        if vel:                                            # right 4 x 4: the picked drum, a semitone a pad
            lane = min(T.seqp.lane, d.lanes - 1)
            semis = r * 4 + (c - 4) + 12 * getattr(T, "octave", 0)
            if T.seq_page and ms.active():
                ms.chrom[p] = semis                        # (hold it and tap steps: they get this note)
            locks = ms.pitch_locks(lane, {}, semis)
            if T.seq_page and ms.active() and ms.down and not ms.selected:
                length = e.seq.lane(lane).length               # hold a step + a chromatic pad: that note on that step
                with e.seq.lock:
                    for i in ms.down:
                        if i < length:
                            st = e.seq.step(lane, i)
                            st.on = True
                            st.locks.update(locks)
                e.seq_changed()
                T.say("STEP %s  PITCH %+d" % (",".join(str(i + 1) for i in sorted(ms.down)), semis), 2)
            elif T.live_rec and e.playing and (T.seq_page or T.drum_page):   # recorded with its pitch: the step locks it
                i = e.seq.live_place(lane, e._heard_frame(), e.frames_per_beat())
                with e.seq.lock:
                    e.seq.step(lane, i).locks.update(locks)
                e.seq_changed()
            e._auditions.append((0, lane, vel, locks))


def pattern_seq(T):
    """The shown instrument's sequencer (its patterns), or None."""
    e = T.engine
    if not e or e.slot is None or not e.slots[e.slot]:
        return None
    return e.seqs.get(e.slots[e.slot])


# ---------------------------------------------------------------- lights

# HELLO on the pads at start-up: the letters stand across the 8 columns (a letter's top at the left) and slide
# down the 4 rows, one colour picked at random each start
_ALL = set(range(8))
HELLO_ROWS = ([_ALL, {4}, {4}, {4}, _ALL, set(),                    # H
               _ALL, {0, 4, 7}, {0, 4, 7}, set(),                    # E
               _ALL, {7}, {7}, set(),                                # L
               _ALL, {7}, {7}, set(),                                # L
               set(range(1, 7)), {0, 7}, {0, 7}, {0, 7}, set(range(1, 7))])   # O
HELLO_RATE = 8.0                                                     # rows a second
HELLO_COLOURS = [3, 11, 8, 15, 22]                                   # (orange, green, yellow, teal, purple)
HELLO = {"start": None, "colour": None}


def hello_frame(now):
    """The 32 pad lights of the HELLO animation now, or None once it has gone by."""
    if HELLO["start"] is None:
        import random
        try:                                                         # the external screen's colour family, this start
            import screenview
            colour = screenview.PAD_COLOUR[screenview.FAMILY]
        except Exception:                                            # noqa: BLE001
            colour = random.choice(HELLO_COLOURS)
        HELLO["start"], HELLO["colour"] = now, colour
    k = int((now - HELLO["start"]) * HELLO_RATE)
    if k - 3 >= len(HELLO_ROWS):
        return None
    out = [0] * 32
    for p in range(32):
        r, c = divmod(p, 8)                                          # r: 0 = the bottom row
        i = k - 3 + r                                                # the top row shows the newest
        if 0 <= i < len(HELLO_ROWS) and c in HELLO_ROWS[i]:
            out[p] = HELLO["colour"]
    return out


class Lights:
    """Sends a light's state only when it changes."""

    def __init__(self, core):
        self.core, self.sent = core, {}

    def cc(self, num, on):
        v = 127 if on else 0
        if self.sent.get(("cc", num)) != v:
            self.sent[("cc", num)] = v
            self.core.send_midi(bytes((0xBF, num, v)))

    def note(self, num, v):
        if self.sent.get(("n", num)) != v:
            self.sent[("n", num)] = v
            self.core.send_midi(bytes((0x9F, num, v)))

    def icons(self, which):
        """The icons under the step buttons (controller numbers 16-31): which = a set of 0-15 lit white, or a dict
        {0-15: colour}."""
        for k in range(16):
            v = which.get(k, 0) if isinstance(which, dict) else 120 if k in which else 0
            if self.sent.get(("icon", k)) != v:
                self.sent[("icon", k)] = v
                self.core.send_midi(bytes((0xBF, 16 + k, v)))

    def update(self, T, board):
        e = T.engine
        self.cc(85, T.playing)
        self.cc(86, T.recording or bool(T.live_rec and (T.seq_page or T.drum_page)))
        self.cc(58, bool(e and e.loop_on))
        self.cc(88, bool(e and not e.audible(T.armed - 1)))
        self.cc(49, board.shift)
        page = 41 if T.fx_page else 43 if (T.inst_page or T.drum_page or T.seq_page) else \
            42 if getattr(T, "song_page", False) else 40
        for b in (43, 42, 41, 40):
            self.cc(b, b == page)
        # step buttons: the tracks (the selected one bright), or the sequencer's steps
        syn = T.msyn.active()
        if T.punch.pads_down and not T.punch.active():
            T.punch.leave()                                # (left the page with a pad held)
        seq_lights = T.punch.step_lights() if T.punch.active() else T.auto.step_lights() if T.auto.active() else T.msyn.step_lights() if syn else \
            T.mseq.step_lights() if T.mseq.active() else T.mlfo.step_lights() if T.mlfo.active() else None
        song = getattr(T, "song_page", False) and not T.seq_page and T.song.step_lights()
        flash = getattr(T, "len_flash", None)
        if flash and (time.monotonic() > flash[0] or not (T.seq_page and seq_lights is not None)):
            flash = T.len_flash = None
        for i in range(16):
            v = 0
            if T.fx_page == "mixer":                       # the MIXER: lit = that instrument plays (off: muted or empty)
                v = WHITE if (i < 8 and e and e.slots[i] and i not in e.slot_mutes) else 0
            elif flash:                                      # a length just changed: its steps light purple
                v = PURPLE if flash[1] + i < flash[2] else 0
            elif song:
                v = song[i]
            elif seq_lights is not None:
                v = seq_lights[i]
            elif i < 8:
                sel, armed = i == T.armed - 1, bool(e and i in e.arm_extra)
                v = (RED if not sel or int(time.monotonic() * 2) % 2 else WHITE) if armed else WHITE if sel else 0
            self.note(16 + i, v)
        # pads
        out = [0] * 32
        q = pattern_seq(T)
        if T.punch.active():
            out = T.punch.pad_lights(board.shift)          # (Shift: the punch patterns)
        elif board.shift and q is not None:                # Shift: the patterns (the current one bright)
            for p in range(16):
                pat = q.patterns[p]
                out[p] = 127 if p == q.current else 20 if not pat.empty() else 0
        elif T.auto.active() and not T.synth_shown():
            out = T.auto.pad_lights()
        elif T.msyn.active():
            out = T.msyn.pad_lights()
        elif T.mseq.active() and T.mseq.held is not None:
            out = T.mseq.pad_lights()
        elif e and e.slot is not None and e.drums:
            if e.is_synth(e.slots[e.slot]):
                out = [20] * 32
                try:                                           # the key's root notes light white
                    q = e.seq
                    base = q.note_row(q.shown_notes()[0])
                    for p in range(32):
                        if q.row_note(base + p) % 12 == q.root:
                            out[p] = WHITE
                except Exception:                              # noqa: BLE001
                    pass
            else:
                lanes, picked = e.drums.lanes, T.seqp.lane
                for p in range(32):
                    r, c = divmod(p, 8)
                    if c < 4:                                  # the drums: each its own colour, the picked one white
                        lane = r * 4 + c
                        out[p] = WHITE if lane == picked else DRUM_COLOURS[lane] if lane < lanes else 0
                    else:                                      # the chromatic pads: another set (pastels), roots white
                        k = r * 4 + c - 4
                        out[p] = WHITE if k % 12 == 0 else NOTE_COLOURS[k]
        if not HELLO.get("done"):
            h = hello_frame(time.monotonic())                # start-up: HELLO slides down the pads first
            if h is None:
                HELLO["done"] = True
            else:
                out = h
        for p in range(32):
            self.note(68 + p, out[p])
        # the icons under the step buttons: lit only while Shift is held (as on the Move's own software), on a synth's sound page
        icons = {}
        if board.shift and T.drum_page and not T.seq_page and not (T.fx_page or T.inst_page or T.song_page):
            if T.synth_shown():
                on = bool(getattr(e.seq, "arp_cfg", {}).get("on"))
                icons[ARP_ICON] = 120 if on else 118 if T.mlfo.arp_on_page() else 20
            if e and e.drums and e.slot is not None and e.slots[e.slot]:        # (a drum machine has PADS too)
                icons[PADS_ICON] = 118 if T.mlfo.pads_on_page() else 20
        self.icons(icons)


# ---------------------------------------------------------------- the app

PADS_ICON = 1                     # the hexagon, under step button 2: the pads' key and scale
ARP_ICON = 2                      # the branching-nodes icon, under step button 3 (see MOVE-NOTES.md)
ICONFILE = os.environ.get("CONSOLE_ICONFILE", "/data/UserData/console/icontest")      # touch it: the step icons light one at a time (see icon_test below)


def main():
    other = already_running()
    if other:
        sys.exit("Console is already running on the Move (it starts by itself in console mode). "
                 "Shift + Back on the Move quits it.")
    try:
        with open(PIDFILE, "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass
    crashed = crashlog.start("STRESS TEST, %g MINUTES" % STRESS_MINUTES if STRESS_MINUTES else "")
    import signal

    def stop_signal(*_):
        raise KeyboardInterrupt                      # asked to stop (the launcher): save and quit as Ctrl+C does
    signal.signal(signal.SIGTERM, stop_signal)
    e = audio.Engine()
    e.start()
    crashlog.watch(e)                        # the black box: BOX lines in the crash log
    deadline = time.time() + 15
    while getattr(e, "core", None) is None and time.time() < deadline:
        time.sleep(0.05)
    if getattr(e, "core", None) is None:
        sys.exit("The sound core didn't start: is console mode running? (%s)" % e.status)
    core = e.core
    knobgate.load(os.path.join(os.path.dirname(os.environ["CONSOLE_DATA"]), "knob-sensitivity"))
    e.select_arms = False                            # selecting a track doesn't arm it: Shift + step button does
    screen = ui.Screen.load(os.path.join(APP, "layouts", "main.ui"))
    T = console.Transport(screen, e)
    T.inst_sends = True                              # the FX page: knob 4 is the picked instrument's send
    try:
        T.insfx_boot()                               # the song's insert effects, running straight away (the core came up
    except Exception as ex:                          # noqa: BLE001     before this hook existed, so it couldn't do it)
        print("insert effects:", ex)
    if e:
        import linksync
        T.link = linksync.LinkSync(e)                    # Ableton Link (MENU > SETTINGS > MIDI SYNC > LINK)
    if "SCREEN" not in menu_mod.SETTINGS:
        menu_mod.SETTINGS.append("SCREEN")           # MENU > SETTINGS > EXTERNAL SCREEN: its address as a QR code
    m = menu_mod.Menu(os.path.join(APP, "layouts", "menu.ui"), T)
    m.kits = kitmenu.KitMenu(os.path.join(APP, "layouts", "menu.ui"), T)
    m.kits.main = m
    T.presets = movepresets.Presets(T, m.kits)     # a synth's PRESETS page (its first sound page)
    T.presets_page = True
    kit_turn = m.kits.turn

    def kit_list_turn(delta, k=m.kits):                # the drums menu's list stops at its ends (it wrapped round)
        if k.mode == "list":
            k.choice = max(1, min(kitmenu.ALL - 1, k.choice + delta))   # (not 0: DRUM MACHINE is hidden here)
            k.msg = ""
        else:
            kit_turn(delta)
    m.kits.turn = kit_list_turn
    kit_show = m.kits.show

    def kits_show(k=m.kits):
        kit_show()
        k.choice = max(1, k.choice)                      # (DRUM MACHINE, row 0, isn't offered here)
    m.kits.show = kits_show
    m.open = False                                   # start on the tape, not the project menu
    keys = queue.Queue()
    board = MoveBoard(keys, T)
    T.shift_held = lambda: board.shift
    T.mseq = moveseq.MoveSeq(T)
    T.pagefx = pagefx.PageFX()                       # the page change card (the page's name sliding in)
    T.msyn = movesynth.MoveSynth(T)
    T.mlfo = movelfo.MoveLFO(T)
    T.auto = moveauto.Auto(T)                        # the AUTOMATION page (left button 1 after the sequencer)
    T.auto_page = False                              # True: AUTOMATION; "punch": PUNCH FX (after it)
    T.has_auto_page = True
    T.punch = movepunch.Punch(T)                     # the PUNCH FX page
    T.list_is_top = True                             # left button 1 rounds an instrument's pages; Back: the list
    T.knob_recorded = lambda param: moveauto.record(T, param)   # recording into the pattern: knob moves too
    T.sbrowse = samplebrowse.SampleBrowser(T)
    T.fxpick = fxpicker.FxPicker(T)
    T.live_rec = False
    T.song_page = False
    T.octave = 0                                     # Up / Down on a sound page: the pads' octave
    T.pad_vel = int(e.settings.get("pad_vel", 0)) if e else 0          # 0: as you hit them
    T.pad_curve = max(0, min(2, int(e.settings.get("pad_curve", 1)))) if e else 1
    T.song = movesong.Song(T)
    T.key("DRUMS")                                   # start on left button 1: the instruments
    try:
        import screenview
        screenview.start(T, m)                       # the big screen: http://move.local:8080
    except Exception as ex:                          # noqa: BLE001
        print("Big screen:", ex)
        screenview = None
    if STRESS_MINUTES and stress.MENU:
        import uitest
        st = uitest.UiTest(STRESS_MINUTES, T, m, e, board)       # the menu test: every screen, every control
    else:
        st = stress.Stress(STRESS_MINUTES, T, m, e, board) if STRESS_MINUTES else None
    if st:
        T.say(("MENU TEST: %g MINUTES. SHIFT + BACK STOPS IT" % STRESS_MINUTES if stress.MENU else
               "START-UP CHECK: 8 MIN, ENDS ITSELF. SHIFT + BACK STOPS IT" if stress.STARTUP else
               "SONG INSERT TEST: ABOUT 15 MIN, ENDS ITSELF. SHIFT + BACK STOPS IT" if stress.SONGFX else
               "STRESS TEST: %g MINUTES. SHIFT + BACK STOPS IT" % STRESS_MINUTES), 5)
    elif crashed:
        T.say("CONSOLE CRASHED LAST TIME. SAVED IN CONSOLE/CRASHES: %s" % crashed.upper(), 6)
    frame = Frame()
    intro = opening.Opening()                        # the opening animation, on the screen while it starts
    if st is not None:
        intro.stop()                                 # (not over a test)
    if st is not None and hasattr(st, "watch_frame"):
        st.watch_frame(frame)                        # the menu test: what each screen draws
    lights = Lights(core)
    print("Console on the Move: running. Ctrl+C quits (the song is saved).")
    last = time.monotonic()
    next_screen = 0.0
    next_lights = 0.0
    next_icon_check, icon_test, icon_k = 0.0, None, 0
    hand_back = False
    try:
        while True:
            while True:
                try:
                    board(e.move_midi.get_nowait())
                except queue.Empty:
                    break
            crashlog.alive(time.monotonic())
            if st is not None and not st.tick(time.monotonic()) and not m.restart:
                m.restart = True                          # the test is over: start again as normal
            quit_now = False
            while not keys.empty():
                name = keys.get()
                crashlog.action(name)
                if name == "QUIT":
                    quit_now = True
                    break
                if icon_test is not None:                # the icon test: the wheel steps through the icons
                    if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11 and name[2]:
                        icon_k = (icon_k + (1 if name[2] > 0 else -1)) % 16
                    continue
                T.pagefx.cancel()                         # any control cuts the page card short
                intro.stop()                              # ... and the opening animation
                if st is not None and getattr(st, "catch", False):
                    st.handle(handle, name, T, m, e)      # the menu test: an error is noted, and it goes on
                else:
                    handle(name, T, m, e)
            if m.restart and not quit_now:          # a software update was installed: start the new version
                frame.clear()
                frame.centre(64, 28, "RESTARTING...")
                core.display(frame.bytes())
                break
            if quit_now:
                hand_back = True
                frame.clear()
                frame.centre(64, 28, "SAVING...")
                core.display(frame.bytes())
                break
            now = time.monotonic()
            T.song.tick()
            T.tick(now - last)
            last = now
            e.inst_view = e.inst_view or T.song_page         # the instruments play on the song page too
            if now >= next_icon_check:
                next_icon_check = now + 0.5
                try:                                         # console/stepdim: another colour for an empty step, to try
                    import sequencer as _sq
                    path = os.path.join(os.path.dirname(stress.FLAG), "stepdim")
                    _sq.STEP_IDLE = int(open(path).read().split()[0]) if os.path.exists(path) else 119
                except (OSError, ValueError, IndexError):
                    pass
                try:
                    T.songfx_sync()                          # the song inserts: a copy on every loaded instrument
                except Exception as ex:                      # noqa: BLE001
                    print("song inserts:", ex)
                try:
                    mode = open(ICONFILE).read().strip().lower() if os.path.exists(ICONFILE) else None
                except OSError:
                    mode = None
                if mode is None and icon_test is not None:
                    lights.icons(set())                      # finished: the icons go dark
                icon_test = mode
                if st is None and os.path.exists(stress.FLAG) and not m.restart:
                    T.say("STRESS TEST: RESTARTING INTO IT", 3)
                    m.restart = True                         # (it starts with the app: see stress.py)
            if icon_test is not None:
                # the icon test: turn the wheel to step through the icons (or all of them: put "all" in the file)
                k = icon_k
                lit = set(range(16)) if icon_test == "all" else {k}
                lights.icons(lit)
                if now >= next_screen:
                    next_screen = now + 1 / FPS_SCREEN
                    frame.clear()
                    frame.rect(0, 0, W, 9, 1)
                    frame.text(1, 1, "ICON TEST", 0)
                    frame.centre(64, 20, "ALL ON" if icon_test == "all" else "ICON %d OF 16" % (k + 1))
                    frame.small(1, 40, "UNDER STEP BUTTON %s" % ("1-16" if icon_test == "all" else k + 1))
                    frame.small(1, 52, "TURN THE WHEEL. DELETE FILE TO END")
                    core.display(frame.bytes())
                time.sleep(0.005)
                continue
            if now >= next_screen:
                next_screen = now + 1 / FPS_SCREEN
                menu_tick(m)
                if T.live_rec and (not (T.seq_page or T.drum_page) or (getattr(T, "_rec_was_playing", False) and not e.playing)):
                    T.live_rec = False                        # recording into the pattern ends at Stop, or when you leave the page
                    T.say("PATTERN RECORDING OFF", 2)
                T._rec_was_playing = bool(e.playing)
                if T.sbrowse.active and (T.seq_page or T.fx_page or T.inst_page or T.song_page or not T.drum_page):
                    T.sbrowse.close(False)                # (went to another page: the sample browser closes, the old sample stays)
                T.pagefx.update(T, m)
                drew_at = time.monotonic()
                if not intro.draw(frame, drew_at):
                    pages.draw(frame, T, m)
                if st is not None and hasattr(st, "drawn"):
                    st.drawn(frame, time.monotonic() - drew_at)
                if screenview is not None:
                    screenview.frame(frame)                   # (a copy for the big screen, if one is open)
                if st is not None:                            # the stress test: the time left, bottom right
                    left = st.left()
                    frame.rect(99, 57, 29, 7, 1)
                    frame.small(100, 58, "T%3d:%02d" % (left // 60, left % 60), 0)
                core.display(frame.bytes())
            if now >= next_lights:
                next_lights = now + 0.03
                lights.update(T, board)
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        failed = sys.exc_info()[0] is not None
        T.playing = False
        if st is not None:
            st.finish("stopped early" if not failed else "Console hit a Python error (see console/crashes)")
        e.save(wait=True)
        frame.clear()
        core.display(frame.bytes())
        time.sleep(0.1)
        e.stop()
        time.sleep(0.2)
        print("Saved. Bye.")
        if not failed:
            crashlog.done()                          # a normal quit: this run's crash log isn't needed
        if hand_back:                                # Shift + Back: back to the normal Move (see RNBOLauncher)
            try:
                open("/data/UserData/console/STOP", "w").close()
                print("Handing the Move back.")
            except OSError as ex:
                print("Couldn't hand the Move back (%s)" % ex)
        elif m.restart:
            print("Restarting with the new version...")
            sys.exit(moveupdater.RESTART_CODE)


def menus_open(m):
    return bool(m.open or m.kits.open)


CURVES = ("SOFT", "NORMAL", "HARD")


def pad_velocity(T, vel):
    """The velocity a pad plays and records: fixed (PADS page, knob 4), or what you hit through a curve (knob 5)."""
    fixed = getattr(T, "pad_vel", 0)
    if fixed:
        return fixed
    g = (0.7, 1.0, 1.5)[getattr(T, "pad_curve", 1)]
    return max(1, min(127, int(round(127 * (vel / 127.0) ** g))))


def choice_knob(T, m, e, name):
    """True for a knob that picks from a list or a mode (they count their own clicks, see knobgate), and in the
    menus; the rest are numbers and get the global knob speed."""
    n = name[1]
    if m.open or m.kits.open:
        return True
    if getattr(T, "song_page", False) and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        return True
    if T.focus.track is not None and n <= 3 and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        return True
    if not (e and e.drums):
        return False
    if T.msyn.active():
        return T.msyn.is_choice_knob(n)
    if T.mlfo.active():
        return T.mlfo.is_choice(n)
    if T.fx_page:
        return n == 1 and T.fx_page == "delay"                              # the delay's TIME steps through note lengths
    if T.auto.active() or T.punch.active():
        return True                                            # (the automation page counts its own clicks)
    ms = T.mseq
    if T.seq_page and ms.active():
        if ms.selected:
            if n == 2 and ms.sel is not None:
                return ms.pad_items()[ms.sel][0] in moveseq.CKEYS     # (its chance: counted in set_chance)
            if n == 1 and ms.sel is not None:
                key = ms.pad_items()[ms.sel][0]
                return (key not in ("vel", "chance")) if isinstance(key, str) else knobgate.is_choice(e.drums, key)
            return ms.sel is None and ms.lock_choice(n)          # (the sound page's knobs: a mode counts its clicks)
        return n == 2                                          # the lane's RATE
    if T.drum_page and not (T.fx_page or T.inst_page):
        pages = T.drum_pages()
        params = pages[min(T.drum_tab, len(pages) - 1)][1]
        return n <= len(params) and knobgate.is_choice(e.drums, params[n - 1])
    return False


def menu_tick(m):
    """The Pi redraws the settings each frame (menu.draw), which keeps SOFTWARE UPDATE's row current and
    restarts after an install; the Move never calls draw, so this does that part."""
    if not m.open or getattr(m, "mode", None) not in ("settings", "wifi"):
        return
    m.refresh()
    u = getattr(m, "updater", None)
    if m.mode == "settings" and u and u.state == "done" and not u.needs_setup:
        if getattr(m, "_done_at", None) is None:
            m._done_at = time.monotonic()
        elif time.monotonic() - m._done_at > 2.0:
            m.restart = True


def handle(name, T, m, e):
    """One action, the way the Pi app's main loop does it (menus first), plus the Move's own."""
    if isinstance(name, tuple) and name[0] == "VOLUME":
        T.phones_volume(name[1] * 0.02)
        return
    if isinstance(name, tuple) and name[0] == "SENS":        # Shift + the volume knob: how many clicks a step takes
        v = knobgate.set_speed(knobgate.SPEED + (1 if name[1] > 0 else -1) * (1 if abs(name[1]) < 3 else 2))
        T.say("KNOB SPEED: %d CLICK%s A STEP" % (v, "" if v == 1 else "S"), 3)
        return
    ms = T.mseq
    sb = T.sbrowse
    fp = T.fxpick
    if name == "REWIND":                               # Shift + Play: back to the start (the loop's), from any page
        if fp.active or sb.active or m.open or m.kits.open:
            name = "HOME"                              # (in a list it still chooses, as before)
        else:
            start = e.loop_a / e.frames_per_beat() if (e and e.loop_on and e.loop_region()) else 0.0
            T.set_pos(start if T.tape.pos > start + 1e-6 else 0.0)
            return
    if fp.active:                                      # the effect picker has the wheel and Back
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11:
            fp.turn(name[2])
            return
        if name in ("HOME", "PLAY"):
            fp.push()
            return
        if name in ("BACK", "FILE", "DRUMS_BACK"):
            fp.back()
            return
    elif name == "HOME" and T.mlfo.active() and T.mlfo.insert_pos() is not None and not (m.open or m.kits.open):
        fp.open(T.insfx(None, T.mlfo.insert_pos()))    # push the wheel on an INSERT page: choose its effect
        return
    elif name == "HOME" and T.fx_page in ("song1", "song2") and not (m.open or m.kits.open):
        fp.open(T.songfx(0 if T.fx_page == "song1" else 1))   # push the wheel on SONG INSERT 1 / 2: choose it
        return
    elif (T.fx_page and not (m.open or m.kits.open) and isinstance(name, tuple) and name[0] == "KNOB"
          and name[1] == 11 and name[2]):                # the wheel on the FX pages: the next / previous one
        order = ["mixer", "reverb", "delay"] + (["song1", "song2"] if T.insert_fx_available() else [])
        way = 1 if name[2] > 0 else -1                   # (one page a click, as the wheel moves through lists)
        if T.fx_page in order:
            T.fx_page = order[max(0, min(len(order) - 1, order.index(T.fx_page) + way))]   # (stops at the ends)
        return
    if isinstance(name, tuple) and name[0] == "PICK_LANE" and sb.active and e and e.drums:
        lv = getattr(e.drums, "lane_voice", ())          # another drum's pad: its sample list (the old one is put back)
        voice = lv[name[1]] if name[1] < len(lv) else sb.voice
        if voice != sb.voice:
            sb.close(False)
            sb.open(e.drums, voice)
    if sb.active and (T.seq_page or T.fx_page or T.inst_page or T.song_page or not T.drum_page):
        sb.close(False)                                # (it is not on this page: it must not keep the wheel)
    if sb.active:                                      # the sample browser has the wheel and Back
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11:
            sb.turn(name[2])
            return
        if name in ("HOME", "PLAY"):
            sb.push()
            return
        if name == "SB_REMOVE":
            sb.remove()
            return
        if name in ("BACK", "FILE", "DRUMS_BACK"):
            sb.back()
            return
    elif (name == "HOME" and T.drum_page and e and e.drums and (getattr(e.drums, "id", "") == "sampler"
                                                                or getattr(e.drums, "sample_param_index", None) is not None)
          and not (T.seq_page or T.fx_page or T.inst_page or T.song_page or m.open or m.kits.open)
          and not T.mlfo.active()):                    # (its sound page only: not LFO, INSERT, SENDS, ARP, PADS)
        sb.open(e.drums, T.drum_voice)                 # push the wheel on a sampler drum: choose its sample
        return
    pr = T.presets
    if pr.orig is not None and not pr.on_page():
        pr.leave()                                     # (off the PRESETS page while trying them: kept)
    if pr.on_page() and not (m.open or m.kits.open or fp.active or sb.active):
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11:
            pr.turn(name[2])                           # the wheel: the presets (heard as you land on them)
            return
        if name == "HOME":
            pr.keep()
            return
        if name == "BACK" and pr.back():
            return
        if isinstance(name, tuple) and name[0] == "KNOB" and 1 <= name[1] <= 8:
            pr.knob(name[1], name[2])                  # knob 1: the bank
            return
        if name in ("LEFT", "RIGHT"):
            pr.leave()
    if isinstance(name, tuple) and name[0] == "KNOB" and 1 <= name[1] <= 8 and not choice_knob(T, m, e, name):
        way = knobgate.numeric(("num", name[1], name[3]), name[2])    # every number knob: SPEED clicks a step
        if not way:
            return
        name = ("KNOB", name[1], way, name[3])
    on_sound = T.drum_page and not (T.seq_page or T.fx_page or T.inst_page or T.song_page or m.open or m.kits.open)
    if on_sound and e and e.drums:
        last = len(T.drum_pages()) - 1
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11:       # the big wheel turns the pages
            way = knobgate.gate(("wheel-pages",), name[2], False, 1)
            if not way:
                return
            name = "RIGHT" if way > 0 else "LEFT"
        if name in ("LEFT", "RIGHT") or (isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 9 and name[3]):
            if T.mlfo.arrows(1 if name == "RIGHT" else -1, last):
                return
        if T.mlfo.active() and isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8:
            T.mlfo.knob(name[1], name[2], name[3])
            return
        # a sound page: Up / Down (+ / -) are the pads' octave (as on the Move); Left / Right the settings pages
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 9 and not name[3]:
            T.octave = max(-4, min(4, T.octave + (1 if name[2] > 0 else -1)))
            T.say("OCTAVE %s" % ("%+d" % T.octave if T.octave else "0"), 2)
            return
        if name in ("LEFT", "RIGHT"):
            name = ("KNOB", 9, 1 if name == "RIGHT" else -1, False)
    if (name == "RECORD" and (T.seq_page or T.drum_page) and not menus_open(m) and e and e.drums
            and e.slot is not None and not (T.fx_page or T.inst_page)):
        T.live_rec = not T.live_rec                  # on an instrument's pages: pads and knob moves go into the pattern
        T.say("RECORDING INTO THE PATTERN: PADS AND KNOBS" if T.live_rec else "PATTERN RECORDING OFF", 2)
        return
    if name == "RECORD" and e and not T.recording and not e.record_tracks():
        T.say("ARM A TRACK FIRST: SHIFT + STEP BUTTON", 3)
        return
    if isinstance(name, tuple) and name[0] == "KNOB" and not (m.open or m.kits.open):
        n = name[1]
        zoomed = T.focus.track is not None and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page
                                                    or T.song_page)
        if (zoomed and n <= 3) or n == 10:
            # a mode or a list (mono / stereo, the input, the grid, the pattern): several clicks per choice
            way = knobgate.gate(("knob", n, zoomed), name[2], False)
            if not way:
                return
            name = ("KNOB", n, way, name[3])
    if (isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8 and T.drum_page and not (
            T.seq_page or T.fx_page or T.inst_page or m.open or m.kits.open) and e and e.drums):
        # a setting that picks a mode (DIST, CHOKE...): several clicks per choice
        pages = T.drum_pages()
        params = pages[min(T.drum_tab, len(pages) - 1)][1]
        if name[1] <= len(params) and knobgate.is_choice(e.drums, params[name[1] - 1]):
            way = knobgate.gate(("drum", params[name[1] - 1]), name[2], name[3])
            if not way:
                return
            name = ("KNOB", name[1], way, True)          # one choice (as with Shift: no speeding up)
    if isinstance(name, tuple) and name[0] == "AUTOSTEP":
        if T.auto.active():
            T.auto.step(name[1], name[2], name[3])
        return
    if name == "AUTO_CLEAR":
        if T.auto.active():
            T.auto.clear()
        return
    if isinstance(name, tuple) and name[0] == "PUNCHSTEP":
        if T.punch.active():
            T.punch.step(name[1], name[2], name[3], name[4])
        return
    if name == "PUNCH_CLEAR":
        if T.punch.active():
            T.punch.clear()
        return
    if isinstance(name, tuple) and name[0] == "STEP":
        if ms.active():
            ms.step(name[1], name[2], name[3])
        elif T.msyn.active():
            T.msyn.step(name[1], name[2], name[3])
        return
    if name == "ARP_JUMP":
        T.mlfo.goto_arp()
        return
    if name == "PADS_JUMP":
        T.mlfo.goto_pads()
        return
    if isinstance(name, tuple) and name[0] == "LFOSTEP":
        if T.mlfo.active():
            T.mlfo.step(name[1], name[2])
        return
    if isinstance(name, tuple) and name[0] == "STEP_PAD":
        if ms.active():
            ms.step_pad(name[1])
        return
    if isinstance(name, tuple) and name[0] == "PICK_LANE":
        if ms.held is None and e and e.drums and name[1] < e.drums.lanes:
            changed = T.seqp.lane != name[1]
            T.seqp.lane = name[1]
            T.drum_voice = T.seqp.voice()
            if changed and T.auto.active():
                T.auto.lane_changed()
        return
    if isinstance(name, tuple) and name[0] == "PATTERN":
        q = pattern_seq(T)
        if q is not None:
            q.choose_pattern(name[1], e.playing)
            e.seq_changed()
            T.say("PATTERN %d%s" % (name[1] + 1, "  (NEXT)" if e.playing and q.queued is not None else ""), 2)
        return
    if isinstance(name, tuple) and name[0] == "PUNCHPAT":
        if T.punch.active():
            T.punch.pattern_pad(name[1])
        return
    if isinstance(name, tuple) and name[0] == "ROW":
        T.song.row_button(name[1], name[2])
        return
    menus = m.open or m.kits.open
    if T.song_page and not menus and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8:
            T.song.knob(name[1], name[2], T.shift_held())    # (Shift: the instruments' punch FX patterns)
            return
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 9:
            T.song.set_on(name[2] > 0)                     # +: song mode on, -: off
            return
    if name == "SONG_TOGGLE":                          # Shift + left button 2: song mode on / off, from any page
        T.song.toggle()
        return
    if name == "SONG" and not menus:                 # left button 2: song mode
        for _ in range(4):
            if T.seq_page or T.drum_page or T.inst_page:
                T.key("DRUMS_BACK")
        T.fx_page = None
        if T.focus.track is not None:
            T.key("FOCUS")
        T.song_page = True
        return
    if name in ("DRUMS", "FX", "DRUMS_BACK"):
        T.song_page = False
    if name == "DRUMS" and T.drum_page and not T.fx_page and not (m.open or m.kits.open):
        # an instrument's pages round: sound -> sequencer -> automation -> sound (ARP: Shift + step 3)
        if T.seq_page and getattr(T, "auto_page", False) is True:
            T.auto_page = "punch"                        # automation -> punch FX
            T.punch.page = 0
            return
        if T.seq_page and getattr(T, "auto_page", False):
            T.punch.leave()
            T.auto_page = T.seq_page = False
            T.seqp.held, T.synthp.held = {}, {}
            T.mlfo.tab = None
            return
    if T.punch.active() and not (m.open or m.kits.open) and T.fx_page is None:
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8:
            T.punch.knob(name[1], name[2], name[3])
            return
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11:
            way = knobgate.gate(("wheel-pages",), name[2], False, 1)
            if way:
                T.punch.arrows(way)
            return
        if name in ("LEFT", "RIGHT"):
            T.punch.arrows(-1 if name == "LEFT" else 1)
            return
    if T.auto.active() and not (m.open or m.kits.open) and T.fx_page is None:
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8:
            T.auto.knob(name[1], name[2], name[3])
            return
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11:
            way = knobgate.gate(("wheel-pages",), name[2], False, 1)
            if way:
                T.auto.arrows(way)
            return
        if name in ("LEFT", "RIGHT"):
            T.auto.arrows(-1 if name == "LEFT" else 1)
            return
    seqm = T.msyn if T.msyn.active() else ms if ms.active() else None
    if seqm is not None and seqm.selected and not (m.open or m.kits.open) and T.fx_page is None:
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11 and seqm.sel is not None:
            seqm.knob(1, name[2], name[3])               # steps selected, a setting picked: the big wheel is knob 1
            return
        if name == "HOME":
            seqm.selected, seqm.sel = [], None           # push the big wheel: finished setting the steps
            return
    if (isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11 and (T.msyn.active() or ms.active())
            and not (m.open or m.kits.open) and T.fx_page is None):
        way = knobgate.gate(("wheel-pages",), name[2], False, 1)       # the big wheel: the 16-step pages
        if not way:
            return
        name = "RIGHT" if way > 0 else "LEFT"
    if T.msyn.active() and not (m.open or m.kits.open) and T.fx_page is None:
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8:
            T.msyn.knob(name[1], name[2], name[3])
            return
        if T.msyn.selected and isinstance(name, str) and re.match(r"^MUTE[1-8]$", name):
            T.msyn.unlock_knob(int(name[4:]))           # Shift + touch a knob: its lock off the selected steps
            return
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 9:
            T.msyn.plus_minus(1 if name[2] > 0 else -1)
            return
        if name in ("LEFT", "RIGHT"):
            T.msyn.arrows(-1 if name == "LEFT" else 1)
            return
    if ms.active() and not (m.open or m.kits.open) and T.fx_page is None:
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] <= 8:
            ms.knob(name[1], name[2], name[3])
            return
        if ms.selected and isinstance(name, str) and re.match(r"^MUTE[1-8]$", name):
            ms.unlock_knob(int(name[4:]))                # Shift + touch a knob: its lock off the selected steps
            return
        if isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 9:
            ms.plus_minus(1 if name[2] > 0 else -1)
            return
        if name in ("LEFT", "RIGHT"):
            ms.arrows(-1 if name == "LEFT" else 1)
            return
    if name == "TAPE":                               # left button 4: the recorder; again: the track zoomed
        m.open = False
        m.kits.open = False
        on_tape = not (T.song_page or T.seq_page or T.drum_page or T.inst_page or T.fx_page)
        T.song_page = False
        for _ in range(4):
            if T.seq_page or T.drum_page or T.inst_page:
                T.key("DRUMS_BACK")
        T.fx_page = None
        if on_tape:
            T.key("FOCUS")                           # zoom in, or (zoomed) back out
        elif T.focus.track is not None:
            T.key("FOCUS")
        return
    if name == "BACK":
        if m.open:
            m.key("FILE")
        elif m.kits.open:
            m.kits.key("FILE")
        elif T.fx_page:
            T.fx_page = None                         # the FX pages: back to the page under them
        elif T.inst_page and T.instp.mode:
            T.instp.cancel()
        elif T.inst_page and not (T.seq_page or T.drum_page):
            pass                                     # the instruments page is a top page: Back does nothing
        elif T.seq_page or T.drum_page or T.inst_page:
            T.key("DRUMS_BACK")
        elif T.fx_page:
            T.fx_page = None
        elif T.song_page:
            pass                                     # (song mode is a top page too)
        elif T.focus.track is not None:
            T.key("FOCUS")
        return
    if (m.open or m.kits.open) and isinstance(name, tuple) and name[0] in ("HOLD", "RELEASE"):
        if name[0] == "HOLD":
            (m if m.open else m.kits).key(name[1])
    elif m.open:
        if getattr(m, "mode", "") == "name" and name in ("HOME", "HOME_PUSH_SHIFT"):
            name = "RIGHT" if name == "HOME" else "LEFT"           # naming: the wheel's push goes to the next letter, PLAY saves
        elif getattr(m, "mode", "") == "list" and name == "HOME_PUSH_SHIFT":
            name = "DELETE_MODE" if m.choice == 0 else "RENAME_MODE"   # Shift + push: NEW -> DELETE PROJECT, SAVE -> RENAME PROJECT
        m.key("PLAY" if name == "HOME" else name)    # pushing the wheel chooses, as PLAY does
    elif m.kits.open:
        if m.kits.mode == "list" and name in ("LEFT", "RIGHT", "BAR_LEFT", "BAR_RIGHT"):
            return                                   # (the Pi's two columns: here it's one list)
        if m.kits.mode == "name" and name in ("HOME", "HOME_PUSH_SHIFT"):
            name = "RIGHT" if name == "HOME" else "LEFT"           # naming a kit: push = next letter, PLAY saves
        m.kits.key("PLAY" if name == "HOME" else name)
    elif name == "FILE" and T.inst_page and T.instp.mode:
        T.instp.cancel()
    elif name == "FILE" and T.drum_page:
        m.kits.show()
    elif name == "FILE":
        m.show()
    elif not tape_only_elsewhere(T, name):
        T.key(name)


TAPE_EDITS = {"ARM_ALL", "MUTE", "SOLO", "VOL_UP", "VOL_DOWN", "PAN_LEFT", "PAN_RIGHT", "FOCUS", "INPUT",
              "BAR_LEFT", "BAR_RIGHT", "LOOP_IN", "LOOP_OUT", "CLEAR_REGION", "HOME", "HOME_PUSH_SHIFT",
              "GRID", "ZOOM_IN", "ZOOM_OUT", "ZOOM_RESET", "SWEEP_UNDO", "SELECT", "COPY", "CUT", "DROP",
              "DROP_INSERT", "SPLICE", "SPLICE_ALL", "UNDO", "LEFT", "RIGHT"}


def tape_only_elsewhere(T, name):
    """True for a tape control pressed while you're not on the tape (an instrument's pages, the instruments list,
    song mode, FX): it does nothing there. (Brian: no touching the tape unless you're in the tape section.) Play,
    Record, Loop and overdub still work everywhere; a page's own use of a control is kept: the instruments list's
    step buttons (mute a slot), the sequencer's Undo and arrows, a knob push on a sound page (its default)."""
    if not (T.song_page or T.seq_page or T.drum_page or T.inst_page or T.fx_page):
        return False                                           # on the tape: everything goes
    inst = T.inst_page and not T.fx_page and not T.drum_page and not T.seq_page
    if isinstance(name, tuple):
        if name[0] in ("HOLD", "RELEASE"):
            return name[0] == "HOLD"                             # Copy / Delete held: a tape selection
        if name[0] == "KNOB":
            n = name[1]
            handled = (T.fx_page or T.inst_page or (T.seq_page and n <= 10) or (T.drum_page and n <= 9))
            return not handled                                   # (else: the tape's volumes, zoom, grid, playhead)
        return False
    if re.match(r"^(TRACK|ARM)\d+$", name):
        return not (inst or T.fx_page == "mixer")                # select / arm a tape track (the MIXER: mute / solo)
    if re.match(r"^(MUTE|SOLO)\d+$", name):                    # Shift + touch a knob
        return not (inst or T.full_drum_page() or (T.seq_page and name == "MUTE1"))
    if name in ("MUTE", "SOLO") and inst:
        return False
    if name == "UNDO" and T.seq_page:
        return False                                             # the sequencer's own undo
    if name in ("LEFT", "RIGHT") and T.seq_page:
        return False                                             # the sequencer's box / rows
    if name in ("LOOP_IN", "LOOP_OUT") and T.seq_page and T.synth_shown():
        return False                                             # the synth sequencer: a row at a time
    if name in ("HOME", "HOME_PUSH_SHIFT") and inst:
        return False                                             # the instruments list: push the wheel
    return name in TAPE_EDITS


if __name__ == "__main__":
    main()
