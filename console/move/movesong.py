"""Song mode (left button 2), OP-XY style: a list of rows, each one a pattern for every instrument and how many
times it plays. With song mode on, PLAY starts at row 1 and the rows follow each other, then it starts again.

  step buttons 1-16   the rows (press one past the end: a new row, a copy of the last). Lit: the rows there are;
                      bright: the row picked; blinking: the row playing
  knobs 1-7           the picked row's pattern for instruments 1-7 (turned all the way down: "-", leave it as is)
  Shift + knobs 1-7   the picked row's PUNCH FX pattern for them (the screen shows those while Shift is held)
  knob 8              how many times the row plays (1-16)
  + / -               song mode on / off
  Delete + a row      take the row out

Saved next to the songs, one file per song (data/songmode/<song>.json).
"""
import json
import os
import time

import knobgate

PATTERNS = 16
MAX_ROWS = 16
REPEAT_KNOB = 8


class Song:
    def __init__(self, T):
        self.T = T
        self.rows = []              # [{"pats": {slot: pattern or None}, "punch": {slot: punch pattern or None}, "repeat": n}]
        self.on = False
        self.pick = 0               # the row the knobs change
        self.playing_row = None     # the row playing (song mode on and playing)
        self._loops = 0
        self._cycle = None
        self._queued = False
        self._was_playing = False
        self._song = None
        self._turned = {}

    # ------------------------------------------------------------ saving

    def path(self):
        data = os.environ.get("CONSOLE_DATA", "/data/UserData/console/data")
        name = getattr(self.T.engine, "song", None) or "song"
        return os.path.join(data, "songmode", "%s.json" % name)

    def load(self):
        self._song = getattr(self.T.engine, "song", None)
        self.rows, self.on, self.pick = [], False, 0
        try:
            d = json.load(open(self.path()))
            self.on = False                       # (song mode is always off when a song opens; the rows are kept)
            for r in d.get("rows", [])[:MAX_ROWS]:
                pats = {int(k): (None if v is None else max(0, min(PATTERNS - 1, int(v))))
                        for k, v in r.get("pats", {}).items()}
                pun = {int(k): (None if v is None else max(0, min(PATTERNS - 1, int(v))))
                       for k, v in (r.get("punch") or {}).items()}
                self.rows.append({"pats": pats, "punch": pun, "repeat": max(1, min(16, int(r.get("repeat", 1))))})
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path()), exist_ok=True)
            with open(self.path(), "w") as fh:
                json.dump({"on": self.on, "rows": [{"pats": {str(k): v for k, v in r["pats"].items()},
                                                    "punch": {str(k): v for k, v in r.get("punch", {}).items()},
                                                    "repeat": r["repeat"]} for r in self.rows]}, fh)
        except OSError as ex:
            print("Song mode: couldn't save (%s)" % ex)

    def check_song(self):
        """The song changed (loaded another): its song mode."""
        if getattr(self.T.engine, "song", None) != self._song:
            self.load()

    # ------------------------------------------------------------ the instruments

    def slots(self):
        e = self.T.engine
        return [i for i, m in enumerate(e.slots) if m][:7] if e else []

    def seq_of(self, slot):
        e = self.T.engine
        m = e.slots[slot] if slot < len(e.slots) else None
        return e.seqs.get(m) if m else None

    def short(self, slot):
        m = self.T.engine.slots[slot]
        return str(m).upper()[:5]

    # ------------------------------------------------------------ controls

    def row_button(self, n, delete=False):
        """Step button n (1-16)."""
        i = n - 1
        if delete:
            if i < len(self.rows):
                del self.rows[i]
                self.pick = max(0, min(self.pick, len(self.rows) - 1))
                self.T.say("ROW %d TAKEN OUT" % (i + 1), 2)
                self.save()
            return
        if i >= len(self.rows):
            if len(self.rows) >= MAX_ROWS:
                return
            if self.rows:
                last = self.rows[-1]
                self.rows.append({"pats": dict(last["pats"]), "punch": dict(last.get("punch", {})),
                                  "repeat": last["repeat"]})
            else:
                import punch
                self.rows.append({"pats": {s: (getattr(self.seq_of(s), "current", 0)) for s in self.slots()},
                                  "punch": {s: punch.state(self.seq_of(s)).current for s in self.slots()
                                            if self.seq_of(s) is not None},
                                  "repeat": 1})
            i = len(self.rows) - 1
            self.T.say("ROW %d ADDED" % (i + 1), 2)
            self.save()
        self.pick = i

    def knob(self, number, delta, shift=False):
        if not self.rows:
            self.T.say("PRESS STEP BUTTON 1 TO ADD A ROW", 2)
            return
        row = self.rows[self.pick]
        way = knobgate.gate(("song", number), delta, False)   # a few clicks a choice
        if not way:
            return
        if number == REPEAT_KNOB:
            row["repeat"] = max(1, min(16, row["repeat"] + way))
            self.T.say("ROW %d PLAYS %d TIME%s" % (self.pick + 1, row["repeat"], "" if row["repeat"] == 1 else "S"), 2)
        else:
            slots = self.slots()
            if number > len(slots):
                return
            s = slots[number - 1]
            key = "punch" if shift else "pats"
            pats = row.setdefault(key, {})
            v = pats.get(s)
            v = -1 if v is None else v
            v = max(-1, min(PATTERNS - 1, v + way))
            pats[s] = None if v < 0 else v
            self.T.say("ROW %d  %s  %s" % (self.pick + 1, self.short(s), "-" if v < 0 else
                                            ("PUNCH FX %d" if shift else "PATTERN %d") % (v + 1)), 2)
        self.save()

    def set_on(self, on):
        if on != self.on:
            self.toggle()

    def toggle(self):
        self.on = not self.on
        self._ready = False
        self.T.say(("SONG MODE ON: PLAY STARTS AT ROW 1" if self.rows else "SONG MODE ON: ADD ROWS FIRST (STEPS)")
                   if self.on else "SONG MODE OFF: THE PICKED PATTERN PLAYS", 2)
        self.save()

    # ------------------------------------------------------------ playing

    def master(self):
        """The sequencer whose pattern length counts the rows: the first instrument's."""
        for s in self.slots():
            q = self.seq_of(s)
            if q is not None:
                return q
        return None

    def apply(self, i, playing):
        import punch
        for s, p in self.rows[i]["pats"].items():
            q = self.seq_of(s)
            if q is not None and p is not None:
                q.choose_pattern(p, playing)
        for s, p in self.rows[i].get("punch", {}).items():
            q = self.seq_of(s)
            if q is not None and p is not None:
                punch.choose(q, p, playing)
        self.T.engine.seq_changed()

    def tick(self):
        """Every frame: start at row 1 on PLAY; queue the next row in the last time round the current one."""
        T, e = self.T, self.T.engine
        if not e:
            return
        self.check_song()
        playing = T.playing
        if not (self.on and self.rows):
            self._was_playing, self.playing_row = playing, None
            return
        if playing and (not self._was_playing or self.playing_row is None):   # (or song mode turned on while playing)
            self.playing_row, self._loops, self._cycle, self._queued = 0, 0, None, False
        elif not playing:
            if self._was_playing or not getattr(self, "_ready", False):
                self.apply(0, False)                       # stopped: ready at row 1
                self._ready = True
            self.playing_row = None
            self._was_playing = False
            return
        self._ready = False
        self._was_playing = True
        m = self.master()
        if m is None:
            return
        fpb = e.frames_per_beat()
        try:
            length = m.pattern_frames(fpb)
        except Exception:
            return
        cycle = (m.anchor, int(max(0, e.seq_clock - m.anchor) // max(1, length)))
        if self._cycle is None:
            self._cycle = cycle
        if cycle[0] == self._cycle[0] and cycle[1] < self._cycle[1]:
            # the clock went back (PLAY: the sequencer's clock is reset a moment after this first looked at it, so
            # it first saw the old stopped time): start counting again, it isn't a pass played
            self._cycle = cycle
        if cycle != self._cycle:
            self._cycle = cycle
            if self._queued:                               # the next row has started
                self.playing_row = (self.playing_row + 1) % len(self.rows)
                self._loops, self._queued = 0, False
            else:
                self._loops += 1
        row = self.rows[min(self.playing_row, len(self.rows) - 1)]
        into = (e.seq_clock - m.anchor) % max(1, length)
        if into < 0.15 * length:
            return                                         # let this row's first pass begin before queuing the next
        if not self._queued and self._loops >= row["repeat"] - 1:
            self.apply((self.playing_row + 1) % len(self.rows), True)
            self._queued = True

    # ------------------------------------------------------------ lights

    def step_lights(self):
        out = []
        blink = int(time.monotonic() * 4) % 2
        for i in range(16):
            if i >= len(self.rows):
                out.append(0)
            elif i == self.playing_row:
                out.append(127 if blink else 30)
            else:
                out.append(127 if i == self.pick else 30)
        return out
