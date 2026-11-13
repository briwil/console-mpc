"""MIDI: the control board's keys and knobs, and tempo sync with an OP-XY (or anything else with MIDI clock).

Sync works either way round (the SETTINGS menu, saved as "sync" in settings.json):
  external  Console follows the OP-XY's clock, start and stop.
  internal  Console leads: it sends clock, start and stop to the OP-XY.

Reads ALSA raw MIDI devices (/dev/snd/midiC<card>D0) directly, so nothing extra
needs installing. Each source runs in its own thread and keeps retrying, so
devices can be plugged in and out while the app runs.
"""
import os
import re
import threading
import time

CONTROLLER_NAMES = ("console controls", "circuitpython")


def midi_cards():
    """[(card index, id, description)] for every card with a raw MIDI port."""
    try:
        with open("/proc/asound/cards") as f:
            cards = re.findall(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)$", f.read(), re.M)
    except OSError:
        return []
    return [(int(i), cid, desc) for i, cid, desc in cards if os.path.exists("/dev/snd/midiC%sD0" % i)]


def is_controller(cid, desc):
    text = (cid + " " + desc).lower()
    return any(n in text for n in CONTROLLER_NAMES)


class Parser:
    """Turns a MIDI byte stream into messages: (status, data1, data2) tuples and real-time bytes."""

    LENGTH = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}

    def __init__(self, on_message, on_realtime):
        self.on_message, self.on_realtime = on_message, on_realtime
        self.status, self.data, self.sysex = None, [], False

    def feed(self, data):
        for b in data:
            if b >= 0xF8:
                self.on_realtime(b)                  # clock, start, continue, stop: can arrive mid-message
                continue
            if b == 0xF0:
                self.sysex = True
                continue
            if self.sysex:
                if b == 0xF7 or b >= 0x80:
                    self.sysex = False
                if b < 0x80 or b == 0xF7:
                    continue
            if b >= 0x80:
                self.status, self.data = b, []
                continue
            if self.status is None:
                continue
            self.data.append(b)
            need = self.LENGTH.get(self.status & 0xF0, 0) if self.status < 0xF0 else {0xF1: 1, 0xF2: 2, 0xF3: 1}.get(self.status, 0)
            if need and len(self.data) == need:
                self.on_message(self.status, self.data[0], self.data[1] if need > 1 else 0)
                self.data = []
                if self.status >= 0xF0:
                    self.status = None               # system common messages don't use running status


class Source(threading.Thread):
    """Reads one kind of MIDI device in the background, reconnecting as needed."""

    def __init__(self, choose, on_message, on_realtime=None, label="MIDI"):
        super().__init__(daemon=True, name=label)
        self.choose = choose                         # function(cards) -> card index or None
        self.label = label
        self.parser = Parser(on_message, on_realtime or (lambda b: None))
        self.connected = None                        # description of the connected device, or None
        self.stopped = False

    def run(self):
        while not self.stopped:
            idx = self.choose(midi_cards())
            if idx is None:
                self.connected = None
                time.sleep(2)
                continue
            path = "/dev/snd/midiC%dD0" % idx
            try:
                fd = os.open(path, os.O_RDONLY)
            except OSError as e:
                print("%s: can't open %s (%s)" % (self.label, path, e))
                time.sleep(2)
                continue
            self.connected = path
            print("%s: reading %s" % (self.label, path))
            try:
                while not self.stopped:
                    data = os.read(fd, 256)
                    if not data:
                        break
                    self.parser.feed(data)
            except OSError:
                pass
            finally:
                os.close(fd)
                self.connected = None
                print("%s: %s disconnected" % (self.label, path))
            time.sleep(1)


class Clock:
    """Follows MIDI clock, start, stop, continue and song position from one device."""

    def __init__(self, engine):
        self.engine = engine
        self.ticks = []                              # times of the last clock ticks
        self.last_tick = 0.0
        self.song_pos = 0.0                          # beats, from the last song position message

    @property
    def active(self):
        return time.monotonic() - self.last_tick < 0.5

    @property
    def bpm(self):
        if len(self.ticks) < 25 or not self.active:
            return None
        span = self.ticks[-1] - self.ticks[0]
        return 60.0 / (span / (len(self.ticks) - 1) * 24) if span > 0 else None

    def following(self):
        return self.engine is not None and self.engine.sync_mode == "external"

    def realtime(self, b):
        now = time.monotonic()
        if b in (0xFA, 0xFB, 0xFC) and not self.following():
            return
        if b == 0xF8:                                # clock: 24 per beat
            if now - self.last_tick > 0.5:
                self.ticks = []
            self.ticks.append(now)
            del self.ticks[:-97]                     # about 4 beats of history
            self.last_tick = now
        elif b == 0xFA and self.engine:              # start
            self.engine.sync_start(0.0)
        elif b == 0xFB and self.engine:              # continue
            self.engine.set_beats(self.song_pos)
            self.engine.sync_continue()
        elif b == 0xFC and self.engine:              # stop
            self.engine.sync_stop()

    def message(self, status, d1, d2):
        if status == 0xF2 and self.following():      # song position, in 16th notes
            self.song_pos = ((d2 << 7) | d1) / 4.0
            if self.engine and not self.engine.playing:
                self.engine.set_beats(self.song_pos)


class ClockOut(threading.Thread):
    """In internal sync, sends MIDI clock (24 per beat, all the time so the other device shows the tempo),
    plus start / continue / stop as Console plays and stops."""

    def __init__(self, engine, choose):
        super().__init__(daemon=True, name="Clock out")
        self.engine = engine
        self.choose = choose
        self.fd = None
        self.connected = None

    def _close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = self.connected = None

    def _send(self, data):
        try:
            os.write(self.fd, bytes(data))
            return True
        except OSError:
            print("Clock out: %s disconnected" % self.connected)
            self._close()
            return False

    def run(self):
        e = self.engine
        was_playing = False
        next_tick = 0.0
        while True:
            if e.sync_mode != "internal":
                if self.fd is not None:
                    if was_playing:
                        self._send([0xFC])
                    self._close()
                was_playing = False
                time.sleep(0.2)
                continue
            if self.fd is None:
                idx = self.choose(midi_cards())
                path = "/dev/snd/midiC%dD0" % idx if idx is not None else None
                try:
                    self.fd = os.open(path, os.O_WRONLY) if path else None
                except OSError:
                    self.fd = None
                if self.fd is None:
                    time.sleep(2)
                    continue
                self.connected = path
                print("Clock out: sending to", path)
                next_tick = time.perf_counter()
            now = time.perf_counter()
            playing = e.playing
            if playing and not was_playing:
                beats = e.beats()
                if beats < 0.01:
                    ok = self._send([0xFA])                       # start from the top
                else:
                    sixteenths = int(beats * 4) & 0x3FFF
                    ok = self._send([0xF2, sixteenths & 0x7F, sixteenths >> 7, 0xFB])   # song position, continue
                next_tick = now                                   # the first clock after start is beat 1
                was_playing = playing
                if not ok:
                    continue
            elif was_playing and not playing:
                was_playing = False
                if not self._send([0xFC]):
                    continue
            if now >= next_tick:
                if not self._send([0xF8]):
                    continue
                next_tick += 60.0 / (max(20.0, e.bpm) * 24)
                if now - next_tick > 0.1:                         # fell behind (busy system): don't rush to catch up
                    next_tick = now
            time.sleep(max(0.0, min(0.002, next_tick - time.perf_counter())))


def start(on_control, engine, clock_name=None, on_note=None):
    """Start reading the control board and a clock source.

    on_control(kind, number, value) gets ("note", note, 1 or 0) and ("cc", number, value).
    on_note(note, velocity) gets the notes played on the clock source (the OP-XY's keys), velocity 0 for
    a note let go: they play the synth that's open.
    Returns (controller source, clock source, Clock).
    """
    def control_message(status, d1, d2):
        kind = status & 0xF0
        if kind == 0x90:
            on_control("note", d1, 1 if d2 else 0)
        elif kind == 0x80:
            on_control("note", d1, 0)
        elif kind == 0xB0:
            on_control("cc", d1, d2)

    def pick_controller(cards):
        for i, cid, desc in cards:
            if is_controller(cid, desc):
                return i
        return None

    def pick_clock(cards):
        for i, cid, desc in cards:
            if is_controller(cid, desc):
                continue
            if clock_name:
                if clock_name.lower() in (cid + " " + desc).lower():
                    return i
            else:
                return i                             # the first other MIDI device, e.g. the OP-XY
        return None

    clock = Clock(engine)

    def clock_message(status, d1, d2):
        kind = status & 0xF0
        if on_note and kind in (0x80, 0x90):
            on_note(d1, d2 if kind == 0x90 else 0)
        clock.message(status, d1, d2)

    ctl = Source(pick_controller, control_message, label="Controls")
    clk = Source(pick_clock, clock_message, clock.realtime, label="Clock")
    ctl.start()
    clk.start()
    if engine:
        ClockOut(engine, pick_clock).start()
    return ctl, clk, clock
