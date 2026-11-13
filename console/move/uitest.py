"""The menu test: Console goes through its own screens by itself, the way a very thorough person would, to find
the screens and button presses that go wrong.

Start it (Console running or not):

    ssh -i ~/.ssh/move_key ableton@move.local "echo menu 60 > /data/UserData/console/stress"

(60 = minutes, 120 or more for a full run.) Like the stress test it uses its own projects (console/stress-data), and
Shift + Back stops it early. The report is console/stress-report.txt, written as it goes.

How it works: every screen it gets to is told apart by what's open (a menu, a picker, a page) and the screen's
title. On each screen it tries every control once (each button, with and without Shift, the wheel, push, the
knobs, some step buttons and pads, Copy and Delete with another control), then goes on to the nearest screen that
still has controls it hasn't tried. When every screen it can reach is done, it starts again with another set-up:

  1. an empty project
  2. a drum machine and a synth, playing
  3. the same with an insert effect and a song insert
  4. all eight slots full

and then, for the time left, presses at random. Every 80 presses (and at each set-up's end) it presses Back six
times: a menu, a picker or an FX page still open after that is noted.

What it notes (each once, with the presses that led to it, so it can be repeated):
  - a Python error in a press (the app would have crashed: here it's noted and the test goes on)
  - SCREEN ERROR (a page that couldn't draw), with its Python error
  - text running off the edge of the screen, letters the screen's font hasn't got (they show as ?), and two bits
    of text drawn over each other (checked once the screen has stopped moving)
  - Back not getting out of a menu or picker
  - a press that took over 1.5 seconds (loading an instrument can, the rest shouldn't), or a screen that took over
    0.15 seconds to draw
  - messages on the screen with ERROR or FAIL in them

It can't tell a screen that shows the wrong thing (that needs a person), only one that breaks.
"""
import os
import re
import time
import traceback
import random

import stress
from stress import _cleanup, REPORT

SETTLE = 0.3                    # seconds after a press before the screen is looked at
BACK_EVERY = 80                 # presses between Back-outs
SLOW_PRESS = 1.5
SLOW_DRAW = 0.15
SETUPS = ["an empty project", "a drum machine and a synth, playing", "with an insert and a song insert",
          "all eight slots full"]

SHIFT, BACK, WHEEL = 49, 51, 14
BUTTONS = {85: "PLAY", 86: "RECORD", 58: "LOOP", 62: "LEFT", 63: "RIGHT", 56: "UNDO", 52: "DROP", 118: "SAMPLE",
           88: "MUTE", 50: "MENU", 3: "PUSH", 43: "LEFT BUTTON 1", 42: "LEFT BUTTON 2", 41: "LEFT BUTTON 3",
           40: "LEFT BUTTON 4", 55: "PLUS", 54: "MINUS"}
COPY, DELETE = 60, 119


def _cc(n, v):
    return bytes((0xB0, n, v))


def _on(n, v=100):
    return bytes((0x90, n, v))


def _off(n):
    return bytes((0x90, n, 0))


def _press(cc, t=0.0):
    return [(t, _cc(cc, 127)), (t + 0.08, _cc(cc, 0))]


def _shifted(events):
    return [(0.0, _cc(SHIFT, 127))] + [(t + 0.03, b) for t, b in events] + \
        [(max(t for t, _ in events) + 0.06, _cc(SHIFT, 0))]


def _tap(note, t=0.0, hold=0.08):
    return [(t, _on(note)), (t + hold, _off(note))]


def _turn(cc, d, n=3):
    return [(k * 0.03, _cc(cc, d if d > 0 else 128 + d)) for k in range(n)]


def actions():
    """{name: [(seconds, midi)]}: everything tried on each screen."""
    a = {}
    for cc, name in BUTTONS.items():
        a[name] = _press(cc)
        a["SHIFT + " + name] = _shifted(_press(cc))
    a["BACK"] = _press(BACK)
    a["WHEEL RIGHT"] = [(0.0, _cc(WHEEL, 1))]
    a["WHEEL LEFT"] = [(0.0, _cc(WHEEL, 127))]
    a["WHEEL RIGHT x4"] = [(k * 0.04, _cc(WHEEL, 1)) for k in range(4)]
    a["SHIFT + WHEEL RIGHT"] = _shifted([(0.0, _cc(WHEEL, 1))])
    a["SHIFT + WHEEL LEFT"] = _shifted([(0.0, _cc(WHEEL, 127))])
    for k in range(8):
        a["KNOB %d UP" % (k + 1)] = _turn(71 + k, 1)
        a["KNOB %d DOWN" % (k + 1)] = _turn(71 + k, -1)
    for k in (0, 7):
        a["SHIFT + KNOB %d UP" % (k + 1)] = _shifted(_turn(71 + k, 1))
        a["SHIFT + KNOB %d DOWN" % (k + 1)] = _shifted(_turn(71 + k, -1))
    a["SHIFT + TOUCH KNOB 1"] = _shifted(_tap(0))
    for s in (1, 2, 8, 16):
        a["STEP %d" % s] = _tap(15 + s)
    a["SHIFT + STEP 1"] = _shifted(_tap(16))
    a["HOLD STEP 1 + KNOB 1 UP"] = [(0.0, _on(16))] + [(0.05 + t, b) for t, b in _turn(71, 1)] + [(0.25, _off(16))]
    a["PAD 1"] = _tap(68, hold=0.15)
    a["PAD 5"] = _tap(72, hold=0.15)
    a["PAD 17"] = _tap(84, hold=0.15)
    a["SHIFT + PAD 2"] = _shifted(_tap(69))
    a["COPY"] = _press(COPY)
    a["SHIFT + COPY"] = _shifted(_press(COPY))
    a["DELETE + PUSH"] = [(0.0, _cc(DELETE, 127))] + [(0.05 + t, b) for t, b in _press(3)] + [(0.25, _cc(DELETE, 0))]
    a["DELETE + STEP 1"] = [(0.0, _cc(DELETE, 127))] + [(0.05 + t, b) for t, b in _tap(16)] + [(0.25, _cc(DELETE, 0))]
    a["COPY + STEP 2"] = [(0.0, _cc(COPY, 127))] + [(0.05 + t, b) for t, b in _tap(17)] + [(0.25, _cc(COPY, 0))]
    return a


class Recorder:
    """Wraps the app's Frame: what text it draws, where, and the filled boxes in between (a box drawn over text
    hides it, so text under a message or a pop-up isn't "drawn over")."""

    def __init__(self, frame):
        import screen
        self.font, self.small_font = screen.FONT, screen.SMALL
        self.ops = []
        f = frame
        orig = {n: getattr(f, n) for n in ("text", "small", "big", "rect", "clear")}

        def clear():
            self.ops = []
            return orig["clear"]()

        def rect(x, y, w, h, c=1):
            if w > 2 and h > 2:
                self.ops.append(("r", x, y, w, h, c))
            return orig["rect"](x, y, w, h, c)

        def mk(kind, h, per):
            def draw(x, y, s, c=1, limit=None, **kw):
                r = orig[kind](x, y, s, c, limit) if kind != "big" else orig[kind](x, y, s, c)
                t = str(s).upper()
                if limit is not None and kind != "big":
                    t = t[:max(0, limit // per)]
                if t:
                    self.ops.append(("t", x, y, len(t) * per - (2 if kind == "big" else 1), h, t, c, kind))
                return r
            return draw
        f.clear, f.rect = clear, rect
        f.text, f.small, f.big = mk("text", 7, 6), mk("small", 5, 4), mk("big", 14, 12)

    def header(self):
        for op in self.ops:
            if op[0] == "t" and op[2] <= 2:
                return op[5]
        return ""

    def texts(self):
        return [op[5] for op in self.ops if op[0] == "t"]

    def problems(self):
        """[(kind, text)] in this frame."""
        out = []
        ops = self.ops
        for i, op in enumerate(ops):
            if op[0] != "t":
                continue
            _, x, y, w, h, t, c, kind = op
            if x < 0 or y < 0 or x + w > 128 or y + h > 64:
                out.append(("OFF THE SCREEN", "%r at x %d, y %d (%d wide)" % (t, x, y, w)))
            font = self.small_font if kind == "small" else self.font
            bad = sorted(set(ch for ch in t if ch.strip() and ch not in font))
            if bad:
                out.append(("NOT IN THE FONT", "%s in %r" % (" ".join(bad), t)))
            for j in range(i + 1, len(ops)):
                o = ops[j]
                if o[0] == "r" and _meet((x, y, w, h), o[1:5]):
                    break                                   # (covered: whatever comes later is drawn over a box)
                if o[0] != "t" or o[6] != c:
                    continue
                ix = min(x + w, o[1] + o[3]) - max(x, o[1])
                iy = min(y + h, o[2] + o[4]) - max(y, o[2])
                if ix >= 2 and iy >= 2:
                    out.append(("DRAWN OVER EACH OTHER", "%r and %r" % (t, o[5])))
        return out


def _meet(a, b):
    return min(a[0] + a[2], b[0] + b[2]) > max(a[0], b[0]) and min(a[1] + a[3], b[1] + b[3]) > max(a[1], b[1])


class UiTest:
    catch = True                                         # app.py: a Python error in a press is noted, not a crash

    def __init__(self, minutes, T, m, e, board):
        self.T, self.m, self.e, self.board = T, m, e, board
        self.start = time.monotonic()
        self.end = self.start + minutes * 60
        seed = int(time.time())
        self.rng = random.Random(seed)
        self.acts = actions()
        self.names = sorted(self.acts)
        self.pending = []
        self.busy_until = 0.0
        self.trail = []                                  # the last presses: what led to a problem
        self.rec = None
        self.look = None                                 # the screen, once it has settled after a press
        self.waiting = False
        self.wait_from = 0.0
        self.last = None                                 # (screen before, press) waiting for where it led
        self.graph = {}                                  # screen -> {press: screen it led to}
        self.tried = {}                                  # screen -> presses tried there
        self.seen = {}                                   # problem key -> count
        self.problems = []
        self.slow = []
        self.presses = 0
        self.since_back = 0
        self.setup = 0
        self.setup_end = 0.0
        self.screens_all = set()
        self.random = False
        self.backing = None                              # the screen a Back-out started on
        self.rec_since = None
        self.finished = False
        try:
            import crashlog
            self.crashlog = crashlog
        except ImportError:
            self.crashlog = None
        try:
            self.rep = open(REPORT, "w", buffering=1)
        except OSError:
            self.rep = None
        self.say("CONSOLE MENU TEST  started %s, %d minutes (seed %d)" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                                                          minutes, seed))
        self.say("%d presses tried on each screen" % len(self.acts))
        m.update_action = lambda: None                   # (no software updates in the middle of the test)
        self.minutes = minutes
        self.next_setup(time.monotonic())

    # ------------------------------------------------------------ the app calls these

    def watch_frame(self, frame):
        self.rec = Recorder(frame)

    def handle(self, fn, name, T, m, e):
        t0 = time.monotonic()
        try:
            fn(name, T, m, e)
        except Exception:                                # noqa: BLE001
            self.problem("PYTHON ERROR", "pressing %s on %s" % (name, self.here_text()),
                         traceback.format_exc().rstrip())
        dt = time.monotonic() - t0
        if dt > SLOW_PRESS:
            self.slow.append("%.1f s: %s on %s" % (dt, name, self.here_text()))

    def drawn(self, frame, seconds):
        now = time.monotonic()
        import pages
        if pages.last_error:
            err, pages.last_error = pages.last_error, None
            self.problem("SCREEN ERROR", self.here_text(), err)
        if seconds > SLOW_DRAW:
            key = ("slow draw", self.here_text())
            if key not in self.seen:
                self.seen[key] = 1
                self.slow.append("%.2f s to draw %s" % (seconds, self.here_text()))
        if not self.waiting or now < self.busy_until or self.rec is None:
            return
        moving = self.T.pagefx.state() is not None or (pages._CAR.get("pos") is not None and
                                                     now - pages._CAR.get("t", 0) < 0.2 and
                                                     pages._CAR.get("pos") != pages._CAR.get("target"))
        if moving and now - self.wait_from < 3:
            return                                       # (still sliding: look once it has stopped)
        self.look = (self.where(), list(self.rec.ops), self.rec.problems(), self.rec.texts())
        self.waiting = False

    # ------------------------------------------------------------ helpers

    def clock(self):
        s = int(time.monotonic() - self.start)
        return "%3d:%02d" % (s // 60, s % 60)

    def left(self):
        return max(0, int(self.end - time.monotonic()))

    def say(self, text):
        line = "%s  %s" % (self.clock(), text) if text else ""
        if self.rep:
            try:
                self.rep.write(line + "\n")
            except OSError:
                pass
        if self.crashlog:
            self.crashlog.action("[menu test] " + text)

    def problem(self, kind, where, detail=""):
        key = (kind, where, detail.splitlines()[-1] if detail else "")
        self.seen[key] = self.seen.get(key, 0) + 1
        if self.seen[key] > 1:
            return
        self.problems.append(key)
        self.say("PROBLEM: %s  (%s)" % (kind, where))
        if detail:
            for line in detail.splitlines():
                self.say("    " + line)
        self.say("    after: " + " > ".join(self.trail[-12:]))

    def where(self):
        T, m = self.T, self.m
        if m.open:
            s = "MENU " + str(getattr(m, "mode", "")).upper()
            if getattr(m, "confirm", None):
                s += " (CONFIRM %s)" % str(m.confirm[0]).upper()
            if getattr(m, "deleting", False):
                s += " (DELETING)"
            if getattr(m, "rename_pick", False):
                s += " (RENAMING)"
            if getattr(m, "editing", False):
                s += " (EDITING)"
        elif m.kits.open:
            s = "PRESETS " + str(getattr(m.kits, "mode", "")).upper()
        else:
            import pagefx
            s = pagefx.label(T) or "?"
            if T.inst_page and getattr(T.instp, "mode", None):
                s += " (PICKER %s)" % str(T.instp.mode).upper()
            if T.sbrowse.active:
                s += " (SAMPLES)"
            if T.focus.track is not None and not (T.seq_page or T.drum_page or T.inst_page or T.fx_page or T.song_page):
                s += " (ZOOMED)"
        head = re.sub(r"\d+", "#", self.rec.header() if self.rec else "")[:28]
        return s + (" | " + head if head else "")

    def here_text(self):
        return self.look[0] if self.look else "?"

    def disk_low(self):
        try:
            st = os.statvfs(stress.HOME)
            return st.f_bavail * st.f_frsize < 400 * 1024 * 1024
        except OSError:
            return False

    def send(self, b):
        if b[0] & 0xF0 == 0xB0 and b[1] == BACK and b[2] and getattr(self.board, "shift", False):
            return                                       # Shift + Back would quit: never
        try:
            self.board(b)
        except Exception:                                # noqa: BLE001
            self.problem("PYTHON ERROR", "a press on %s" % self.here_text(), traceback.format_exc().rstrip())

    def run(self, name, events, now):
        self.trail.append(name)
        del self.trail[:-30]
        if self.crashlog:
            self.crashlog.action("[menu test] " + name)
        for t, b in events:
            self.pending.append((now + t, b))
        self.busy_until = now + max(t for t, _ in events) + SETTLE
        self.waiting, self.wait_from, self.look = True, now, None
        self.presses += 1

    def safe(self, name):
        if self.disk_low() and name in ("RECORD", "SHIFT + RECORD", "SHIFT + MENU"):
            return False                                 # (recording and exporting fill the disk)
        return True

    # ------------------------------------------------------------ set-ups

    def next_setup(self, now):
        if self.setup >= len(SETUPS):
            if not self.random:
                self.random = True
                self.say("")
                self.say("RANDOM PRESSES until the time's up")
            return
        k = self.setup
        self.setup += 1
        self.graph, self.tried = {}, {}
        budget = (self.end - now) * 0.8 / (len(SETUPS) - k + 1)
        self.setup_end = now + budget
        self.say("")
        self.say("%d. %s (up to %d minutes)" % (k + 1, SETUPS[k].upper(), budget // 60))
        e, T = self.e, self.T
        try:
            self.release()
            if e.playing:
                self.send(_cc(85, 127))
                self.send(_cc(85, 0))
            T.new_song(None)
            for s in range(8):
                for pos in (0, 1):
                    ins = (getattr(T, "_insfx", None) or {}).get((s, pos))
                    if ins is not None and ins.index:
                        ins.choose(0)
                e.set_slot(s, None)
            if getattr(T, "_songfx", None):
                for sf in T._songfx:
                    sf.choose(0, [False] * 8)
            T._insfx_save()
            machines = stress.Stress._machines(self)
            drum = next((d for d in ("lxr", "808", "606") if d in machines), machines[0] if machines else None)
            synth = next((d for d in ("braids", "plaits", "obxd") if d in machines), None)
            if k in (1, 2):
                if drum:
                    e.set_slot(0, drum)
                if synth:
                    e.set_slot(1, synth)
                e.open_slot(0)
            if k == 2:
                T.insfx(0, 0).choose(1)
                T._insfx_save()
                T.songfx(0).choose(1, [bool(x) for x in e.slots])
            if k == 3:
                pick = self.rng.sample(machines, min(8, len(machines)))
                for s, mid in enumerate(pick):
                    e.set_slot(s, mid)
                e.open_slot(0)
            if k in (1, 2) and not e.playing:
                self.send(_cc(85, 127))
                self.send(_cc(85, 0))
        except Exception:                                # noqa: BLE001
            self.problem("SET-UP FAILED", SETUPS[k], traceback.format_exc().rstrip())
        self.back_out(now)

    def release(self):
        for _, b in self.pending:
            self.send(b)
        self.pending = []
        self.send(_cc(SHIFT, 0))

    def back_out(self, now):
        self.backing = self.here_text()
        self.last = None
        events = []
        for k in range(6):
            events += _press(BACK, k * 0.15)
        self.run("BACK x6", events, now)

    # ------------------------------------------------------------ the main loop calls this

    def tick(self, now):
        if self.finished:
            return False
        due = [p for p in self.pending if p[0] <= now]
        if due:
            self.pending = [p for p in self.pending if p[0] > now]
            for _, b in due:
                self.send(b)
        if now >= self.end:
            self.finish("finished")
            return False
        e = self.e
        if e.recording:                                  # (recording: stopped after 40 seconds or so)
            self.rec_since = self.rec_since or now
            if now - self.rec_since > 40 and not self.pending:
                self.rec_since = None
                self.run("PLAY (stop recording)", _press(85), now)
                return True
        else:
            self.rec_since = None
        if self.pending or self.waiting or self.look is None:
            if self.waiting and now - self.wait_from > 10:
                self.problem("SCREEN STOPPED DRAWING", self.here_text())
                self.waiting = False
            return True
        here, ops, found, texts = self.look
        self.screens_all.add(here)
        for kind, what in found:
            self.problem(kind, here, what)
        for t in texts:
            if re.search(r"\bERROR\b|FAIL", t) and t != "SCREEN ERROR":
                self.problem("MESSAGE", here, t)
        if self.backing is not None:                     # a Back-out just finished
            T, m = self.T, self.m
            if m.open or m.kits.open or T.fx_page or (T.inst_page and getattr(T.instp, "mode", None)) or T.sbrowse.active:
                self.problem("BACK DOESN'T GET OUT", "started on %s, still on %s" % (self.backing, here))
            self.backing = None
            self.since_back = 0
        elif self.last is not None:
            before, press = self.last
            self.graph.setdefault(before, {})[press] = here
        self.last = None
        self.look = (here, ops, [], [])                 # (looked at)
        self.next_press(now, here)
        return True

    def next_press(self, now, here):
        r = self.rng
        if self.since_back >= BACK_EVERY:
            self.back_out(now)
            return
        if self.random:
            name = r.choice(self.names)
        else:
            if now >= self.setup_end:
                self.say("  (out of time for this set-up: %d screens found)" % len(self.graph))
                self.next_setup(now)
                return
            name = self.route(here)
            if name is None:
                self.say("  every press tried on every screen it could get to: %d screens, %d presses so far" %
                         (len(self.tried), self.presses))
                for s in sorted(self.tried):
                    self.say("     " + s)
                self.next_setup(now)
                return
        if not self.safe(name):
            name = "BACK"
        self.tried.setdefault(here, set()).add(name)
        self.last = (here, name)
        self.since_back += 1
        self.run(name, self.acts[name], now)

    def route(self, here):
        """A press not yet tried here, or the first press on the way to the nearest screen that has one."""
        left = [n for n in self.names if n not in self.tried.get(here, ()) and self.safe(n)]
        if left:
            return self.rng.choice(left)
        seen, queue = {here}, [(here, None)]
        while queue:
            s, first = queue.pop(0)
            for press, nxt in sorted(self.graph.get(s, {}).items()):
                if nxt in seen:
                    continue
                f = first or press
                if any(n not in self.tried.get(nxt, ()) for n in self.names):
                    return f
                seen.add(nxt)
                queue.append((nxt, f))
        return None

    # ------------------------------------------------------------ the end

    def finish(self, why):
        if self.finished:
            return
        self.finished = True
        try:
            self.release()
        except Exception:                                # noqa: BLE001
            pass
        self.say("")
        self.say("RESULT (%s)" % why)
        self.say("  %d presses, %d different screens" % (self.presses, len(self.screens_all)))
        if self.problems:
            self.say("  %d PROBLEMS:" % len(self.problems))
            for key in self.problems:
                kind, where, last = key
                self.say("    %s  %s  %s%s" % (kind, where, last,
                                              ("  (x%d)" % self.seen[key]) if self.seen[key] > 1 else ""))
        else:
            self.say("  no problems")
        if self.slow:
            self.say("  SLOW:")
            for s in self.slow[:20]:
                self.say("    " + s)
        self.say("")
        self.say("SCREENS FOUND:")
        for s in sorted(self.screens_all):
            self.say("  " + s)
        if why == "finished":
            self.say("Console restarts as normal now.")
        if self.rep:
            try:
                self.rep.close()
            except OSError:
                pass
            self.rep = None
        _cleanup()
