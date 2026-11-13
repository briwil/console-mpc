"""Ableton Link: tempo, bar position and start/stop shared over the network with Ableton Live, phone apps
and anything else that has Link. SETTINGS > MIDI SYNC > LINK turns it on.

- Tempo: while the tape is stopped, Console takes Link's tempo, and a tempo you set goes out to everyone.
  While it plays the tape keeps its tempo (its audio can't stretch); stop to take a new one.
- Start and stop: PLAY starts everyone, on the next bar; someone else starting or stopping starts or
  stops Console. Recording armed with RECORD while stopped starts on that bar too.
- Bars line up: the tape starts on a Link bar line (Link's "quantum" is Console's bar length), and the
  audio thread nudges the tape by a frame now and then to stay locked to Link's clock.

Needs the aalink package (setup.sh installs it); without it, LINK just says so.
"""
import asyncio
import math
import threading
import time

import ctypes
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "link", "liblink.so")      # Ableton's Link, built by move/build-for-move.sh (the Move)


class _H(ctypes.Structure):                          # abl_link and abl_link_session_state: a struct around a pointer
    _fields_ = [("impl", ctypes.c_void_p)]


class _Abl:
    """Ableton Link through its C interface (liblink.so), with the few things LinkSync uses from the aalink package."""

    def __init__(self, bpm):
        L = self.L = ctypes.CDLL(LIB)
        c, d, b, i64, u64 = ctypes.c_void_p, ctypes.c_double, ctypes.c_bool, ctypes.c_int64, ctypes.c_uint64
        for name, args, res in [
                ("abl_link_create", [d], _H), ("abl_link_enable", [_H, b], None), ("abl_link_is_enabled", [_H], b),
                ("abl_link_enable_start_stop_sync", [_H, b], None), ("abl_link_num_peers", [_H], u64),
                ("abl_link_clock_micros", [_H], i64), ("abl_link_create_session_state", [], _H),
                ("abl_link_capture_app_session_state", [_H, _H], None),
                ("abl_link_commit_app_session_state", [_H, _H], None),
                ("abl_link_tempo", [_H], d), ("abl_link_set_tempo", [_H, d, i64], None),
                ("abl_link_beat_at_time", [_H, i64, d], d), ("abl_link_is_playing", [_H], b),
                ("abl_link_set_is_playing", [_H, b, u64], None)]:
            fn = getattr(L, name)
            fn.argtypes, fn.restype = args, res
        self.h = L.abl_link_create(float(bpm))
        self.ss = L.abl_link_create_session_state()
        self._quantum = 4.0

    def _cap(self):
        self.L.abl_link_capture_app_session_state(self.h, self.ss)
        return self.ss

    def _now(self):
        return self.L.abl_link_clock_micros(self.h)

    enabled = property(lambda s: bool(s.L.abl_link_is_enabled(s.h)),
                       lambda s, v: s.L.abl_link_enable(s.h, bool(v)))
    start_stop_sync_enabled = property(lambda s: True, lambda s, v: s.L.abl_link_enable_start_stop_sync(s.h, bool(v)))
    num_peers = property(lambda s: int(s.L.abl_link_num_peers(s.h)))
    quantum = property(lambda s: s._quantum, lambda s, v: setattr(s, "_quantum", float(v)))
    tempo = property(lambda s: s.L.abl_link_tempo(s._cap()))
    beat = property(lambda s: s.L.abl_link_beat_at_time(s._cap(), s._now(), s._quantum))
    playing = property(lambda s: bool(s.L.abl_link_is_playing(s._cap())))

    @tempo.setter
    def tempo(self, bpm):
        ss = self._cap()
        self.L.abl_link_set_tempo(ss, float(bpm), self._now())
        self.L.abl_link_commit_app_session_state(self.h, ss)

    @playing.setter
    def playing(self, on):
        ss = self._cap()
        self.L.abl_link_set_is_playing(ss, bool(on), self._now())
        self.L.abl_link_commit_app_session_state(self.h, ss)


try:
    import aalink
    AVAILABLE = True
except Exception:
    aalink = None
    AVAILABLE = os.path.exists(LIB)

POLL = 0.004                  # seconds between looks at Link
NUDGE_AT = 64                 # frames of drift before the tape is nudged back (about 1.5 ms)
JUMP_AT = 0.25                # beats: more than this off and it's a jump (a loop, a move), not drift


class LinkSync:
    def __init__(self, engine):
        self.engine = engine
        self.link = None
        self.peers = 0
        self.message = ""                  # something for the screen, once
        self._want_play = None             # True / False: PLAY or stop pressed here, to tell everyone
        self._waiting = False              # Link is playing; the tape starts on the next bar
        self._map = None                   # (tape beat, link beat) at the same moment, while playing
        self._drift = 0.0
        self._last = None                  # (tape beat, link beat) at the last look
        self._sent_bpm = None
        self._seen_tempo = None
        self._tempo_warned = False
        self._joined = 0.0
        if AVAILABLE:
            threading.Thread(target=self._thread, daemon=True, name="link").start()

    @property
    def on(self):
        return AVAILABLE and self.engine.sync_mode == "link"

    def request_play(self, playing):
        """PLAY / stop pressed on Console while Link is on."""
        self._want_play = bool(playing)

    # ------------------------------------------------------------ the Link thread

    def _thread(self):
        try:
            asyncio.run(self._main())
        except Exception as e:
            print("Link stopped:", e)

    async def _main(self):
        e = self.engine
        self.link = link = aalink.Link(e.bpm) if aalink else _Abl(e.bpm)
        link.start_stop_sync_enabled = True
        while True:
            await asyncio.sleep(POLL)
            if not self.on:
                if link.enabled:
                    link.enabled = False
                    self._map, self._waiting, self.peers = None, False, 0
                    e.link_nudge = 0
                continue
            if not link.enabled:
                link.enabled = True
                self._joined = time.monotonic()      # see who's there before deciding whose tempo wins
                self._sent_bpm = self._seen_tempo = None
            link.quantum = e.bar_beats()
            self.peers = link.num_peers
            self._tempo(link)
            self._start_stop(link)
            self._follow(link)

    def _tempo(self, link):
        e = self.engine
        tempo = link.tempo
        if self._sent_bpm is None:
            if time.monotonic() - self._joined < 1.5:
                return
            if link.num_peers == 0:
                link.tempo = e.bpm                 # on our own: our tempo is the session's
                self._sent_bpm = self._seen_tempo = e.bpm
                return
            self._sent_bpm = e.bpm                 # joining others: take theirs (below)
        if e.bpm != self._sent_bpm and not e.playing:
            link.tempo = e.bpm                     # changed here: tell everyone
            self._sent_bpm = self._seen_tempo = e.bpm
            return
        if abs(tempo - (self._seen_tempo or tempo)) > 0.005 or abs(tempo - e.bpm) > 0.005:
            self._seen_tempo = tempo
            if not e.playing:
                if e.set_bpm(round(tempo, 2)):
                    self._sent_bpm = e.bpm
                    self.message = "TEMPO %.1f BPM FROM LINK" % tempo
                self._tempo_warned = False
            elif not self._tempo_warned and abs(tempo - e.bpm) > 0.05:
                self._tempo_warned = True
                self.message = "LINK TEMPO IS NOW %.1f: STOP TO TAKE IT" % tempo

    def _start_stop(self, link):
        e = self.engine
        if self._want_play is not None:
            want, self._want_play = self._want_play, None
            if link.playing != want:
                link.playing = want
            if not want:
                self._waiting = False
        playing = link.playing
        if playing and not e.playing and not self._waiting and self._map is None:
            self._waiting = True                   # start the tape on the next bar line
            q = link.quantum
            self._start_at = math.ceil(link.beat / q - 1e-6) * q
            if link.beat - (self._start_at - q) < 0.05:
                self._start_at -= q                # right on a bar line already: go now
        if self._waiting:
            if not playing:
                self._waiting = False
            elif link.beat >= self._start_at:
                self._waiting = False
                late = link.beat - self._start_at   # we looked a moment after the bar line
                bar = e.bar_beats()                 # from the start of the playhead's bar, so the bars line up
                start = math.floor(e.beats() / bar + 1e-6) * bar + late
                e.sync_start(start)
                self._map = (start - late, self._start_at)
                self._drift, self._last = 0.0, None
        if not playing and e.playing and self._map is not None:
            e.sync_stop()
        if not e.playing:
            self._map = None
            e.link_nudge = 0

    def _follow(self, link):
        """Keep the playing tape on Link's beat: nudge it a frame per block while it's off."""
        e = self.engine
        if self._map is None or not e.playing:
            return
        if abs(link.tempo - e.bpm) > 0.005:
            e.link_nudge = 0                       # different tempos: can't lock (see _tempo)
            return
        tape0, link0 = self._map
        lb, tb = link.beat, e.beats()
        expected = tape0 + (lb - link0)
        if self._last is not None:
            # the tape jumped (round the loop, or moved): keep the phase, take the new place
            moved = (tb - self._last[0]) - (lb - self._last[1])
            if abs(moved) > JUMP_AT:
                self._map = (tb - (lb - link0), link0)
                self._last, self._drift = (tb, lb), 0.0
                return
        self._last = (tb, lb)
        off = (tb - expected) * e.frames_per_beat()          # frames: + the tape is ahead
        self._drift = 0.95 * self._drift + 0.05 * off         # the tape moves in blocks: smooth it
        if self._drift > NUDGE_AT:
            e.link_nudge = -1
        elif self._drift < -NUDGE_AT:
            e.link_nudge = 1
        elif abs(self._drift) < NUDGE_AT / 4:
            e.link_nudge = 0
