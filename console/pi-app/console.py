#!/usr/bin/env python3
"""Console: the Pi app (version 0.4).

An 8-track tape recorder. The playhead stays in the middle and the tape moves
past it. Records from a USB audio device (an OP-XY in 8-channel mode records
all 8 tracks at once), plays back through it, follows the OP-XY's tempo and
play/stop over MIDI, and edits the tape: loop, lift, drop, cut, splice, undo.

Controls come from the control board (USB MIDI) or a keyboard: a keyboard
plugged into the Pi, or keys typed into the SSH terminal running the app. See
CONTROLS.md for the full list.

Options:
    --window     open a 1280x400 window instead of full screen (for testing on a laptop)
    --rotate N   turn the picture by N degrees (90 or 270) when the screen is upright
                 and the system isn't rotating it; the default is 270
    --demo       no audio engine: made-up waveforms
"""
import re
import argparse
import json
import math
import os
import queue
import sys
import threading
import time


def startup(what):
    """How far into the boot each start-up step is (journalctl -b -u console shows them)."""
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
    except (OSError, ValueError):
        return
    print("startup: %-28s %5.2f s after power-on" % (what, up), flush=True)


startup("app starting")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # pygame mustn't open a sound device: the audio engine owns them
import pygame

import drumparams
import effects
import focus
import kitmenu
import menu
import seqpage
import sequencer
import tape
import ui

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30
BPM = 120.0

# ---------------------------------------------------------------- keyboard: typed characters -> actions

CHAR_ACTIONS = {
    " ": "PLAY", "r": "RECORD", "R": "RECORD", "q": "QUIT", "Q": "QUIT",
    "g": "GRID", "G": "GRID", "+": "ZOOM_IN", "=": "ZOOM_IN", "-": "ZOOM_OUT", "_": "ZOOM_OUT",
    "[": "BAR_LEFT", "]": "BAR_RIGHT", "i": "INPUT", "I": "INPUT", "e": "EXPORT", "E": "EXPORT",
    "l": "LOOP", "L": "LOOP", "{": "LOOP_IN", "}": "LOOP_OUT", "k": "CLEAR_REGION", "K": "CLEAR_REGION",
    "c": "COPY", "C": "COPY", "v": "DROP", "V": "DROP_INSERT", "x": "CUT", "X": "CUT",
    "s": "SPLICE", "S": "SPLICE_ALL", "a": "SELECT", "A": "SELECT", "u": "UNDO", "U": "UNDO", "m": "MUTE", "M": "SOLO",
    "o": "REC_MODE", "O": "REC_MODE", "f": "FOCUS", "F": "FOCUS",
    "9": "VOL_DOWN", "0": "VOL_UP", "(": "PHONES_DOWN", ")": "PHONES_UP", "h": "HOME", "H": "HOME", "`": "ARM_ALL", "~": "ARM_ALL",
    "b": "BOUNCE", "B": "BOUNCE", "w": "FX", "W": "FX", "d": "DRUMS", "D": "DRUMS_BACK", ",": "PAN_LEFT", "<": "PAN_LEFT", ".": "PAN_RIGHT", ">": "PAN_RIGHT",
}
for _n, _ch in enumerate("!@#$%^&*", 1):              # Shift+1..8 on a US keyboard
    CHAR_ACTIONS[_ch] = "ARM%d" % _n
for _n in range(1, 9):
    CHAR_ACTIONS[str(_n)] = "TRACK%d" % _n
CHAR_ACTIONS.update({"\r": "ENTER", "\n": "ENTER", "\t": "FILE"})
ESCAPES = {"\x1b[C": "RIGHT", "\x1b[D": "LEFT", "\x1b[1;2C": "BAR_RIGHT", "\x1b[1;2D": "BAR_LEFT",
           "\x1b[A": "UP", "\x1b[B": "DOWN", "\x1b": "FILE"}
TEXT_INPUT = {"on": False}      # while typing a name, keys arrive as ("CHAR", letter) instead of commands


def start_terminal_keys(q):
    """Read key presses from the terminal (when run over SSH) and put action names on the queue."""
    if not sys.stdin.isatty() or os.environ.get("CONSOLE_NO_TERMINAL_KEYS"):
        return None
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def reader():
        while True:
            try:
                data = os.read(fd, 16).decode(errors="ignore")
            except OSError:
                return
            if not data:
                return
            if data in ESCAPES and not (TEXT_INPUT["on"] and data == "\x1b"):
                q.put(ESCAPES[data])
                continue
            for ch in data:
                if TEXT_INPUT["on"]:
                    q.put(("CHAR", ch))
                elif ch in CHAR_ACTIONS:
                    q.put(CHAR_ACTIONS[ch])

    threading.Thread(target=reader, daemon=True).start()
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def pygame_key(ev):
    """A pygame key press -> action name, ("CHAR", letter) while typing, or None."""
    shift = ev.mod & pygame.KMOD_SHIFT
    if ev.key == pygame.K_LEFT:
        return "BAR_LEFT" if shift else "LEFT"
    if ev.key == pygame.K_RIGHT:
        return "BAR_RIGHT" if shift else "RIGHT"
    if ev.key == pygame.K_UP:
        return "UP"
    if ev.key == pygame.K_DOWN:
        return "DOWN"
    if TEXT_INPUT["on"]:
        if ev.key == pygame.K_ESCAPE:
            return ("CHAR", "\x1b")
        return ("CHAR", ev.unicode) if ev.unicode else None
    if ev.key == pygame.K_ESCAPE:
        return "FILE"
    return CHAR_ACTIONS.get(ev.unicode) if ev.unicode else None


# ---------------------------------------------------------------- control board (MIDI from the firmware)

# key notes 0-23 = SW1-SW24, in keycap order
BOARD_KEYS = ["INPUT", "DRUMS", "FX", "FILE", "SPLICE", "CUT", "LIFT", "DROP",
              "LOOP", "IMPORT", "EXPORT", "RECORD", "SHIFT", "PLAY", "LEFT", "RIGHT"] + \
             ["TRACK%d" % n for n in range(1, 9)]
BOARD_KEYS[6] = "COPY"                # the LIFT key copies (lifts a copy off the tape)
WITH_SHIFT = {"LEFT": "LOOP_IN", "RIGHT": "LOOP_OUT", "CUT": "UNDO", "COPY": "SELECT",
              "DROP": "DROP_INSERT", "SPLICE": "SPLICE_ALL", "PLAY": "HOME", "RECORD": "REC_MODE",
              "LOOP": "CLEAR_REGION", "INPUT": "ARM_ALL", "EXPORT": "BOUNCE", "DRUMS": "DRUMS_BACK"}
# knob pushes: notes 32-42 = ENC1-ENC11
HOLD_KEYS = ("COPY", "CUT")            # hold one and move to take several pieces; let go to copy / cut
PUSHES = ["MUTE%d" % n for n in range(1, 9)] + ["ZOOM_RESET", "LOOP", "HOME"]


def mix_pan_text(p):
    """-1..1 as C, L25, R50..."""
    return "C" if abs(p) < 0.02 else ("L%d" % round(-p * 100) if p < 0 else "R%d" % round(p * 100))


class Board:
    """Turns control board MIDI into actions, keeping track of SHIFT."""

    def __init__(self, q):
        self.q = q
        self.shift = False
        self.held = set()                  # hold keys pressed without SHIFT, waiting for their release
        self.pads = None                   # Transport.pad: plays the drum synth straight from this thread
        self.seq_page = lambda: False      # True on the sequencer page: track keys go to it, pressed and let go
        self.heard = lambda: 0             # the sequencer's clock now (for live recording into the sequencer)
        self.banked = lambda: False        # True when the drum machine has more than 8 lanes (SHIFT: 9-16)
        self.seq_pads = None               # Transport.seq_pad: the sequencer page's key sound
        self.pad_release = None            # Transport.pad_release: a synth's key let go on its sound page

    def __call__(self, kind, number, value):       # runs in the MIDI thread
        if kind == "note":
            if 0 <= number < len(BOARD_KEYS):
                name = BOARD_KEYS[number]
                if name == "SHIFT":
                    self.shift = bool(value)
                    return
                if name.startswith("TRACK") and self.seq_page():
                    # the sequencer: the drum keys pick and place (with SHIFT, a step of the picked lane's box)
                    n = int(name[5:])
                    if value and self.seq_pads:
                        self.seq_pads(n, self.shift)      # heard straight away
                    self.q.put(("LANE", n, bool(value), self.heard(), self.shift))
                    return
                if name in HOLD_KEYS and (not value or not self.shift):
                    if value:
                        self.held.add(name)
                        self.q.put(("HOLD", name))
                    elif name in self.held:
                        self.held.discard(name)
                        self.q.put(("RELEASE", name))
                    return
                if not value:
                    if name.startswith("TRACK") and self.pad_release:
                        self.pad_release(int(name[5:]))   # a synth's note stops when its key is let go
                    return
                if name.startswith("TRACK") and self.pads and self.pads(int(name[5:]), self.shift):
                    return                                # a drum pad: played already, nothing else to do
                if self.shift:
                    if name.startswith("TRACK"):
                        name = "ARM" + name[5:]           # SHIFT+track: arm / disarm it as well
                    else:
                        name = WITH_SHIFT.get(name, name)
                self.q.put(name)
            elif 32 <= number < 32 + len(PUSHES) and value:
                name = PUSHES[number - 32]
                if self.shift and name.startswith("MUTE"):
                    name = "SOLO" + name[4:]          # SHIFT + push a track knob: solo
                elif self.shift and name == "HOME":
                    name = "HOME_PUSH_SHIFT"          # SHIFT + push knob 11 (HOME otherwise)
                elif self.shift and name == "ZOOM_RESET":
                    name = "SWEEP_UNDO"               # SHIFT + push knob 9: undo the in/out sweep
                self.q.put(name)
        elif kind == "cc" and 1 <= number <= 11:
            delta = value - 64
            if delta:
                self.q.put(("KNOB", number, delta, self.shift))


def drums_mod():
    import drums
    return drums


# ---------------------------------------------------------------- the recorder's state

class Transport:
    """Play, record, position, editing and the screen readouts. Uses the audio engine when there is one."""

    def __init__(self, screen, engine=None, clock=None):
        self.s = screen
        self.engine = engine
        self.clock = clock
        self.link = None                          # linksync.LinkSync, set by main()
        self.tape = tape.Tape(screen, engine)
        for n in range(1, 8):
            screen.custom["track%d_num" % n] = self.draw_num
        self.focus = focus.Focus(screen, self.tape)
        self.fx_page = None                       # None, "reverb" or "delay": what the FX key shows
        self.drum_page = False                    # the DRUMS key: track keys 1-7 play the drum synth
        self.drum_voice = 0                       # the voice the knobs edit (the last one played), 0-5
        self.drum_tab = 0                         # which page of its settings (knob 9 turns them)
        self._drum_hits = [0.0] * 16              # when each voice was last played, to light it up
        self.drum_key = 1                         # the drum key played last (7: the open hi-hat)
        import drumpage
        self.drumpage = drumpage.DrumPage(self)
        self._knob_times = {}                     # knob -> when it last clicked, to speed up fast turns
        self.seq_page = False                     # the MIDI key on the drum page: its sequencer
        self.seqp = seqpage.SeqPage(self)
        import synthpage
        self.synthp = synthpage.SynthPage(self)   # a synth's sequencer (the rows are notes)
        import instpage
        self.inst_page = False                    # the MIDI key from the tape: the INSTRUMENTS page
        self.instp = instpage.InstPage(self)
        self.engine.insert_boot = self.insfx_boot
        self.engine.insert_apply = self.insfx_apply
        self._songfx = None                       # SONG INSERT 1 / 2 (left button 3), made when first used
        self._insfx_song = None                  # the opened song's insert effects, kept until the sound core is up
        screen.after["playhead"] = self.draw_page
        self._playing = False
        self._recording = False
        self._armed = 4
        self.message = ""
        self.message_until = 0.0
        self.holding = None                # the hold key (LIFT or CUT) being held, if any
        self.drop_ask = None               # DROP of several tracks: {"insert", "merged"} while it asks how
        self.shift_held = lambda: False    # whether SHIFT is down on the control board (set up in main)
        self.bounce_pending = None         # (sources, dest) after the first BOUNCE press
        self._dirty_since = None
        self.glide = None                  # (from beat, to beat, seconds so far): the playhead easing somewhere
        self._bpm_seen = None
        self._bpm_since = 0.0
        self.tab_colours = {n: (screen.get("track%d_tab" % n) or {}).get("c") for n in range(1, 9)}
        if engine:
            screen.set("song", t=engine.song_label)
        self.update_screen()

    # the engine owns these when it exists, so the audio thread and the screen agree
    @property
    def playing(self):
        return self.engine.playing if self.engine else self._playing

    @playing.setter
    def playing(self, v):
        if self.engine:
            with self.engine.lock:
                self.engine.playing = v
                if not v:
                    self.engine.recording = False
        else:
            self._playing = v

    @property
    def recording(self):
        return self.engine.recording if self.engine else self._recording

    @recording.setter
    def recording(self, v):
        if self.engine:
            self.engine.set_recording(v)
        else:
            self._recording = v
            if v:
                self._playing = True

    @property
    def armed(self):
        return self.engine.armed if self.engine else self._armed

    @armed.setter
    def armed(self, v):
        if self.engine:
            self.engine.armed = v
        else:
            self._armed = v

    @property
    def synced(self):
        return bool(self.clock and self.clock.active and self.engine and self.engine.sync_mode == "external")

    def say(self, text, seconds=4):
        self.message, self.message_until = text, time.monotonic() + seconds

    @property
    def linked(self):
        """Ableton Link is on: PLAY and stop go to everyone on the network."""
        return bool(self.link and self.link.on)

    def stop(self):
        self.playing = False
        if self.linked:
            self.link.request_play(False)
        if self.engine:
            self.engine.rec_ready = False
            if self.engine.save():
                self.say("SAVED")

    # ------------------------------------------------------------ actions

    def key(self, name):
        if self.drop_ask is not None and name not in ("DROP", "DROP_INSERT") and \
                not (isinstance(name, tuple) and name[0] == "KNOB"):
            self.drop_ask = None                  # any other key: the drop question goes away
            self.message_until = 0
        if isinstance(name, tuple):
            if name[0] == "KNOB":
                self.glide = None                 # turning a knob or the wheel stops the playhead gliding too
                self.knob(*name[1:])
            elif name[0] == "LANE":
                self.sp().lane_key(*name[1:])
            elif name[0] == "HOLD":
                self.hold(name[1])
            elif name[0] == "RELEASE":
                self.release(name[1])
            self.update_screen()
            return
        t, e = self.tape, self.engine
        if name != "BOUNCE":
            self.bounce_pending = None
        if not isinstance(name, tuple) or name[0] == "KNOB":
            self.glide = None                     # any other control stops the playhead gliding
        if name == "PLAY":
            if self.playing or (self.linked and self.link._waiting):
                self.stop()
            elif self.linked:
                self.link.request_play(True)     # everyone starts, on the next bar
                self.say("STARTING ON THE NEXT BAR (LINK)", 2)
            else:
                self.playing = True
        elif name == "RECORD":
            self.record_key()
        elif name in ("LEFT", "RIGHT", "LOOP_IN", "LOOP_OUT") and self.seq_page and self.synth_shown():
            # the synth sequencer: the rows down / up an octave (SHIFT: one row)
            way = -1 if name in ("LEFT", "LOOP_IN") else 1
            self.synthp.arrows(way * (self.synthp.octave() if name in ("LEFT", "RIGHT") else 1))
        elif name in ("LEFT", "RIGHT") and self.seq_page and self.engine and self.engine.drums:
            self.seqp.move_box(-1 if name == "LEFT" else 1)   # the sequencer: the picked lane's 8-step box
        elif name in ("LEFT", "RIGHT", "BAR_LEFT", "BAR_RIGHT"):
            self.move(-1 if name.endswith("LEFT") else 1, tape.BEATS_PER_BAR if name.startswith("BAR") else t.step)
        elif self.inst_page and not self.fx_page and name in ("HOME", "HOME_PUSH_SHIFT"):
            # the INSTRUMENTS page: knob 11 turns through the list, push it: open a loaded slot, or choose for an empty one
            # (SHIFT + push on a loaded slot: change or remove it)
            self.instp.push() if name == "HOME" else self.instp.wheel_push()
        elif name in ("HOME", "HOME_PUSH_SHIFT"):
            start = e.loop_a / e.frames_per_beat() if (e and e.loop_on and e.loop_region()) else 0.0
            self.set_pos(start if t.pos > start + 1e-6 else 0.0)
        elif name == "GRID":
            t.cycle_grid()
        elif name == "ZOOM_IN":
            t.zoom_in()
        elif name == "ZOOM_OUT":
            t.zoom_out()
        elif name == "SWEEP_UNDO":
            self.sweep_undo()
        elif name == "ZOOM_RESET":
            t.zoom = tape.ZOOMS.index(4)
        elif name == "INPUT":
            if e:
                n = self.armed
                self.say("TRACK %d: %s  %s   ·   PRESS %d AGAIN TO ZOOM IN, THEN KNOBS 1-3 TO CHANGE" % (
                    n, "STEREO" if (n - 1) in e.stereo else "MONO",
                    e.input_text(n - 1) if e.device else "NO INPUT DEVICE", n), 5)
        elif name in ("PAN_LEFT", "PAN_RIGHT"):
            self.pan(self.armed, -0.1 if name == "PAN_LEFT" else 0.1)
        elif name == "EXPORT":
            self.export()
        elif name == "BOUNCE":
            self.bounce()
        elif name == "DRUMS":
            self.drums_key()
        elif name == "DRUMS_BACK":
            self.back_key()
        elif self.fx_page == "mixer" and re.match(r"^(TRACK|ARM)\d+$", name):
            # the MIXER: step buttons 1-8 mute the instrument in that slot, Shift + step button: solo it
            (self.instp.mute if name.startswith("TRACK") else self.instp.solo)(int(re.sub(r"\D", "", name)))
        elif self.inst_page and not self.fx_page and (name.startswith("TRACK") or name.startswith("ARM")
                                                       or name.startswith("MUTE") or name.startswith("SOLO")):
            # the INSTRUMENTS page: track keys mute slots, push knob 1 opens / picks (SHIFT: change, remove)
            if name.startswith("TRACK"):
                self.instp.mute(int(name[5:]))
        elif name.startswith("TRACK") and self.pad(int(name[5:])):
            pass                                  # a keyboard number key on the drum page: played
        elif name.startswith("TRACK"):
            n = int(name[5:])
            if n == self.armed or self.focus.track:
                self.focus.toggle(n)              # the selected track's key again: zoom in / out
            self.armed = n
            if e and not self.recording and e.select_arms:
                e.arm_extra = set()               # a plain press arms just this track
        elif name == "ARM_ALL" and e:
            every = set(range(8))
            e.arm_extra = set() if e.arm_extra == every else every
            self.say("ALL TRACKS ARMED" if e.arm_extra else "NO TRACKS ARMED", 2)
        elif name.startswith("ARM") and name[3:].isdigit() and e:
            # SHIFT + a track key arms it (the selected one too): an armed track's instrument is heard on
            # the tape page, and LIFT / CUT / SPLICE take every armed track
            n = int(name[3:])
            e.arm_extra ^= {n - 1}
            self.say("TRACK %d %s" % (n, "ARMED" if (n - 1) in e.arm_extra else "DISARMED"), 2)
        elif name == "FOCUS":
            self.focus.toggle(self.armed)
        elif name == "SEQ_UNDO":
            self.sp().undo()
        elif name.startswith("MUTE") and name[4:].isdigit() and self.full_drum_page():
            self.drum_reset(int(name[4:]))        # the drum page: push a knob, its setting goes back to default
        elif name == "MUTE1" and self.seq_page:
            self.sp().cycle_mode()                # push knob 1 on the sequencer: the next knob mode
        elif name in ("MUTE4", "MUTE5", "MUTE6", "SOLO4", "SOLO5", "SOLO6") and self.focus.active and e \
                and not self.drum_page and not self.fx_page:
            # the zoomed view: push knob 4 normalizes the box (SHIFT: gain back to 0 dB); 5 and 6: no fade
            self.box_edit({"MUTE4": "normalize", "SOLO4": "reset_gain"}.get(name, "reset_" + ("in" if name[-1] == "5" else "out")))
        elif name.startswith("MUTE"):
            self.mute(int(name[4:]) if name[4:] else self.armed)
        elif name.startswith("SOLO"):
            self.solo(int(name[4:]) if name[4:] else self.armed)
        elif name in ("PHONES_UP", "PHONES_DOWN"):
            self.phones_volume(0.05 if name == "PHONES_UP" else -0.05)
        elif name in ("VOL_UP", "VOL_DOWN"):
            self.volume(self.armed, 0.05 if name == "VOL_UP" else -0.05)
        elif name == "FX":
            order = [None, "reverb", "delay"]                # (the inserts are pages of each instrument's sound)
            if self.insert_fx_available():
                order += ["song1", "song2"]                  # ... and the song's two (a copy on every instrument)
            if getattr(self, "list_is_top", False):
                order.insert(1, "mixer")                     # (the Move) the MIXER first: each instrument's volume (Shift: pan)
            if self.fx_page and getattr(self, "list_is_top", False):
                order.remove(None)                           # (the Move) round the FX pages; Back leaves them
            self.fx_page = order[(order.index(self.fx_page) + 1) % len(order)]
            if self.fx_page and not effects.AVAILABLE:
                self.say(effects.PROBLEM or "EFFECTS AREN'T AVAILABLE", 4)
        elif name == "IMPORT":
            self.say("%s COMES IN A LATER VERSION" % name)
        else:
            self.edit(name)
        self.update_screen()

    # ------------------------------------------------------------ the drum synth (the DRUMS key)

    PAD_NAMES = ["DRUM 1", "DRUM 2", "DRUM 3", "SNARE", "CYMBAL", "CLOSED HAT", "OPEN HAT"]

    def drums_key(self):
        """The MIDI key, forwards: the tape -> the INSTRUMENTS page -> the picked slot's drum page -> its
        sequencer -> back to the INSTRUMENTS page (round and round). Over an FX page it closes the FX page first."""
        e = self.engine
        if self.fx_page:
            self.fx_page = None
            if self.drum_page or self.inst_page:
                return
        if self.drum_page and getattr(self, "list_is_top", False):
            # (the Move) round the instrument's own pages: sound -> sequencer -> automation -> sound; Back: the list
            if not self.seq_page:
                self.seq_page = True
            elif getattr(self, "has_auto_page", False) and not getattr(self, "auto_page", False):
                self.auto_page = True
            else:
                self.auto_page = self.seq_page = False
            self.seqp.held = {}
            self.synthp.held = {}
            return
        if self.drum_page:
            if self.seq_page and getattr(self, "has_auto_page", False) and not getattr(self, "auto_page", False):
                self.auto_page = True         # the sequencer, pressed again: its AUTOMATION page (the Move)
                return
            if self.seq_page:                 # the sequencer (or automation), pressed again: round to the instrument list
                self.auto_page = False
                self.back_key()
                return
            self.seq_page = True              # the sound -> its sequencer
            self.seqp.held = {}
            self.synthp.held = {}
            return
        if self.inst_page:
            if not getattr(self, "list_is_top", False):  # (the Move: on the list it does nothing; push the wheel)
                self.instp.push()
            return
        if not e or not e.drums:
            import drums
            self.say(getattr(drums, "PROBLEM", "") or "THE DRUM SYNTH ISN'T AVAILABLE", 4)
            return
        self.inst_page = True
        if e.slot is not None:
            self.instp.row = e.slot
        if e.input_choice != "DRUMS":
            e.set_input("DRUMS", "INSTRUMENTS")
            self.say("INPUT: INSTRUMENTS  (SETTINGS > INPUT TO CHANGE BACK)", 4)

    def back_key(self):
        """SHIFT+MIDI, back: the drum page or sequencer -> INSTRUMENTS -> the tape."""
        if self.fx_page:
            self.fx_page = None
            return
        if getattr(self, "auto_page", False):     # (the Move) the automation page: back to the instruments list
            self.auto_page = False
            if not getattr(self, "list_is_top", False):
                return
        if self.drum_page:
            self.drum_page = self.seq_page = False
            self.seqp.held = {}
            self.inst_page = True
            if self.engine and self.engine.slot is not None:
                self.instp.row = self.engine.slot
            return
        if self.inst_page:
            if self.instp.mode:
                self.instp.cancel()
                return
            self.inst_page = False

    def reset_drum_view(self):
        """The drum and sequencer pages start at the first drum (another instrument is showing)."""
        self.drum_voice, self.drum_key, self.drum_tab = 0, 1, 0
        self.seqp.lane, self.seqp.mode, self.seqp.box = 0, 0, {}
        self.seqp.held, self.seqp.placed = {}, {}
        self.synthp.row, self.synthp.mode, self.synthp.held, self.synthp.down = 0, 0, {}, {}

    def synth_shown(self):
        """True when the drum and sequencer pages show a synth (its rows are notes)."""
        e = self.engine
        return bool(e and e.slot is not None and e.slots[e.slot] and e.is_synth(e.slots[e.slot]))

    def sp(self):
        """The sequencer page for the shown instrument: the synth sequencer or the drum sequencer."""
        return self.synthp if self.synth_shown() else self.seqp

    def pad(self, n, shift=False):
        """Track key n on the drum page: play the drum on lane n (with SHIFT, lane n + 8 on a machine with
        more than 8; on the LXR, 7 is the hi-hat open). True if it played (else SHIFT + key arms the track).
        Called from the MIDI thread, so it only reads a few flags and queues the hit."""
        e = self.engine
        if not (self.drum_page and e and e.drums_input and e.drums and 1 <= n <= 8):
            return False
        if self.synth_shown():
            if shift:
                return False
            e.note_on(e.seq.shown_notes()[n - 1], 100)     # a synth: the keys play the sequencer's 8 rows
            self.drum_key = n
            self._drum_hits[0] = time.monotonic()
            return True
        d = e.drums
        if shift and d.lanes <= 8:
            return False
        lane = n - 1 + (8 if shift else 0)
        if lane >= d.lanes:
            return False
        e.hit(lane, 100)
        voice = d.lane_voice[lane]
        self.drum_voice = voice
        self.drum_key = lane + 1
        self._drum_hits[voice] = time.monotonic()
        return True

    def midi_note(self, note, velocity):
        """A note from a MIDI keyboard (the OP-XY): plays the open synth, and on its sequencer page while
        playing, goes into the pattern where it's playing, as long as it's held. From the MIDI thread."""
        e = self.engine
        if not (e and self.synth_shown() and e.drums_input):
            return
        held = self.__dict__.setdefault("_midi_held", {})
        if velocity:
            e.note_on(note, velocity)
            if self.seq_page and e.playing and getattr(self, "msyn", None) is None:   # (the Move records its pads itself)
                at = e._heard_frame()
                held[note] = (e.seq.live_place(note, at, e.frames_per_beat()), at)
                e.seq_changed()
        else:
            e.note_off(note)
            placed = held.pop(note, None)
            if placed and e.playing:
                step, at = placed
                steps = round((e._heard_frame() - at) / (e.frames_per_beat() / (e.seq.pattern.steps_per_beat() * e.seq._tf())))
                if steps > 1:
                    e.seq.change_note(step, note, "length", steps - 1)
                    e.seq_changed()

    def pad_release(self, n):
        """Track key n let go on a synth's sound page: its note stops. From the MIDI thread."""
        e = self.engine
        if self.drum_page and not self.seq_page and e and self.synth_shown() and 1 <= n <= 8:
            e.note_off(e.seq.shown_notes()[n - 1])

    def seq_pad(self, n, shift=False):
        """Track key n pressed on the sequencer page: the drum on lane n of the keys' bank (the 808's
        9-16 after SHIFT + knob 1), or with SHIFT the picked lane's drum. From the MIDI thread."""
        e = self.engine
        if not (self.drum_page and e and e.drums_input and e.drums and 1 <= n <= 8):
            return False
        if self.synth_shown():
            if not shift:
                self.synthp.key_sound(n, True)
            return True
        lane = self.seqp.lane if shift else n - 1 + 8 * (self.seqp.lane // 8)
        if lane >= e.drums.lanes:
            return False
        e.hit(lane, 100)
        voice = e.drums.lane_voice[lane]
        self._drum_hits[voice] = time.monotonic()
        if not shift:
            self.drum_voice = voice
            self.drum_key = lane + 1
        return True

    def drum_pages(self):
        d = self.engine.drums
        self.drum_voice = min(self.drum_voice, d.voices - 1)
        pages = d.pages(self.drum_voice)
        if getattr(self, "presets_page", False) and self.engine.is_synth(d.machine) and hasattr(d, "has_presets"):
            pages = [("PRESETS", [])] + list(pages)      # (the Move: a synth's first page is its presets)
        return pages

    def drum_knob(self, number, delta, shift):
        """On the drum page: knobs 1-8 are the settings on the page, knob 9 turns the page."""
        e = self.engine
        pages = self.drum_pages()
        if number == 9:
            self.drum_tab = max(0, min(len(pages) - 1, self.drum_tab + (1 if delta > 0 else -1)))
            return
        self.drum_tab = min(self.drum_tab, len(pages) - 1)
        params = pages[self.drum_tab][1]
        if number > len(params):
            return
        param = params[number - 1]
        e.change_drum(param, self.knob_clicks(number, delta, shift))
        rec = getattr(self, "knob_recorded", None)               # (the Move) recording into the pattern: a lock
        if rec:
            try:
                rec(param)
            except Exception as ex:                              # noqa: BLE001
                print("knob recording:", ex)
        self.drumpage.edited[number] = time.monotonic()        # lime, with its value, for a moment
        self.say("%s  %s  %s" % (e.drums.names[self.drum_voice], e.drums.label(param), e.drums.value_text(param)), 2)

    def drum_reset(self, number):
        """Knob n pushed on the drum page: its setting back to where the Init Kit has it."""
        e = self.engine
        pages = self.drum_pages()
        self.drum_tab = min(self.drum_tab, len(pages) - 1)
        params = pages[self.drum_tab][1]
        if number > len(params):
            return
        param = params[number - 1]
        e.reset_drum(param)
        self.drumpage.edited[number] = time.monotonic()
        self.say("%s  %s  BACK TO %s" % (e.drums.names[self.drum_voice], e.drums.label(param),
                                         e.drums.value_text(param)), 2)

    def knob_clicks(self, number, delta, shift):
        """Turning quickly goes further; SHIFT: one step at a time."""
        now = time.monotonic()
        fast = now - self._knob_times.get(number, 0) < 0.05
        self._knob_times[number] = now
        return delta if shift else delta * (4 if fast else 1)

    def knob(self, number, delta, shift):
        t = self.tape
        if self.drop_ask is not None and number == 1:
            self.drop_ask["merged"] = delta > 0           # DROP of several tracks: right = merged, left = separate
            self.say_drop_ask()
            return
        if self.fx_page and self.engine and not (number == 10 and shift):
            self.fx_knob(number, delta, shift)    # the FX pages go over everything, the drum pages too
        elif self.inst_page:
            self.instp.knob(number, delta)
        elif self.seq_page and self.engine and self.engine.drums and number <= 10 and not (number == 10 and shift):
            self.sp().knob(number, delta, shift)
        elif self.drum_page and self.engine and self.engine.drums and number <= 9:
            self.drum_knob(number, delta, shift)
        elif self.focus.active and self.engine and number <= 3:
            self.track_setup(number, delta)          # the zoomed view: knobs 1-3 mono / stereo, its input(s)
        elif self.focus.active and self.engine and number <= 6:
            # knobs 4-6 work on the box under the playhead: gain, fade in, fade out
            what = {4: "gain", 5: "in", 6: "out"}[number]
            steps = self.knob_clicks(number, delta, shift)
            self.box_edit(what, steps * 0.5 if what == "gain" else steps)
        elif number <= 8:
            if shift:
                self.pan(number, delta * 0.05)          # SHIFT + a track knob: pan
            else:
                self.volume(number, delta * 0.02)
        elif number == 9 and shift:
            self.sweep(delta)                     # SHIFT + knob 9: in and out points, a bar a click
        elif number == 9:
            for _ in range(abs(delta)):
                t.zoom_in() if delta > 0 else t.zoom_out()
        elif number == 10 and shift:
            self.phones_volume(delta * 0.02)       # SHIFT + knob 10: headphone volume
        elif number == 10:
            for _ in range(abs(delta)):
                t.grid = (t.grid + (1 if delta > 0 else -1)) % len(tape.GRIDS)
        elif number == 11:
            self.move(delta, tape.BEATS_PER_BAR if shift else t.step)

    SWEEP_GAP = 2.0           # seconds: turns closer together than this are one sweep

    def sweep(self, delta):
        """SHIFT + knob 9: from where the playhead is (on the nearest bar line), each click moves it a bar
        and the in and out points span from there to where it is now: turning right, the start is the
        IN point; turning left, it's the OUT point. A pause starts a new sweep."""
        e, t = self.engine, self.tape
        if not e:
            return
        now = time.monotonic()
        bar = tape.BEATS_PER_BAR
        s = getattr(self, "_sweep", None)
        if not s or now - s["t"] > self.SWEEP_GAP:
            pos = e.beats()
            start = round(pos / bar) * bar
            s = self._sweep = {"start": start, "pos": start, "undo": e.region_state(), "from": pos, "t": now}
        s["t"] = now
        s["pos"] = max(0.0, min(e.tape_beats, s["pos"] + (1 if delta > 0 else -1) * bar * abs(delta)))
        self.set_pos(s["pos"])
        a, b = sorted((s["start"], s["pos"]))
        e.set_region(a, b, loop_on=True if b > a else None)
        if b > a:
            self.say("IN %s  OUT %s   (SHIFT + PUSH KNOB 9: UNDO)" % (self.position_text(a), self.position_text(b)), 3)
        else:
            self.say("NO IN/OUT POINTS (TURN ON TO MAKE THEM)", 2)

    def sweep_undo(self):
        """SHIFT + push knob 9: the in and out points as they were before the last sweep, and the playhead
        back where it started."""
        s = getattr(self, "_sweep", None)
        if not s or not self.engine:
            self.say("NO SWEEP TO UNDO", 2)
            return
        self.engine.restore_region(s["undo"])
        self.set_pos(s["from"])
        self._sweep = None
        r = self.engine.loop_region()
        fpb = self.engine.frames_per_beat()
        self.say("IN/OUT POINTS BACK: %s" % ("IN %s  OUT %s" % (self.position_text(r[0] / fpb), self.position_text(r[1] / fpb))
                                              if r else "NONE"), 3)

    def record_key(self):
        e = self.engine
        if self.recording:
            self.recording = False
            return
        if e and not e.device:
            self.say("NO AUDIO DEVICE TO RECORD FROM")
            return
        if e and self.synced and not self.playing:
            e.rec_ready = not e.rec_ready
            if e.rec_ready:
                self.say("REC READY: PRESS PLAY ON THE OP-XY", 6)
            return
        if e and self.linked and not self.playing:
            e.rec_ready = True                    # recording starts with the tape, on Link's next bar
            self.link.request_play(True)
            self.say("RECORDING FROM THE NEXT BAR (LINK)", 3)
            return
        self.recording = True

    def set_pos(self, beats):
        self.tape.pos = beats
        if self.engine:
            self.engine.set_beats(beats)

    def move(self, steps, size):
        t = self.tape
        if self.engine:
            t.pos = self.engine.beats()
        t.move(steps, size)
        if self.engine:
            self.engine.set_beats(t.pos)

    def volume(self, track, delta):
        if not self.engine:
            return
        v = self.engine.change_volume(track, delta)
        self.say("TRACK %d  VOLUME %d%%" % (track, round(v * 100)), 2)

    # ------------------------------------------------------------ send effects (the FX key)

    FX_KNOBS = {"reverb": (("rev_size", "SIZE"), ("rev_tone", "TONE"), ("rev_level", "LEVEL"), ("rev_width", "WIDTH")),
                "delay": (("dly_time", "TIME"), ("dly_feedback", "FEEDBACK"), ("dly_level", "LEVEL"))}

    def insert_fx_available(self):
        import catalog
        return bool(getattr(self, "inst_sends", False) and catalog.FX)

    def insfx(self, slot=None, pos=None):
        """An instrument's INSERT effect 1 or 2 (schwung/insertfx.py), made when first used; its saved choice
        comes back with it. No slot / pos: the ones you're on."""
        import insertfx
        if getattr(self, "_insfx", None) is None:
            self._insfx = {}
            self.engine.insert_fx = self._insfx
            self._insfx_saved = {}
            try:
                self._insfx_saved = json.load(open(self._insfx_path())).get("slots", {})
            except (OSError, ValueError, AttributeError):
                pass
        if slot is None:
            slot = self.engine.slot if self.engine.slot is not None else 0
        if pos is None:
            pos = 1 if self.fx_page == "insert2" else 0
        core = getattr(self.engine, "core", None)
        ins = self._insfx.get((slot, pos))
        if ins is None:
            ins = self._insfx[(slot, pos)] = insertfx.Insert(core, slot, pos)
            if core is not None:
                saved = self._insfx_saved.get(str(slot)) or {}
                if "fx" in saved:                            # (the first version: one effect per instrument)
                    saved = {"0": saved}
                try:
                    ins.from_json(saved.get(str(pos)))
                except Exception:                           # noqa: BLE001
                    pass
        if ins.core is None and core is not None:
            ins.core = core
        return ins

    def songfx(self, p):
        """SONG INSERT 1 or 2 (p 0 / 1): one effect for the song, a copy of it on every loaded instrument."""
        import insertfx
        if self._songfx is None:
            self._songfx = [insertfx.SongInsert(i, lambda k, pos: self.insfx(k, pos)) for i in (0, 1)]
            self.engine.song_fx = self._songfx
        return self._songfx[p]

    def songfx_sync(self):
        """Instruments loaded or taken out: each loaded one gets (or loses) its copies of the song inserts."""
        if self._songfx is None or getattr(self.engine, "core", None) is None:
            return
        slots = [bool(m) for m in self.engine.slots]
        for sf in self._songfx:
            sf.sync(slots)

    def insfx_apply(self, data):
        """A song was opened: its insert effects replace the current ones (a slot the song has none for: none)."""
        if not isinstance(data, dict):
            return
        if getattr(self.engine, "core", None) is None:           # the core isn't up yet: insfx_boot does it
            self._insfx_song = data
            return
        self._insfx_song = None
        for slot in range(8):
            for pos in (0, 1):
                saved = (data.get(str(slot)) or {}).get(str(pos))
                have = getattr(self, "_insfx", None) and self._insfx.get((slot, pos))
                if saved and saved.get("fx"):
                    self.insfx(slot, pos).from_json(saved)
                elif have is not None and have.h:
                    have.choose(0)
        songs = data.get("song") or []                           # SONG INSERT 1 / 2 (none in older songs)
        if songs or self._songfx is not None:
            slots = [bool(m) for m in self.engine.slots]
            for p in (0, 1):
                self.songfx(p).from_json(songs[p] if p < len(songs) else None, slots)
        self._insfx_save()

    def insfx_boot(self):
        """The core is up: bring back every instrument's saved insert effects."""
        self.insfx(0, 0)
        data = self._insfx_song if self._insfx_song is not None else getattr(self.engine, "song_inserts", None)
        if data is not None:
            self.insfx_apply(data)
            return
        for k, v in list(self._insfx_saved.items()):
            for pos in (("0", "1") if "fx" not in v else ("0",)):
                try:
                    self.insfx(int(k), int(pos))
                except Exception:                           # noqa: BLE001
                    pass

    def _insfx_path(self):
        import store
        return os.path.join(store.data_dir(), "insert-fx.json")

    def _insfx_save(self):
        if getattr(self, "_insfx", None) is None:              # no insert effects made yet: nothing to save
            return
        try:
            out = {}
            for (k, pos), v in self._insfx.items():
                if pos < 2:                                        # (2-3: the song inserts' copies, saved as the song's)
                    out.setdefault(str(k), {})[str(pos)] = v.to_json()
            json.dump({"slots": out}, open(self._insfx_path(), "w"))
        except OSError:
            pass
        try:
            self.engine.seq_changed()                              # the song keeps its insert effects: save it
        except Exception:                                          # noqa: BLE001
            pass

    def fx_knob(self, number, delta, shift=False):
        """On an FX page: knobs 1-8 are the tracks' sends, 9 and 10 the effect's settings, the big knob its level."""
        e = self.engine
        if self.fx_page == "mixer":                              # the MIXER: knobs 1-8 the instruments in slots 1-8
            if number <= 8 and e and e.slots[number - 1]:
                if shift:                                        # Shift + knob: its pan
                    v = e.change_inst_pan(number - 1, delta * 0.04)
                    self.say("INSTRUMENT %d PAN: %s" % (number, mix_pan_text(v)), 2)
                else:
                    v = e.change_inst_level(number - 1, delta * 0.02)
                    self.say("INSTRUMENT %d VOLUME: %d%%" % (number, round(v * 100)), 2)
            return
        if self.fx_page in ("insert", "insert2"):
            ins = self.insfx()
            if number <= 8:
                ins.knob(number - 1, delta)
                self._insfx_save()
            return
        if self.fx_page in ("song1", "song2"):                   # SONG INSERT 1 / 2: knobs 1-8 its settings
            if number <= 8:
                self.songfx(0 if self.fx_page == "song1" else 1).knob(number - 1, delta)
                self._insfx_save()
            return
        if getattr(self, "inst_sends", False):          # the Move: 1-3 the effect (each instrument's send is on its SENDS page)
            if number <= len(self.FX_KNOBS[self.fx_page]):
                key = self.FX_KNOBS[self.fx_page][number - 1][0]
                e.change_fx(key, delta if key == "dly_time" else delta * 0.02)
            return
        if number <= 8:
            e.change_send(self.fx_page, number, delta * 0.02)
        else:
            key = self.FX_KNOBS[self.fx_page][number - 9][0]
            e.change_fx(key, delta if key == "dly_time" else delta * 0.02)

    def fx_value_text(self, key):
        v = self.engine.fx[key]
        if key == "dly_time":
            return v
        return "%d%%" % round(v * 100)

    def draw_page(self, surf, it=None):
        if self.inst_page and not self.fx_page:
            return                                # drawn over the whole screen at the end (draw_full_page)
        if self.fx_page:
            self.draw_fx(surf, it)
        elif self.seq_page and self.engine and self.engine.drums:
            self.sp().draw(surf)
        elif self.full_drum_page():
            pass                                  # drawn over the whole screen at the end (draw_full_page)
        else:
            self.draw_fx(surf, it)

    def full_drum_page(self):
        return bool(self.drum_page and not self.fx_page and not self.seq_page and self.engine and self.engine.drums)

    def draw_full_page(self, surf):
        """Pages that take the whole screen, drawn after everything else."""
        if self.full_drum_page():
            self.drumpage.draw(surf)
        elif self.inst_page and not self.fx_page:
            self.instp.draw(surf)

    def draw_drums(self, surf):
        """The drum page: knob n's setting across track n's lane, and the voices and pages on the right."""
        s, e = self.s, self.engine
        d = e.drums
        small, mid, big = s.font("mono", 600, 14), s.font("mono", 600, 18), s.font("mono", 700, 26)
        accent, grey, white = (255, 181, 71), (125, 131, 140), (242, 243, 245)
        home = lambda n, part: self.focus.home.get((n, part)) or s.get("track%d_%s" % (n, part))
        first, last = home(1, "lane"), home(8, "lane")
        surf.set_clip(None)
        pygame.draw.rect(surf, (12, 13, 16), (0, first["y"] - 4, 1280, last["y"] + last["h"] - first["y"] + 8))
        pages = self.drum_pages()
        self.drum_tab = min(self.drum_tab, len(pages) - 1)
        page_name, params = pages[self.drum_tab]
        label_x, bar_x, bar_w = 72, 230, 470
        for n in range(1, 9):
            lane, tab = home(n, "lane"), home(n, "tab")
            if not lane:
                continue
            on = n <= len(params)
            if tab:
                pygame.draw.rect(surf, accent if on else (40, 43, 50), (tab["x"], tab["y"], tab["w"], tab["h"]), border_radius=6)
                num = s.font("mono", 600, 16).render(str(n), True, (12, 13, 16))
                surf.blit(num, (tab["x"] + (tab["w"] - num.get_width()) // 2, tab["y"] + (tab["h"] - num.get_height()) // 2))
            if not on:
                continue
            param = params[n - 1]
            mid_y = lane["y"] + lane["h"] // 2
            name = mid.render(drumparams.LABELS[param], True, white)
            surf.blit(name, (label_x, mid_y - name.get_height() // 2))
            y, h = lane["y"] + 8, lane["h"] - 16
            pygame.draw.rect(surf, (40, 43, 50), (bar_x, y, bar_w, h), border_radius=3)
            w = round(bar_w * max(0.0, min(1.0, d.fraction(param))))
            if w:
                pygame.draw.rect(surf, accent, (bar_x, y, w, h), border_radius=3)
            value = small.render(d.value_text(param), True, white)
            surf.blit(value, (bar_x + bar_w + 12, mid_y - value.get_height() // 2))
        # the box on the right: the voices (light up when played) and this voice's pages
        bx, by = 880, first["y"]
        bw, bh = first["x"] + first["w"] - bx, last["y"] + last["h"] - by
        pygame.draw.rect(surf, (20, 22, 26), (bx, by, bw, bh), border_radius=6)
        pygame.draw.rect(surf, accent, (bx, by, bw, bh), 2, border_radius=6)
        names = drums_mod().NAMES
        surf.blit(big.render(names[self.drum_voice], True, accent), (bx + 18, by + 14))
        hint = small.render("KEYS 1-7 PLAY", True, grey)
        surf.blit(hint, (bx + bw - 18 - hint.get_width(), by + 22))
        now = time.monotonic()
        cell = (bw - 36) // 6
        for v in range(6):
            x0, y0 = bx + 18 + v * cell, by + 56
            glow = max(0.0, 1.0 - (now - self._drum_hits[v]) / 0.25)
            base = (60, 64, 72) if v != self.drum_voice else (120, 92, 40)
            colour = tuple(round(c + (255 - c) * glow) for c in base)
            pygame.draw.rect(surf, colour, (x0, y0, cell - 6, 26), border_radius=4)
            t = small.render(str(v + 1), True, (12, 13, 16) if (glow > 0.3 or v == self.drum_voice) else white)
            surf.blit(t, (x0 + (cell - 6 - t.get_width()) // 2, y0 + 4))
        py = by + 100
        surf.blit(small.render("KNOB 9: PAGE", True, grey), (bx + 18, py))
        for i, (pname, _) in enumerate(pages):
            colour = accent if i == self.drum_tab else grey
            surf.blit(mid.render(("> " if i == self.drum_tab else "  ") + pname, True, colour), (bx + 18, py + 24 + i * 26))

    def draw_fx(self, surf, it=None):
        """The FX page: each track's send as a bar across its lane, and the effect's settings on the right."""
        page, e = self.fx_page, self.engine
        if not page or not e:
            return
        s = self.s
        sends = e.rev_sends if page == "reverb" else e.dly_sends
        small, mid, big = s.font("mono", 600, 14), s.font("mono", 600, 18), s.font("mono", 700, 26)
        bar_x, bar_w = 72, 720
        # the layout's own positions: the zoomed track view moves the real items around
        home = lambda n, part: self.focus.home.get((n, part)) or s.get("track%d_%s" % (n, part))
        first, last = home(1, "lane"), home(8, "lane")
        surf.set_clip(None)
        pygame.draw.rect(surf, (12, 13, 16), (0, first["y"] - 4, 1280, last["y"] + last["h"] - first["y"] + 8))
        for n in range(1, 9):
            lane, tab = home(n, "lane"), home(n, "tab")
            if not lane:
                continue
            colour = ui.rgb(tab["c"]) if tab else (200, 200, 200)
            if tab:
                pygame.draw.rect(surf, colour, (tab["x"], tab["y"], tab["w"], tab["h"]), border_radius=6)
                num = s.font("mono", 600, 16).render(str(n), True, (12, 13, 16))
                surf.blit(num, (tab["x"] + (tab["w"] - num.get_width()) // 2, tab["y"] + (tab["h"] - num.get_height()) // 2))
            y, h = lane["y"] + 8, lane["h"] - 16
            pygame.draw.rect(surf, (40, 43, 50), (bar_x, y, bar_w, h), border_radius=3)
            w = round(bar_w * sends[n - 1])
            if w:
                pygame.draw.rect(surf, colour, (bar_x, y, w, h), border_radius=3)
            label = small.render("%d%%" % round(sends[n - 1] * 100), True, (242, 243, 245))
            surf.blit(label, (bar_x + bar_w + 12, lane["y"] + (lane["h"] - label.get_height()) // 2))
        # the settings box on the right
        bx, by = 880, first["y"]
        bw, bh = first["x"] + first["w"] - bx, last["y"] + last["h"] - by
        pygame.draw.rect(surf, (20, 22, 26), (bx, by, bw, bh), border_radius=6)
        pygame.draw.rect(surf, (60, 203, 127), (bx, by, bw, bh), 2, border_radius=6)
        title = big.render(page.upper(), True, (60, 203, 127))
        surf.blit(title, (bx + 18, by + 14))
        hint = small.render("KNOBS 1-8: SENDS", True, (125, 131, 140))
        surf.blit(hint, (bx + bw - 18 - hint.get_width(), by + 22))
        if not effects.AVAILABLE:
            msg = small.render(effects.PROBLEM or "EFFECTS AREN'T AVAILABLE", True, (255, 181, 71))
            surf.blit(msg, (bx + 18, by + 60))
            return
        for i, (key, name) in enumerate(self.FX_KNOBS[page]):
            ry = by + 66 + i * 76
            knob = ("KNOB 9", "KNOB 10", "BIG KNOB")[i]
            surf.blit(mid.render(name, True, (242, 243, 245)), (bx + 18, ry))
            surf.blit(small.render(knob, True, (125, 131, 140)), (bx + 18, ry + 26))
            value = mid.render(self.fx_value_text(key), True, (242, 243, 245))
            surf.blit(value, (bx + bw - 18 - value.get_width(), ry))
            if key == "dly_time":
                names = [n for n, _ in effects.DELAY_TIMES]
                frac = (names.index(e.fx[key]) + 1) / len(names) if e.fx[key] in names else 0
            else:
                frac = e.fx[key] / (0.95 if key == "dly_feedback" else 1.0)
            pygame.draw.rect(surf, (40, 43, 50), (bx + 130, ry + 30, bw - 148, 8), border_radius=4)
            if frac > 0:
                pygame.draw.rect(surf, (60, 203, 127), (bx + 130, ry + 30, round((bw - 148) * frac), 8), border_radius=4)

    def phones_volume(self, delta):
        e = self.engine
        if not e:
            return
        v = e.change_phones_volume(delta)
        if e.port:
            note = "" if e.route == "phones" else "  (%s)" % e.output_label
        else:
            note = "  (OUTPUT IS %s: USE ITS OWN VOLUME)" % (e.output_label or "NOT SET")
        self.say("VOLUME %d%%%s" % (round(v * 100), note), 2)

    def clip_text(self):
        """Where the clipboard came from: TRACK 3, TRACK 3 (STEREO) or TRACKS 1, 3, 4."""
        ts = [t for t in self.engine.clip_tracks if t < 8]      # (8 and up: right channels)
        if len(ts) == 1:
            return "TRACK %d%s" % (ts[0] + 1, " (STEREO)" if self.engine.clip_stereo() else "")
        return "TRACKS " + ", ".join(str(t + 1) for t in ts)

    def say_drop_ask(self):
        n = self.engine.clip_parts()
        merged = self.drop_ask["merged"]
        self.say("DROP %d AS %s / %s   ·   KNOB 1 CHANGES   ·   DROP AGAIN TO DROP" % (   # (the Move shows the first 31 letters)
            n, "SEPARATE" if merged else "[SEPARATE]", "[MERGED]" if merged else "MERGED"), 60)

    def edit_text(self):
        t = self.engine.armed - 1
        return "TRACK %d%s" % (t + 1, " (STEREO)" if t in self.engine.stereo else "")

    def draw_num(self, surf, it):
        """The track number, and a small ST beside a stereo track's."""
        self.s.draw_default(surf, it)
        e = self.engine
        n = int(it["name"][5:it["name"].index("_")])
        if not e or (n - 1) not in e.stereo:
            return
        tab = self.s.get("track%d_tab" % n) or it
        font = self.s.font("mono", 700, 9)
        img = font.render("ST", True, (12, 13, 16))
        x = tab["x"] + tab["w"] - img.get_width() - 3
        surf.blit(img, (x, tab["y"] + 2))

    def pan(self, track, delta):
        if not self.engine:
            return
        word = "BALANCE" if (track - 1) in self.engine.stereo else "PAN"
        self.say("TRACK %d  %s %s" % (track, word, self.pan_text(self.engine.change_pan(track, delta))), 2)

    @staticmethod
    def pan_text(p):
        if abs(p) < 0.01:
            return "CENTRE"
        return "%s %d" % ("L" if p < 0 else "R", round(abs(p) * 100))

    def solo(self, track):
        if not self.engine:
            return
        on = self.engine.toggle_solo(track)
        others = sorted(t + 1 for t in self.engine.solos)
        self.say("TRACK %d SOLO %s%s" % (track, "ON" if on else "OFF",
                                          "  (SOLOED: %s)" % ",".join(map(str, others)) if others else ""), 2)

    def mute(self, track):
        if not self.engine:
            return
        muted = self.engine.toggle_mute(track)
        self.say("TRACK %d %s" % (track, "MUTED" if muted else "ON"), 2)

    def hold(self, name):
        """LIFT or CUT pressed on the board: start selecting from the piece under the playhead."""
        if self.engine and not self.recording:
            self.engine.begin_selection()
            self.holding = name
            self.say("MOVE TO TAKE MORE PIECES, LET GO TO %s" % ("COPY" if name == "COPY" else "CUT"), 30)

    def release(self, name):
        if self.holding == name:
            self.holding = None
            self.message_until = 0
            self.edit(name)

    def edit(self, name):
        e = self.engine
        if not e:
            self.say("EDITING NEEDS THE AUDIO ENGINE")
            return
        pos = self.position_text(self.tape.pos)
        if name == "LOOP":
            e.toggle_loop()
            self.say("LOOP ON" if e.loop_on else "LOOP OFF", 2)
            return
        if name in ("LOOP_IN", "LOOP_OUT"):
            e.set_loop_point("in" if name == "LOOP_IN" else "out", self.tape.pos)
            self.say("%s POINT AT %s" % ("IN" if name == "LOOP_IN" else "OUT", pos), 2)
            return
        if name == "CLEAR_REGION":
            e.clear_region()
            self.say("IN/OUT POINTS CLEARED", 2)
            return
        if name == "REC_MODE":
            self.say("RECORDING %s" % ("ADDS TO THE TAPE (OVERDUB)" if e.toggle_rec_mode() == "overdub"
                                       else "REPLACES THE TAPE"), 3)
            return
        if self.recording:
            self.say("STOP RECORDING FIRST")
            return
        if name == "SELECT":
            if e.sel_anchor is None:
                e.begin_selection()
                self.say("SELECTING: MOVE TO TAKE MORE PIECES, THEN COPY OR CUT", 30)
            else:
                e.end_selection()
                self.say("SELECTION CANCELLED", 2)
        elif name == "COPY":
            beats = e.copy()
            if beats:
                self.glide_to_edit(0)
            self.say("COPIED %s FROM %s" % (self.beats_text(beats), self.clip_text()) if beats
                     else "NOTHING HERE TO COPY")
        elif name == "CUT":
            beats = e.cut()
            if beats:
                self.glide_to_edit(0)
            self.say("CUT %s FROM %s" % (self.beats_text(beats), self.clip_text()) if beats
                     else "NOTHING HERE TO CUT")
        elif name in ("DROP", "DROP_INSERT"):
            insert = name == "DROP_INSERT"
            if e.clip is not None and e.clip_parts() > 1 and self.drop_ask is None:
                # several tracks on the clipboard: ask how, then DROP again
                self.drop_ask = {"insert": insert, "merged": False}
                self.say_drop_ask()
                return
            merged = False
            if self.drop_ask is not None:
                merged = self.drop_ask["merged"]
                insert = insert or self.drop_ask["insert"]
                self.drop_ask = None
            done = e.drop(insert=insert, merged=merged)
            if isinstance(done, list):
                self.glide_to_edit(1)
                if len(done) == 1:
                    where = "TRACK %d" % (done[0] + 1)
                else:
                    where = "TRACKS %d-%d" % (done[0] + 1, done[-1] + 1)
                self.say("DROPPED%s ON %s AT %s%s" % (" (MERGED)" if merged else "", where, pos,
                                                      ", PUSHING THE REST LATER" if insert else ""))
            else:
                self.say(done)
        elif name in ("SPLICE", "SPLICE_ALL"):
            done = e.splice(name == "SPLICE_ALL")
            ts = set(e.armed_tracks())
            where = "ALL TRACKS" if name == "SPLICE_ALL" else self.armed_text(sorted(t + 1 for t in ts))
            self.say("SPLIT %s AT %s" % (where, pos) if done == "added"
                     else "JOINED BACK TOGETHER ON %s" % where if done == "removed"
                     else "NO BOX HERE TO SPLIT", 2)
        elif name == "UNDO" and self.seq_page and e and e.drums:
            self.sp().undo()                      # on the sequencer, SHIFT+CUT undoes the last pattern edit
        elif name == "UNDO":
            self.say("UNDONE" if e.undo() else "NOTHING TO UNDO", 2)

    def new_song(self, name):
        self.focus.track = None
        self.engine.new_song(name)
        try:
            self.insfx_apply({})                     # a new song starts with no insert effects
        except Exception as ex:                      # noqa: BLE001
            print("insert effects:", ex)
        self.tape.pos = 0.0
        self.s.set("song", t=name or "NEW PROJECT")
        self.say("NEW PROJECT: %s" % name.upper() if name else "NEW PROJECT  (SAVE PROJECT NAMES IT)", 5)

    def open_song(self, name):
        self.focus.track = None
        self.engine.open_song(name)
        self.tape.pos = self.engine.beats()
        self.s.set("song", t=name)
        self.say("OPENED %s" % name.upper(), 4)

    def export(self):
        if not self.engine:
            self.say("NOTHING TO EXPORT IN DEMO MODE")
            return
        self.say("EXPORTING...", 60)

        def work():
            name = self.engine.export()
            self.say("EXPORTED TO EXPORTS / %s" % name.upper() if name else "NOTHING RECORDED YET", 6)
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ every frame

    def tick(self, seconds):
        t, e = self.tape, self.engine
        if e:
            e.inst_view = bool(self.inst_page or self.drum_page)   # there every instrument plays, the tape doesn't
            self.update_glide(seconds)
            was = self._playing
            t.pos = e.beats()
            self._playing = e.playing
            if was and not self._playing:           # stopped by the tape end, or by MIDI stop
                self.stop()
            self.follow_tempo()
            e.refresh_levels()
            if self.link and self.link.message:
                self.say(self.link.message, 3)
                self.link.message = ""
            self.autosave()
            dirty = getattr(e, "_phones_dirty", None)
            if dirty and time.monotonic() - dirty > 1.0:
                e.save_phones_volume()              # once the knob has stopped turning
        elif self.playing:
            start = t.pos
            t.pos += seconds * BPM / 60
            if t.pos >= tape.TAPE_BEATS:
                t.pos = float(tape.TAPE_BEATS)
                self.playing = self.recording = False
            if self.recording:
                t.record(self.armed, start, t.pos)
        self.focus.update(seconds, self.playing)
        self.update_screen()

    def glide_to_edit(self, which):
        """Ease the playhead to the start (0) or end (1) of the box just lifted, cut or dropped."""
        e = self.engine
        if not e.last_edit or self.playing:
            return
        to = e.last_edit[which] / e.frames_per_beat()
        here = e.beats()
        if abs(to - here) > 1e-6:
            self.glide = (here, to, 0.0)

    def update_glide(self, seconds):
        if not self.glide:
            return
        if self.playing:
            self.glide = None
            return
        a, b, done = self.glide
        length = min(0.9, 0.3 + 0.04 * abs(b - a) ** 0.5)          # longer moves take a little longer
        done += seconds
        f = min(1.0, done / length)
        f = f * f * (3 - 2 * f)                                       # ease in and out
        self.engine.set_beats(a + (b - a) * f)
        self.glide = None if done >= length else (a, b, done)

    def autosave(self):
        """While stopped, write changes to the song's files a moment after the last edit."""
        e = self.engine
        if self.playing or not e.dirty:
            self._dirty_since = None
            return
        now = time.monotonic()
        if self._dirty_since is None:
            self._dirty_since = now
        elif now - self._dirty_since > 1.0:
            self._dirty_since = None
            e.save()

    def bounce(self):
        e = self.engine
        if not e:
            self.say("BOUNCING NEEDS THE AUDIO ENGINE")
            return
        if self.playing:
            self.say("STOP FIRST, THEN BOUNCE")
            return
        dest = self.armed - 1
        sources = sorted(e.arm_extra - {dest})        # (the selected track can be armed too: it's where it goes)
        if not sources:
            self.say("ARM THE TRACKS TO BOUNCE WITH SHIFT+TRACK; THEY GO ONTO THE SELECTED TRACK", 6)
            return
        names = ",".join(str(t + 1) for t in sources)
        if self.bounce_pending != (tuple(sources), dest):
            self.bounce_pending = (tuple(sources), dest)
            self.say("BOUNCE TRACK%s %s INTO TRACK %d? PRESS AGAIN TO DO IT" % ("S" if len(sources) > 1 else "", names, dest + 1), 8)
            return
        self.bounce_pending = None
        beats = e.bounce(sources, dest)
        if beats is None:
            self.say("NOTHING TO BOUNCE")
            return
        e.arm_extra = set()
        self.say("BOUNCED %s INTO TRACK %d (SHIFT+CUT UNDOES)" % (names, dest + 1), 5)

    def follow_tempo(self):
        """Take the OP-XY's tempo while stopped, once it has held steady for a moment."""
        bpm = self.clock.bpm if (self.clock and self.synced) else None
        if not bpm or self.playing:
            self._bpm_seen = None
            return
        bpm = round(bpm, 1)
        now = time.monotonic()
        if self._bpm_seen is None or abs(bpm - self._bpm_seen) > 0.2:
            self._bpm_seen, self._bpm_since = bpm, now
        elif now - self._bpm_since > 0.7 and abs(bpm - self.engine.bpm) > 0.2:
            if self.engine.set_bpm(bpm):
                self.say("TEMPO %.1f BPM FROM MIDI" % bpm, 3)

    def panel_lines(self):
        e, n = self.engine, self.focus.shown
        if not e:
            return ["DEMO MODE", "NO AUDIO ENGINE"]
        vol = "VOLUME %d%%  %s %s%s" % (round(e.volumes[n - 1] * 100), "BALANCE" if (n - 1) in e.stereo else "PAN",
                                        self.pan_text(e.pans[n - 1]),
                                         "  MUTED" if (n - 1) in e.mutes else "  SOLO" if (n - 1) in e.solos else "")
        mode = "REC: OVERDUB" if e.rec_mode == "overdub" else "REC: REPLACE"
        r = e.loop_region()
        fpb = e.frames_per_beat()
        inout = ("IN %s  OUT %s" % (self.position_text(r[0] / fpb), self.position_text(r[1] / fpb))) if r else "NO IN/OUT POINTS"
        if e.clip is not None:
            clip = "CLIPBOARD %s%s" % (self.beats_text(len(e.clip[0]) / fpb), "  STEREO" if e.clip_stereo()
                                       else "  %d TRACKS" % len(e.clip) if len(e.clip) > 1 else "")
        else:
            clip = "CLIPBOARD EMPTY"
        info = e.box_info()
        box = ("BOX: " + self.box_text(info)) if info else "NO BOX AT THE PLAYHEAD"
        st = (n - 1) in e.stereo
        track = "%s  %s  (KNOBS 1-%d)" % ("STEREO" if st else "MONO", e.input_text(n - 1) if e.device else "NO INPUT",
                                        3 if st else 2)
        # the panel: [the track, volume / its column, ...] two columns of two lines, and the box beside the title
        return [track, vol, "%s  ·  %s" % (mode, inout), clip, box]

    def knob_labels(self):
        """The zoomed view's eight knob labels, left to right: (what it does, its value, in use right now)."""
        e, n = self.engine, self.focus.shown
        t = n - 1
        st = t in e.stereo
        src = e.source(t) if e.device else None
        if st and isinstance(src, tuple):
            left, right = e.channel_name(src[0]), e.channel_name(src[1])
        else:
            left, right = (e.input_text(t) if e.device else "NO INPUT"), "-"
        info = e.box_info()
        return [
            ("MONO / STEREO", "STEREO" if st else "MONO", True),
            ("LEFT IN" if st else "INPUT", left, True),
            ("RIGHT IN", right, st),
            ("BOX GAIN", "%+.1f dB" % info["gain"] if info else "NO BOX", bool(info)),
            ("FADE IN", self.fade_text(info["in"]) if info else "NO BOX", bool(info)),
            ("FADE OUT", self.fade_text(info["out"]) if info else "NO BOX", bool(info)),
            ("TRACK 7 VOL", "%d%%" % round(e.volumes[6] * 100), True),
            ("TRACK 8 VOL", "%d%%" % round(e.volumes[7] * 100), True),
        ]

    def track_setup(self, number, delta):
        """The zoomed track view's knobs 1-3: 1 MONO / STEREO, 2 the input (a stereo track's left),
        3 a stereo track's right input."""
        e, n = self.engine, self.focus.shown
        t = n - 1
        if self.recording:
            self.say("STOP RECORDING FIRST", 2)
            return
        if number == 1:
            on = delta > 0
            self.input_popup = (time.monotonic() + 2.5, t, -1)            # MONO / STEREO, big on the screen
            if e.set_stereo(t, on):
                self.say("TRACK %d: %s%s" % (n, "STEREO" if on else "MONO",
                                             "  (BOTH SIDES MIXED TOGETHER; SHIFT+CUT UNDOES)" if not on and e.track_end(t)
                                             else ""), 3)
            else:
                self.say("TRACK %d IS %s (KNOB 1: LEFT MONO, RIGHT STEREO)" % (n, "STEREO" if t in e.stereo else "MONO"), 2)
            return
        if number == 3 and t not in e.stereo:
            self.say("TRACK %d IS MONO: ONE INPUT, ON KNOB 2" % n, 2)
            return
        text = e.step_input(t, number - 2, delta)
        if text is None:
            self.say("NO INPUT DEVICE", 2)
        else:
            self.say("TRACK %d%s  INPUT %s" % (n, " STEREO" if t in e.stereo else "", text), 2)
            self.input_popup = (time.monotonic() + 2.5, t, number - 2)        # the Move shows it big, on the whole screen

    def box_edit(self, what, delta=0):
        info = self.engine.change_box(what, delta)
        if info is None:
            self.say("MOVE THE PLAYHEAD ONTO A BOX FIRST", 2)
        elif info == "SILENT":
            self.say("THIS BOX IS SILENT: NOTHING TO NORMALIZE", 2)
        else:
            self.say(("NORMALIZED: " if what == "normalize" else "BOX ") + self.box_text(info), 2)

    @staticmethod
    def fade_text(s):
        if s <= 0:
            return "OFF"
        return "%d ms" % round(s * 1000) if s < 1 else "%g s" % round(s, 2)

    def box_text(self, info):
        return "GAIN %+.1f dB   FADE IN %s   FADE OUT %s" % (info["gain"], self.fade_text(info["in"]),
                                                               self.fade_text(info["out"]))

    def routing_text(self, armed):
        """What the armed tracks record: TRACK 4 < IN 4, or 1 < IN 1  ·  3 ST < IN 3+4."""
        e = self.engine
        parts = ["%s%s%s < %s" % ("TRACK " if len(armed) == 1 else "", n, " ST" if (n - 1) in e.stereo else "",
                                 e.input_text(n - 1)) for n in armed]
        return "  ·  ".join(parts) if len(parts) <= 4 else "%s (%d TRACKS)" % (parts[0], len(parts))

    def armed_text(self, armed):
        if len(armed) == 8:
            return "ALL TRACKS"
        if len(armed) == 1:
            return "TRACK %d" % armed[0]
        return "TRACKS " + ",".join(str(n) for n in armed)

    def beats_text(self, beats):
        if beats >= 4 and abs(beats / 4 - round(beats / 4)) < 0.01:
            bars = round(beats / 4)
            return "%d BAR%s" % (bars, "" if bars == 1 else "S")
        return "%g BEAT%s" % (round(beats, 2), "" if abs(beats - 1) < 0.01 else "S")

    def position_text(self, beats):
        bar = math.floor(beats / tape.BEATS_PER_BAR + 1e-9)
        within = max(0.0, beats - bar * tape.BEATS_PER_BAR)
        beat = math.floor(within / tape.BEAT_UNIT + 1e-9)
        sixteenth = math.floor((within - beat * tape.BEAT_UNIT) * 4 + 1e-9)
        return "%03d.%d.%d" % (bar + 1, beat + 1, sixteenth + 1)

    def update_screen(self):
        s, t, e = self.s, self.tape, self.engine
        s.set("clock", t=self.position_text(t.pos))
        region = e.loop_region() if e else None
        s.set("grid", t=t.label() + ("   LOOP" if (region and e.loop_on) else "   IN/OUT" if region else ""))
        bpm = e.bpm if e else BPM
        internal = bool(e and e.sync_mode == "internal")
        if e and tuple(e.time_sig) != tape.SIG:
            tape.set_signature(*e.time_sig)
        sync = "  SYNC" if self.synced else "  LEAD" if internal else ""
        if self.linked:
            sync = "  LINK %d" % self.link.peers
        s.set("bpm", t="%.1f BPM  %s%s" % (bpm, tape.signature_text(), sync))
        armed = [t + 1 for t in e.armed_tracks()] if e else [self.armed]
        first, last, lane = s.get("track1_lane"), s.get("track8_lane"), s.get("track%d_lane" % self.armed)
        if self.focus.active:
            lane = s.get("track%d_lane" % self.focus.shown)
            if lane:
                s.set("rec_outline", y=lane["y"] - 2, h=lane["h"] + 4)
        elif lane:
            s.set("rec_outline", y=lane["y"] - 2, h=lane["h"] + 4)
        ready = bool(e and e.rec_ready)
        state = "RECORDING" if self.recording else "REC READY" if ready else "PLAYING" if self.playing else "STOPPED"
        overdub = bool(e and e.rec_mode == "overdub")
        selecting = bool(e and e.sel_anchor is not None)
        s.set("status", t="%s  %s%s%s" % (state, self.armed_text(armed),
                                          "  OVERDUB" if overdub else "", "  SELECTING" if selecting else ""))
        if self.focus.active:
            self.focus.info["lines"] = self.panel_lines()
            self.focus.info["knobs"] = self.knob_labels() if e else None
        red = "#FF5A4E" if (self.recording or ready) else "#7D838C"
        t.extra_armed = {n + 1 for n in e.arm_extra} if e else set()   # armed with SHIFT + key: outlined
        t.arm_colour = ui.rgb(red)
        s.set("rec_dot", c=red)
        s.set("rec_outline", c=red)

        if self.message and time.monotonic() < self.message_until:
            hint = self.message
        elif not e:
            hint = "DEMO: NO AUDIO ENGINE"
        elif self.drum_page and not (e.device and e.drums_input):
            hint = "INSTRUMENTS STARTING..."
        elif self.seq_page:
            hint = "SEQUENCER  \u00b7  MIDI: DRUM PAGE  \u00b7  SHIFT+MIDI: INSTRUMENTS"
        elif self.drum_page:
            hint = "DRUMS  ·  MIDI: SEQUENCER  ·  SHIFT+MIDI: INSTRUMENTS"
        elif self.fx_page:
            hint = "FX: %s  \u00b7  PRESS FX FOR %s" % (self.fx_page.upper(), "DELAY" if self.fx_page == "reverb" else "THE TRACKS")
        elif not e.device:
            hint = e.status or "NO AUDIO DEVICE"
        else:
            hint = "%s  ·  %s" % (e.device["name"].upper(), self.routing_text(armed))
        s.set("hint", t=hint)

        targets = e.targets() if (e and e.device) else {}
        for n in range(1, 9):
            muted = bool(e and not e.audible(n - 1))      # muted, or another track is soloed
            if self.tab_colours.get(n):
                s.set("track%d_tab" % n, c="#2A2D33" if muted else self.tab_colours[n])
            if e and (n - 1) in targets and (self.recording or ready or not self.playing):
                ch = targets[n - 1]
                peak = float(e.in_peaks.max() if ch is None else max(e.in_peaks[c] for c in ch)
                             if isinstance(ch, tuple) else e.in_peaks[ch])
                level = min(1.0, peak ** 0.5)
            elif self.playing and not muted:
                level = t.level_at(n, t.pos - 1 / tape.RES) * (e.volumes[n - 1] / 0.8 if e else 1)
            else:
                level = 0
            s.set("track%d_meter" % n, v=round(min(1.0, level) * 100))


# ---------------------------------------------------------------- start-up

def start_engine(demo):
    """Start the audio engine, or return None (demo mode) if asked to or if it can't load."""
    if demo:
        return None
    try:
        import alsaaudio  # noqa: F401  (checked here so a missing package means demo mode, not a silent failure)
        import audio
    except ImportError as e:
        print("No audio engine (%s). Run pi-app/setup.sh to install what it needs. Running in demo mode." % e)
        return None
    engine = audio.Engine(bpm=BPM)
    engine.start()
    return engine


def main():
    startup("code loaded")
    ap = argparse.ArgumentParser(description="Console recorder")
    ap.add_argument("--window", action="store_true", help="open a window instead of full screen")
    ap.add_argument("--rotate", type=int, default=int(os.environ.get("CONSOLE_ROTATE", "270")))
    ap.add_argument("--layout", default=os.path.join(HERE, "layouts", "main.ui"))
    ap.add_argument("--demo", action="store_true", help="no audio: show made-up waveforms")
    args = ap.parse_args()

    pygame.display.init()                   # not pygame.init(): that would grab the Pi's default sound device
    pygame.font.init()
    if args.window:
        display = pygame.display.set_mode((ui.WIDTH, ui.HEIGHT))
    else:
        display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    pygame.display.set_caption("Console")
    dw, dh = display.get_size()
    rotate = args.rotate if dh > dw else 0      # an upright screen means nobody rotated it for us
    print("Console: display %dx%d driver %s%s" % (dw, dh, pygame.display.get_driver(),
                                                 ", turning the picture %d degrees" % rotate if rotate else ""))
    print("Keys: see pi-app/CONTROLS.md (Space play, R record, Q quit)")

    startup("screen open")
    screen = ui.Screen.load(args.layout)
    frame = pygame.Surface((ui.WIDTH, ui.HEIGHT))
    engine = start_engine(args.demo)
    startup("audio engine and song loaded")
    keys = queue.Queue()
    clock = None
    note_to = [None]                                  # Transport.midi_note, once there's a transport
    try:
        import midi
        settings = engine.settings if engine else {}
        board = Board(keys)
        # the OP-XY's notes go to the transport, made just below (until then they're dropped)
        _ctl, _clk, clock = midi.start(board, engine, settings.get("clock_device"),
                                       on_note=lambda note, vel: note_to[0] and note_to[0](note, vel))
    except Exception as e:
        board = None
        print("No MIDI input:", e)
    transport = Transport(screen, engine, clock)
    note_to[0] = transport.midi_note
    if engine:
        import linksync
        transport.link = linksync.LinkSync(engine)
    if board:
        board.pads = transport.pad
        board.seq_page = lambda: transport.seq_page
        board.banked = lambda: bool(engine and engine.drums and engine.drums.lanes > 8)
        board.seq_pads = transport.seq_pad
        board.pad_release = transport.pad_release
        transport.shift_held = lambda: board.shift       # the sequencer's box lights up while SHIFT is held
        if engine:
            board.heard = lambda: engine.seq_clock        # where the sequencer is (for live steps)
    project_menu = menu.Menu(os.path.join(HERE, "layouts", "menu.ui"), transport)
    project_menu.kits = kitmenu.KitMenu(os.path.join(HERE, "layouts", "menu.ui"), transport)
    project_menu.kits.main = project_menu        # the drums menu's right column opens the project menu
    restore_terminal = start_terminal_keys(keys)
    fps = pygame.time.Clock()
    startup("controls and menus ready")

    try:
        run_loop(keys, screen, frame, display, transport, project_menu, fps, rotate, dw, dh)
    except Exception:
        import traceback
        details = traceback.format_exc()
        try:
            import audio
            audio.log("Console crashed", details)
        except Exception:
            print(details)
        raise
    finally:
        if restore_terminal:
            restore_terminal()
        if engine:
            transport.playing = False
            engine.stop()
            engine.save(wait=True)
        pygame.quit()
    if project_menu.restart:
        import updater
        print("Restarting with the new version...")
        sys.exit(updater.RESTART_CODE)          # run.sh (or the boot service) starts the app again


def screen_picture(frame, state):
    """The theme page (http://console.local/theme) asks for a picture of the screen by making
    ~/console-data/.screen-request; save the frame as .screen.png for it."""
    now = time.monotonic()
    if now - state["checked"] < 0.2:
        return
    state["checked"] = now
    import theme
    req = os.path.join(theme.DATA, ".screen-request")
    if not os.path.exists(req):
        return
    try:
        os.remove(req)
        tmp = os.path.join(theme.DATA, ".screen-part.png")
        pygame.image.save(frame, tmp)
        os.replace(tmp, os.path.join(theme.DATA, ".screen.png"))
    except Exception as e:
        print("Couldn't save a picture of the screen:", e)


def run_loop(keys, screen, frame, display, transport, project_menu, fps, rotate, dw, dh):
    """The main loop: keys in, screen out, until Q."""
    running = True
    first = True
    picture = {"checked": 0.0}
    while running:
        seconds = fps.tick(FPS) / 1000
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                name = pygame_key(ev)
                if name:
                    keys.put(name)
        while not keys.empty():
            name = keys.get()
            if name == "QUIT":
                if os.environ.get("CONSOLE_SERVICE"):
                    print("Q ignored: Console is running as the boot app. Stop it with: sudo systemctl stop console")
                else:
                    running = False
            elif (project_menu.open or project_menu.kits.open) and isinstance(name, tuple) \
                    and name[0] in ("HOLD", "RELEASE"):
                # CUT and LIFT come from the board as keys you can hold; in the menus they're plain presses
                if name[0] == "HOLD":
                    (project_menu if project_menu.open else project_menu.kits).key(name[1])
            elif project_menu.open:
                project_menu.key(name)
            elif project_menu.kits.open:
                project_menu.kits.key(name)
            elif name == "FILE" and transport.inst_page and transport.instp.mode:
                transport.instp.cancel()            # FILE closes the INSTRUMENTS page's list
            elif name == "FILE" and transport.drum_page:
                project_menu.kits.show()            # on the drum page, FILE is the drum kit menu
            elif name == "FILE":
                project_menu.show()
            elif not (isinstance(name, tuple) and name[0] == "CHAR"):
                transport.key(name)
            TEXT_INPUT["on"] = project_menu.text_input or project_menu.kits.text_input
        transport.tick(seconds)
        if project_menu.restart:
            running = False                         # a software update was installed: start again

        if project_menu.open:
            project_menu.draw(frame)
        elif project_menu.kits.open:
            project_menu.kits.draw(frame)
        else:
            screen.draw(frame)
            transport.draw_full_page(frame)
        out = pygame.transform.rotate(frame, rotate) if rotate else frame
        if out.get_size() != (dw, dh):
            scale = min(dw / out.get_width(), dh / out.get_height())
            size = (round(out.get_width() * scale), round(out.get_height() * scale))
            out = pygame.transform.smoothscale(out, size)
            display.fill((0, 0, 0))
        display.blit(out, ((dw - out.get_width()) // 2, (dh - out.get_height()) // 2))
        pygame.display.flip()
        screen_picture(frame, picture)
        if first:
            first = False
            startup("first picture on the screen")


if __name__ == "__main__":
    main()
