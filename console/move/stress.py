"""The stress test: Console runs by itself on the Move for a while, the way a very busy (and slightly mad)
person would use it, to find crashes, freezes and memory leaks.

Start it (Console running or not):

    ssh -i ~/.ssh/move_key ableton@move.local "echo 60 > /data/UserData/console/stress"

(60 = minutes; "60 random" skips the first two parts, "60 inserts" the first one; "songfx": only the song
inserts' load test, below.) If Console is running it restarts into the test; otherwise start Console as usual. It uses
its own projects (console/stress-data), so your songs and settings aren't touched. It:

  1. loads every instrument in turn and plays it (with the memory it took),
  2. loads every insert effect in turn (with a second one beside it) while a synth plays,
  3. then until the time's up: random buttons, pads, knobs and the wheel, plus every 20 seconds or so
     a random instrument into a random slot or a random insert effect, and now and then a new,
     saved or opened project.

Every 30 seconds it notes the app's memory. The report is console/stress-report.txt, written as it goes
(so a crash leaves it up to that point, and the crash itself is in console/crashes/):

    ssh -i ~/.ssh/move_key ableton@move.local "cat /data/UserData/console/stress-report.txt"

When it's finished Console restarts as normal with your own songs. Shift + Back stops it early.

The song inserts' load test ("songfx", about 15 minutes):

    ssh -i ~/.ssh/move_key ableton@move.local "echo songfx > /data/UserData/console/stress"

4 instruments, then 8, play busy patterns; each insert effect in turn is SONG INSERT 1 (so every instrument runs
a copy of it) while the sound core's DSP load is measured. The report ranks them and marks the ones that
overload (the sound would break up), so they can be kept off the SONG INSERT list.

The start-up check ("startup", 8 minutes), for Console being busier for its first minutes:

    ssh -i ~/.ssh/move_key ableton@move.local "echo startup > /data/UserData/console/stress"

4 instruments play (no effects). Every 30 seconds: DSP load, the app's CPU and which threads use it. At 1:30
every synth gets "all notes off" (stuck notes?); at 3:00 stop, OB-Xd reloaded while stopped, play; at 4:30
OB-Xd reloaded while playing; at 6:00 stop and play with no reload. Ends at 8:00.
"""
import os
import random
import shutil
import time
import traceback

HOME = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
FLAG = os.path.join(HOME, "stress")
RUNNING = os.path.join(HOME, "stress.running")
REPORT = os.path.join(HOME, "stress-report.txt")
DATA = os.path.join(HOME, "stress-data")
INSERTS_FILE = os.path.join(HOME, "insert-fx.json")      # (shared with your own data: put back at the end)
BACKUP = os.path.join(HOME, "insert-fx.json.stress-backup")
RANDOM_ONLY = False             # "60 random" in the file: straight to part 3
INSERTS_FIRST = False           # "60 inserts": straight to part 2 (no instruments tried first)
SONGFX = False                  # "songfx": only the song inserts' load test
STARTUP = False                 # "startup": only the start-up check
MENU = False                    # "menu": the menu test instead (uitest.py)
SONGFX_SET = ["lxr", "606", "braids", "obxd", "808", "plaits", "dexed", "wurl"]   # what plays (the first 4, then 8)

# the Move's controls the test presses (see app.py). Not the volume knob, and never Shift + Back (that quits).
PADS = range(68, 100)
STEPS = range(16, 32)
KNOBS = range(71, 79)
WHEEL, PUSH, PLUS, MINUS, SHIFT, BACK = 14, 3, 55, 54, 49, 51
LEFT_BUTTONS = (43, 42, 41, 40)
BUTTONS = {85: 3, 86: 1, 58: 2, 62: 3, 63: 3, 56: 2, 52: 1, 118: 1, 88: 2, 50: 1}   # cc: how often
HOLDS = (60, 119)                                                                # Copy, Delete


def prepare():
    """At the very start (before anything reads CONSOLE_DATA). Returns the test's minutes, or None for
    a normal start."""
    if os.path.exists(FLAG):
        global RANDOM_ONLY, INSERTS_FIRST
        try:
            global SONGFX, STARTUP, MENU
            words = open(FLAG).read().split()
            low = [w.lower() for w in words]
            MENU = "menu" in low
            if MENU:
                words = [w for w in words if w.lower() != "menu"] or ["60"]
                low = [w.lower() for w in words]
            SONGFX = "songfx" in low
            STARTUP = "startup" in low
            if STARTUP:
                words = [w for w in words if w.lower() != "startup"] or ["10"]      # (a limit: it ends itself at 8)
                low = [w.lower() for w in words]
            if SONGFX:
                words = [w for w in words if w.lower() != "songfx"] or ["25"]      # (a time limit only: it ends itself, in about 15)
                low = [w.lower() for w in words]
            RANDOM_ONLY = "random" in low[1:]
            INSERTS_FIRST = "inserts" in low[1:]
            minutes = float(words[0]) if words else 60
        except (OSError, ValueError):
            minutes = 60
        minutes = max(1.0, min(24 * 60.0, minutes))
        try:
            os.replace(FLAG, RUNNING)
            shutil.rmtree(DATA, ignore_errors=True)
            os.makedirs(DATA, exist_ok=True)
            if os.path.exists(INSERTS_FILE) and not os.path.exists(BACKUP):
                shutil.copy2(INSERTS_FILE, BACKUP)
        except OSError:
            return None
        os.environ["CONSOLE_DATA"] = DATA
        return minutes
    if os.path.exists(RUNNING):                       # the last test never finished: it crashed or froze
        _note("\nSTOPPED %s: Console crashed or froze during the test (it never finished). "
              "The crash is in console/crashes/ (the newest crash-*.log).\n" % time.strftime("%H:%M:%S"))
        _cleanup()
    return None


def _note(text):
    try:
        with open(REPORT, "a") as fh:
            fh.write(text)
    except OSError:
        pass


def _cleanup():
    try:
        os.remove(RUNNING)
    except OSError:
        pass
    try:
        if os.path.exists(BACKUP):
            os.replace(BACKUP, INSERTS_FILE)
    except OSError:
        pass


def _threads():
    """{thread id: (name, CPU ticks so far)} for every thread of this program: Python's own threads by their
    names, the rest (the sound server's, the instruments' workers) by the system's name for them."""
    import threading
    py = {getattr(t, "native_id", None): t.name for t in threading.enumerate()}
    out = {}
    try:
        tids = os.listdir("/proc/self/task")
    except OSError:
        return out
    for tid in tids:
        try:
            st = open("/proc/self/task/%s/stat" % tid).read()
            rest = st[st.rindex(")") + 2:].split()              # (after the name, which may hold spaces)
            out[int(tid)] = (py.get(int(tid)) or st[st.index("(") + 1:st.rindex(")")], int(rest[11]) + int(rest[12]))
        except (OSError, ValueError, IndexError):
            pass
    return out


def _status():
    out = {}
    try:
        for line in open("/proc/self/status"):
            k, _, v = line.partition(":")
            if k in ("VmRSS", "VmHWM", "Threads"):
                out[k] = int(v.split()[0])
    except OSError:
        pass
    try:
        out["fds"] = len(os.listdir("/proc/self/fd"))
    except OSError:
        out["fds"] = 0
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                out["avail"] = int(line.split()[1])
    except OSError:
        pass
    t = os.times()
    out["cpu"] = t.user + t.system
    return out


def _mb(kb):
    return kb / 1024.0


class Stress:
    def __init__(self, minutes, T, m, e, board):
        self.T, self.m, self.e, self.board = T, m, e, board
        self.start = time.monotonic()
        self.end = self.start + minutes * 60
        self.minutes = minutes
        seed = int(time.time())
        self.rng = random.Random(seed)
        self.pending = []                     # [(when, midi bytes)]: releases still to come
        self.shift = False
        self.events = 0
        self.actions = 0
        self.problems = []
        self.mem = []                         # [(seconds, rss kb)]
        self.loads = []                       # [(what, rss before, rss after)]
        self.finished = False
        self.phase = "startup" if STARTUP else "songfx" if SONGFX else "random" if RANDOM_ONLY else "inserts" if INSERTS_FIRST else "instruments"
        self.sfx = None                       # the song inserts' load test (see sweep_songfx)
        if RANDOM_ONLY:
            self.random_from = self.start
        self.next_event = self.start + 2
        self.next_mem = self.start
        self.next_peak = self.start
        self.next_cp = 0.0
        self.cp_at = None
        self.baselines = []                   # [(seconds, rss kb)]: an empty project's memory, now and then
        self.peak = 0
        self.next_action = 0.0
        self.next_home = 0.0
        self.next_project = 0.0
        self.saves = 0
        self.last_cpu = (self.start, _status().get("cpu", 0))
        self.inst_list = self._machines()
        self.fx_count = self._fx_count()
        self.inst_i = 0
        self.fx_i = 1
        self.step_at = 0.0
        self.sub = 0
        self.before = 0
        self.random_from = getattr(self, "random_from", None)
        try:
            import crashlog
            self.crashlog = crashlog
        except ImportError:
            self.crashlog = None
        try:
            self.rep = open(REPORT, "w", buffering=1)
        except OSError:
            self.rep = None
        self.say("CONSOLE STRESS TEST  started %s, %s%d minutes (seed %d)" %
                 (time.strftime("%Y-%m-%d %H:%M:%S"), "up to " if (SONGFX or STARTUP) else "", minutes, seed))
        self.say("%d instruments, %d insert effects to try" % (len(self.inst_list), self.fx_count - 1))
        self.say("")
        m.update_action = lambda: None         # (no software updates in the middle of the test)

    # ------------------------------------------------------------ helpers

    def say(self, text):
        line = "%s  %s" % (self.clock(), text) if text else ""
        if self.rep:
            try:
                self.rep.write(line + "\n")
            except OSError:
                pass
        if self.crashlog:
            self.crashlog.action("[stress] " + text)

    def clock(self):
        s = int(time.monotonic() - self.start)
        return "%3d:%02d" % (s // 60, s % 60)

    def left(self):
        return max(0, int(self.end - time.monotonic()))

    def _machines(self):
        try:
            import drums
            return [mid for mid, _ in drums.available_machines()]
        except Exception:                                    # noqa: BLE001
            return []

    def _fx_count(self):
        try:
            import catalog
            return 1 + len(catalog.FX)
        except Exception:                                    # noqa: BLE001
            return 1

    def problem(self, what):
        self.problems.append("%s  %s" % (self.clock(), what))
        self.say("PROBLEM: " + what)

    def guarded(self, label, fn):
        """A direct action (load an instrument...): a Python error is noted, and the test goes on."""
        self.actions += 1
        try:
            fn()
        except Exception:                                    # noqa: BLE001
            self.problem("%s failed:\n%s" % (label, traceback.format_exc().rstrip()))

    def send(self, *msg):
        b = bytes(msg)
        if b[0] & 0xF0 == 0xB0 and b[1] == SHIFT:
            self.shift = b[2] > 0
        if b[0] & 0xF0 == 0xB0 and b[1] == BACK and b[2] and self.shift:
            return                                           # Shift + Back would quit: never
        self.events += 1
        self.board(b)

    def later(self, delay, *msg):
        self.pending.append((time.monotonic() + delay, bytes(msg)))

    def press(self, cc, hold=0.08):
        self.send(0xB0, cc, 127)
        self.later(hold, 0xB0, cc, 0)

    def pad(self, n, vel=100, hold=0.15):
        self.send(0x90, n, vel)
        self.later(hold, 0x90, n, 0)

    def release_all(self):
        for _, b in self.pending:
            self.board(b)
        self.pending = []
        if self.shift:
            self.send(0xB0, SHIFT, 0)

    def beat(self, now):
        """About 8 times a second (a pad while an instrument or effect is tried)."""
        if now < self.next_event:
            return False
        self.next_event = now + 0.12
        return True

    def rss(self):
        return _status().get("VmRSS", 0)

    def slots_text(self):
        e = self.e
        try:
            ins = getattr(self.T, "_insfx", None) or {}
            fx = ["%d.%d:%s" % (k + 1, p + 1, v.name()) for (k, p), v in sorted(ins.items()) if v.index]
            return "slots %s  inserts %s" % ([s or "-" for s in e.slots], fx or "none")
        except Exception:                                    # noqa: BLE001
            return ""

    def memory(self, now):
        s = _status()
        cpu_t, cpu = self.last_cpu
        pct = 100.0 * (s.get("cpu", 0) - cpu) / max(0.001, now - cpu_t)
        self.last_cpu = (now, s.get("cpu", 0))
        self.mem.append((now - self.start, s.get("VmRSS", 0), self.phase))
        self.say("MEMORY %.1f MB (peak %.1f)  threads %d  files %d  Move free %.0f MB  cpu %.0f%%  %s" %
                 (_mb(s.get("VmRSS", 0)), _mb(s.get("VmHWM", 0)), s.get("Threads", 0), s.get("fds", 0),
                  _mb(s.get("avail", 0)), pct, self.slots_text()))
        if os.environ.get("CONSOLE_TRACEMALLOC"):          # (for finding where Python's memory went)
            import tracemalloc
            if not tracemalloc.is_tracing():
                tracemalloc.start(8)
            else:
                for st in tracemalloc.take_snapshot().statistics("traceback")[:4]:
                    self.say("   %.1f MB  %s" % (st.size / 1048576.0, " <- ".join(
                        "%s:%d" % (os.path.basename(f.filename), f.lineno) for f in list(st.traceback)[::-1][:6])))
        if s.get("avail", 10 ** 9) < 60 * 1024:
            self.problem("the Move is almost out of memory (%.0f MB free)" % _mb(s["avail"]))

    def disk_low(self):
        try:
            st = os.statvfs(HOME)
            return st.f_bavail * st.f_frsize < 400 * 1024 * 1024
        except OSError:
            return False

    # ------------------------------------------------------------ the main loop calls this

    def tick(self, now):
        """Returns False once the test is over (the app then restarts as normal)."""
        if self.finished:
            return False
        due = [p for p in self.pending if p[0] <= now]
        if due:
            self.pending = [p for p in self.pending if p[0] > now]
            for _, b in due:
                self.send(*b)
        if now >= self.next_mem:
            self.next_mem = now + 30
            self.memory(now)
        if now >= self.next_peak:                            # a sudden jump in memory: what was just done
            self.next_peak = now + 0.5
            st = _status()
            hwm = st.get("VmHWM", 0)
            if self.peak and hwm - self.peak > 40 * 1024:
                recent = [r for r in (self.crashlog.recent if self.crashlog else []) if not r.startswith("[stress] MEMORY")]
                self.say("MEMORY JUMP +%.0f MB (peak %.0f MB, now %.0f MB) just after: %s" % (
                    _mb(hwm - self.peak), _mb(hwm), _mb(st.get("VmRSS", 0)), " | ".join(recent[-6:])))
            self.peak = hwm
        if now >= self.end:
            self.finish("finished")
            return False
        if self.phase in ("songfx", "startup") and getattr(self, "want_play", False) and not self.e.playing \
                and now >= getattr(self, "replay_at", 0):
            # the tape got to its end (5 minutes) and stopped, and the patterns with it: the load numbers after
            # that were of instruments sitting idle. Back to the start and on.
            self.guarded("rewind", lambda: self.T.set_pos(0.0))
            self.press(85)
            self.replay_at = now + 2
            if now >= getattr(self, "replay_said", 0):           # (it can take a try or two: say it once)
                self.say("  (the tape got to its end: back to the start, playing again)")
                self.replay_said = now + 15
        try:
            if self.phase == "instruments":
                self.sweep_instruments(now)
            elif self.phase == "inserts":
                self.sweep_inserts(now)
            elif self.phase == "songfx":
                self.sweep_songfx(now)
            elif self.phase == "startup":
                self.startup(now)
            else:
                self.monkey(now)
        except Exception:                                    # noqa: BLE001
            self.problem("the test itself (%s):\n%s" % (self.phase, traceback.format_exc().rstrip()))
            self.phase = "random"
        return True

    # ------------------------------------------------------------ 1: every instrument

    def playing(self, on):
        self.want_play = on
        if on and not self.e.playing:                        # from the start: the tape is 5 minutes long, and
            self.guarded("rewind", lambda: self.T.set_pos(0.0))   # at its end playing stops (patterns too)
        if bool(self.e.playing) != on:
            self.press(85)

    def sweep_instruments(self, now):
        e = self.e
        if now < self.step_at:
            if self.sub == 1 and self.beat(now):             # playing it: a few pads
                self.pad(self.rng.choice(PADS), self.rng.randint(30, 127), self.rng.uniform(0.05, 0.4))
            return
        if self.sub == 1:                                     # done playing the last one
            self.playing(False)
            after = self.rss()
            what = self.inst_list[self.inst_i]
            problem = ""
            try:
                problem = e.drums.m.problem() if hasattr(e.drums.m, "problem") else ""
            except Exception:                                # noqa: BLE001
                pass
            self.loads.append((what, self.before, after))
            self.say("  %-16s +%.1f MB%s" % (what, _mb(after - self.before),
                                            ("   (it says: %s)" % problem) if problem else ""))
            self.inst_i += 1
            self.sub = 0
        if self.inst_i >= len(self.inst_list):
            self.guarded("empty slot 1", lambda: e.set_slot(0, None))
            self.say("")
            self.say("2. EVERY INSERT EFFECT (slot 1, with a synth playing)")
            self.phase, self.sub, self.step_at = "inserts", 0, now + 1
            return
        if self.inst_i == 0 and self.sub == 0 and not getattr(self, "_titled", False):
            self._titled = True
            self.say("1. EVERY INSTRUMENT (memory it added)")
        what = self.inst_list[self.inst_i]
        self.before = self.rss()
        other = e.slot_of(what)

        def load():
            if other not in (None, 0):
                e.set_slot(other, None)                      # (it can only be in one slot)
            if not e.set_slot(0, what):
                self.problem("%s wouldn't load" % what)
            e.open_slot(0)
        self.guarded("load " + what, load)
        self.playing(True)
        self.sub, self.step_at = 1, now + 4

    # ------------------------------------------------------------ 2: every insert effect

    def sweep_inserts(self, now):
        e, T = self.e, self.T
        if self.sub == 0:                                    # a synth to play through them
            synth = next((m for m in ("braids", "plaits", "obxd", "sampler") if m in self.inst_list), None)
            synth = synth or (self.inst_list[0] if self.inst_list else None)
            if synth:
                self.guarded("load " + synth, lambda: (e.set_slot(0, synth), e.open_slot(0)))
            self.playing(True)
            self.sub, self.step_at = 2, now + 1
            return
        if now < self.step_at:
            if self.beat(now):
                self.pad(self.rng.choice(PADS), self.rng.randint(40, 127), self.rng.uniform(0.05, 0.5))
            if self.rng.random() < 0.02:                    # and its knobs
                ins = T.insfx(0, 0)
                ins.knob(self.rng.randrange(8), self.rng.choice((-3, -1, 1, 3)))
            return
        if self.sub == 3:
            after = self.rss()
            ins = T.insfx(0, 0)
            title = ins.choices()[self.fx_i] if self.fx_i < len(ins.choices()) else str(self.fx_i)
            self.loads.append(("fx " + title, self.before, after))
            self.say("  %-16s +%.1f MB%s" % (title, _mb(after - self.before),
                                            ("   (%s)" % ins.error) if ins.error else ""))
            self.fx_i += 1
        if self.fx_i >= self.fx_count:
            self.guarded("inserts off", lambda: (T.insfx(0, 0).choose(0), T.insfx(0, 1).choose(0), T._insfx_save()))
            self.playing(False)
            self.say("")
            self.say("3. RANDOM USE until the time's up")
            self.phase = "random"
            self.random_from = now
            self.next_action = now + 2
            return
        self.before = self.rss()
        i = self.fx_i
        j = self.rng.randrange(self.fx_count)

        def load():
            T.insfx(0, 0).choose(i)
            T.insfx(0, 1).choose(j)                          # a second one beside it (sometimes none)
            T._insfx_save()
        self.guarded("insert %d" % i, load)
        self.sub, self.step_at = 3, now + 3

    # ------------------------------------------------------------ the song inserts' load test

    def _fill(self, k, mid):
        """Slot k: this instrument, with a busy pattern (so the effects have sound to work on)."""
        e = self.e
        e.set_slot(k, mid)
        e.open_slot(k)
        q = e.seq
        if hasattr(q, "shown_notes"):                        # a synth: a chord now and then, a line
            sh = q.shown_notes()
            for st in range(0, 16, 2):
                q.toggle(st, sh[(st * 3) % len(sh)], 2)
                if st % 8 == 0:
                    q.toggle(st, sh[(st * 3 + 2) % len(sh)], 4)
        else:                                                # a drum machine: kick, snare, hats
            for lane, every in ((0, 4), (1, 8), (2, 2), (3, 3)):
                for st in range(0, 16, every):
                    try:
                        q.toggle(lane, st)
                    except Exception:                        # noqa: BLE001
                        pass
        e.seq_changed()

    def _sample(self):
        core = getattr(self.e, "core", None)
        if core is None:
            return
        try:
            v = float(core.load())
        except Exception:                                    # noqa: BLE001
            return
        if v >= 0:
            self.sfx["loads"].append(v)

    def sweep_songfx(self, now):
        """4 instruments, then 8: no song insert (the baseline), then each insert effect as SONG INSERT 1 in turn,
        a few seconds each, measuring the sound core's DSP load (and its cycles: a missed one is a dropout)."""
        e, T = self.e, self.T
        import catalog
        x = self.sfx
        if x is None:
            want = [m for m in SONGFX_SET if m in self.inst_list] or self.inst_list[:8]
            self.sfx = x = {"want": want, "counts": [c for c in (4, 8) if c <= len(want)] or [len(want)],
                            "ci": 0, "fx": -1, "stage": "load", "at": now, "loads": [], "rows": {}, "c0": None,
                            "t0": 0.0}
            self.say("SONG INSERTS: LOAD TEST  (%s)" % ", ".join(want))
            self.say("each effect as SONG INSERT 1: a copy on every instrument; DSP load avg / max, dropouts, memory")
            T.inst_sends = True
        if x["ci"] >= len(x["counts"]):
            if not x.get("ob_done") and self.obxd_check(now):
                return
            self.songfx_result()
            self.finish("finished")
            return
        n = x["counts"][x["ci"]]
        if x["stage"] == "load":                             # the instruments, playing
            self.playing(False)
            for k in range(8):
                self.guarded("slot %d" % (k + 1), lambda k=k: (self._fill(k, x["want"][k]) if k < n else e.set_slot(k, None)))
            self.guarded("song insert off", lambda: (T.songfx(0).choose(0), T.songfx_sync()))
            self.guarded("open slot 1", lambda: e.open_slot(0))   # the random pads: always slot 1, the drum machine
            self.playing(True)                                       # (they went to the last one loaded: OB-Xd with
            self.say("")                                             # 4, Wurl with 8, and the halves didn't compare)
            self.say("%d INSTRUMENTS  %s" % (n, [s or "-" for s in e.slots]))
            # warm up first: right after a start or an update the app is busy (loading, first-run work) and the
            # first numbers came out higher with 4 instruments than with 8. Wait at least 20 s and until the
            # app's own CPU has calmed down (90 s at most).
            x["stage"], x["at"], x["fx"] = "warmup", now + 20, 0
            x["until"], x["wcpu"], x["wt"] = now + 90, _status().get("cpu", 0), now
            return
        if self.beat(now) and self.rng.random() < 0.5:       # someone playing the pads too
            self.pad(self.rng.choice(PADS), self.rng.randint(60, 127), self.rng.uniform(0.05, 0.3))
        if x["stage"] == "warmup":
            if now - x["wt"] < 5:
                return
            cpu = 100.0 * (_status().get("cpu", 0) - x["wcpu"]) / max(0.001, now - x["wt"])
            x["wcpu"], x["wt"] = _status().get("cpu", 0), now
            if now < x["at"] or (cpu > 110 and now < x["until"]):
                return
            self.say("  (warmed up: app cpu %d%%%s)" % (cpu, ", still busy: numbers may run high" if cpu > 110 else ""))
            x["stage"], x["at"] = "settle", now
            if cpu > 110:                                    # still busy with no effect on: find out who
                x["stage"], x["pr"] = "probe", {"step": "threads", "at": now + 5, "th": _threads(), "t": now, "k": 0}
                self.say("  BUSY CHECK: what is using the CPU, with no effect on")
            return
        if x["stage"] == "probe":
            self.probe(now, n)
            return
        if x["stage"] == "settle":
            if now < x["at"]:
                return
            x["loads"], x["stage"], x["at"] = [], "measure", now + 6
            core = getattr(e, "core", None)
            x["c0"], x["t0"], x["rss0"] = (core.cycles() if core else None), now, self.rss()
            x["cpu0"] = _status().get("cpu", 0)
            return
        if x["stage"] == "measure":
            self._sample()
            if now < x["at"]:
                return
            core = getattr(e, "core", None)
            missed = 0
            if core is not None and x["c0"] is not None:
                expect = (now - x["t0"]) * core.rate / max(1, core.block)
                missed = max(0, int(round(expect - (core.cycles() - x["c0"]))))
            ld = x["loads"]
            cpu = 100.0 * (_status().get("cpu", 0) - x["cpu0"]) / max(0.001, now - x["t0"])   # the app's own CPU
            avg = sum(ld) / len(ld) if ld else -1
            peak = max(ld) if ld else -1
            if not ld:                                       # (no DSP load from the sound server: judge by CPU)
                avg = peak = min(100.0, cpu)                 # (roughly: the sound runs on one core)
            name = "(no song insert)" if x["fx"] == 0 else catalog.FX[x["fx"] - 1]["title"].upper()
            if x["fx"] == 0:
                x["base_missed"] = missed                    # (what the cycle count misses anyway: not the effects')
            missed = max(0, missed - x.get("base_missed", 0))
            err = T.songfx(0).error if x["fx"] else ""
            verdict = ("FAILED TO START" if err else "OVERLOAD" if (peak >= 90 or missed > 2) else
                       "HEAVY" if peak >= 70 else "ok")
            row = x["rows"].setdefault(name, {})
            row[n] = (avg, peak, missed, verdict, _mb(self.rss() - x["rss0"]))
            self.say("  %-20s avg %5.1f%%  max %5.1f%%  cpu %5.0f%%  dropouts %3d  mem %+5.1f MB  %s" % (
                name, avg, peak, cpu, missed, row[n][4], verdict + (("  (%s)" % err[:40]) if err else "")))
            x["fx"] += 1
            if x["fx"] > len(catalog.FX):
                x["ci"], x["stage"] = x["ci"] + 1, "load"
                self.guarded("song insert off", lambda: (T.songfx(0).choose(0), T.songfx_sync()))
                return
            i = x["fx"]
            self.guarded("song insert %s" % catalog.FX[i - 1]["id"],
                         lambda: (T.songfx(0).choose(i), T.songfx_sync()))
            x["stage"], x["at"] = "settle", now + 2

    def obxd_check(self, now):
        """OB-Xd on its own in slot 1: its pattern only, then played hard (4-note chords about 4 times a second,
        long-ish notes), at a few voice counts. Returns True while it is still running."""
        e, x = self.e, self.sfx
        ob = x.get("ob")
        if ob is None:
            if "obxd" not in self.inst_list:
                x["ob_done"] = True
                return False
            self.playing(False)
            self.guarded("song insert off", lambda: (self.T.songfx(0).choose(0), self.T.songfx_sync()))
            for k in range(8):
                self.guarded("slot %d" % (k + 1), lambda k=k: (self._fill(k, "obxd") if k == 0 else e.set_slot(k, None)))
            self.guarded("open slot 1", lambda: e.open_slot(0))
            self.playing(True)
            d = self.machine("obxd") or e.drums
            idx = next((i for i, q in enumerate(getattr(d, "params", []))
                        if "voice" in ("%s %s" % (q.get("key", ""), q.get("label", ""))).lower()
                        and "var" not in ("%s %s" % (q.get("key", ""), q.get("label", ""))).lower()), None)
            settings = [None]                                # None: as it loads
            if idx is not None:
                start = d.get_param(idx)
                texts = {d.value_text(idx, v): v for v in range(d.params[idx]["steps"] + 1)}
                settings = [start] + [texts[t] for t in ("16", "8", "4") if t in texts and texts[t] != start]
            x["ob"] = ob = {"idx": idx, "settings": settings, "i": 0, "phase": "set", "at": now, "rows": []}
            self.say("")
            self.say("OB-XD CHECK: on its own, its pattern, then played hard (4-note chords, 4 a second)%s" % (
                "" if idx is not None else "  (no voice count setting found)"))
            return True
        if ob["i"] >= len(ob["settings"]):
            if ob["idx"] is not None:
                self.guarded("voices back", lambda: (self.machine("obxd") or e.drums).set_param(ob["idx"], ob["settings"][0]))
            self.release_all()
            self.say("  OB-XD: %s" % "   ".join("%s voices: pattern max %.0f%%, played hard max %.0f%% (dropouts %d)"
                                                 % r for r in ob["rows"]))
            x["ob_done"] = True
            return False
        v = ob["settings"][ob["i"]]
        if ob["phase"] == "set":
            if ob["idx"] is not None:
                self.guarded("voices", lambda: (self.machine("obxd") or e.drums).set_param(ob["idx"], v))
            ob["phase"], ob["at"] = "wait", now + 3
            return True
        if ob["phase"] == "hard" and self.beat(now) and self.rng.random() < 0.5:
            for _ in range(4):
                self.pad(self.rng.choice(PADS), self.rng.randint(80, 127), self.rng.uniform(0.4, 1.0))
        if ob["phase"] in ("pattern", "hard"):
            self._sample()
        if now < ob["at"]:
            return True
        core = getattr(e, "core", None)
        if ob["phase"] in ("pattern", "hard"):
            ld, missed = x["loads"], 0
            if core is not None and ob.get("c0") is not None:
                expect = (now - ob["t0"]) * core.rate / max(1, core.block)
                missed = max(0, int(round(expect - (core.cycles() - ob["c0"]))) - x.get("base_missed", 0))
            ob[ob["phase"]] = (max(ld) if ld else -1, missed)
        if ob["phase"] == "hard":
            text = (self.machine("obxd") or e.drums).value_text(ob["idx"], v) if ob["idx"] is not None else "?"
            ob["rows"].append((text, ob["pattern"][0], ob["hard"][0], ob["hard"][1]))
            self.say("  %-4s voices   pattern: max %5.1f%%   played hard: max %5.1f%%  dropouts %d" % (
                text, ob["pattern"][0], ob["hard"][0], ob["hard"][1]))
            self.release_all()
            ob["i"], ob["phase"], ob["at"] = ob["i"] + 1, "set", now + 2
            return True
        ob["phase"] = "pattern" if ob["phase"] == "wait" else "hard"
        x["loads"], ob["c0"], ob["t0"], ob["at"] = [], (core.cycles() if core else None), now, now + 8
        return True

    def machine(self, mid):
        """The running instrument mid (whichever slot is picked)."""
        d = getattr(self.e, "drums", None)
        return d.get(mid) if d is not None and hasattr(d, "get") else None

    def settings_of(self, k):
        """[(name, value as shown)] of every setting of the instrument in slot k."""
        d = self.machine(self.e.slots[k])
        if d is None:
            return []
        return [(str(q.get("key") or q.get("label")), str(d.value_text(i))) for i, q in enumerate(getattr(d, "params", []))]

    def startup(self, now):
        """Console's first minutes: 4 instruments playing, no effects. Every 30 s: DSP load, app CPU, threads.
        Then: all notes off (1:30), OB-Xd reloaded while stopped (3:00) and while playing (4:30), stop + play
        with no reload (6:00): which makes it heavy, loading while stopped or pressing Play?"""
        e = self.e
        x = getattr(self, "su", None)
        core = getattr(e, "core", None)
        if x is None:
            want = [m for m in ("lxr", "606", "braids", "obxd") if m in self.inst_list]
            self.playing(False)
            for k in range(8):
                self.guarded("slot %d" % (k + 1), lambda k=k: (self._fill(k, want[k]) if k < len(want) else e.set_slot(k, None)))
            self.guarded("open slot 1", lambda: e.open_slot(0))
            self.playing(True)
            ob = want.index("obxd") if "obxd" in want else None
            first = self.settings_of(ob) if ob is not None else []
            self.su = x = {"t0": now, "next": now + 30, "th": _threads(), "cpu0": _status().get("cpu", 0), "t": now,
                           "loads": [], "ob": ob, "first": first}
            self.say("START-UP CHECK  %s  (no effects; pads on slot 1)" % [s or "-" for s in e.slots])
            if ob is not None:
                vo = [(k, v) for k, v in first if "voice" in k.lower() or "unison" in k.lower() or "poly" in k.lower()]
                self.say("  OB-XD at first load: %d settings; %s" % (len(first), ", ".join("%s %s" % kv for kv in vo) or "-"))
            return
        if core is not None:
            try:
                v = float(core.load())
                if v >= 0:
                    x["loads"].append(v)
            except Exception:                                # noqa: BLE001
                pass
        if self.beat(now) and self.rng.random() < 0.5:
            self.pad(self.rng.choice(PADS), self.rng.randint(60, 127), self.rng.uniform(0.05, 0.3))
        k = x["ob"]
        steps = [(90, "alloff"), (180, "stop"), (183, "reload"), (186, "play"), (270, "reload"), (360, "stop"),
                 (363, "play")] if k is not None else []
        done = x.setdefault("done", 0)
        if done < len(steps) and now - x["t0"] >= steps[done][0]:
            what = steps[done][1]
            x["done"] = done + 1
            if what == "alloff":                             # every synth: let go of every note
                n = 0
                for mid in e.slots:
                    m = self.machine(mid) if mid else None
                    if m is not None and hasattr(m, "all_off"):
                        self.guarded("all off %s" % mid, m.all_off)
                        n += 1
                self.say("  * ALL NOTES OFF on %d synths, still playing: if the load drops, notes were stuck on" % n)
            elif what == "stop":
                self.playing(False)
                self.say("  * stopped")
            elif what == "play":
                self.playing(True)
                self.say("  * playing again (from the start)%s" % ("" if x.get("reloaded_stopped") else
                                                                  ": no reload; does pressing Play make it heavy?"))
            elif what == "reload":
                stopped = not self.e.playing
                self.guarded("obxd out", lambda: e.set_slot(k, None))
                self.guarded("obxd back", lambda: self._fill(k, "obxd"))
                self.guarded("open slot 1", lambda: e.open_slot(0))
                x["reloaded_stopped"] = stopped
                second = self.settings_of(k)
                a, b = dict(x["first"]), dict(second)
                diff = [(n, a.get(n), b.get(n)) for n in list(a) + [n for n in b if n not in a] if a.get(n) != b.get(n)]
                self.say("  * OB-XD reloaded while %s (%s)" % (
                    "STOPPED" if stopped else "PLAYING",
                    ("%d settings differ: " % len(diff)) + "; ".join("%s %s -> %s" % d for d in diff[:20])
                    if diff else "same settings"))
            if what in ("alloff", "play") or (what == "reload" and self.e.playing):
                x["th"], x["cpu0"], x["t"], x["loads"], x["next"] = _threads(), _status().get("cpu", 0), now, [], now + 30
            return
        if now < x["next"]:
            return
        th, dt = _threads(), max(0.001, now - x["t"])
        tick = float(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100.0
        use = sorted(((100.0 * (v[1] - x["th"][k][1]) / tick / dt, v[0]) for k, v in th.items() if k in x["th"]), reverse=True)
        cpu = 100.0 * (_status().get("cpu", 0) - x["cpu0"]) / dt
        ld = x["loads"]
        self.say("  %4.1f min  dsp avg %5.1f%%  max %5.1f%%  app cpu %4.0f%%   %s" % (
            (now - x["t0"]) / 60.0, sum(ld) / len(ld) if ld else -1, max(ld) if ld else -1, cpu,
            "  ".join("%s %d%%" % (n, c) for c, n in use[:6] if c >= 1)))
        x.update(th=th, cpu0=_status().get("cpu", 0), t=now, loads=[], next=now + 30)
        if now - x["t0"] >= 480:
            self.finish("finished")

    def probe(self, now, n):
        """Console was busy with no effect on: which threads use the CPU, then each instrument taken out in turn
        (and put back) to see whose absence brings the load down."""
        x, pr, e = self.sfx, self.sfx["pr"], self.e
        if now < pr["at"]:
            if pr["step"] == "measure":
                self._sample()
            return
        if pr["step"] == "threads":
            th, dt = _threads(), max(0.001, now - pr["t"])
            tick = float(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100.0
            use = sorted(((100.0 * (v[1] - pr["th"][k][1]) / tick / dt, v[0], k) for k, v in th.items()
                          if k in pr["th"]), reverse=True)
            self.say("    threads (cpu over %.0f s): %s" % (dt, "   ".join("%s %d%%" % (name, c) for c, name, _k in use[:8]
                                                                         if c >= 1) or "none busy"))
            pr["step"] = "out"
        elif pr["step"] == "out":                            # take instrument k out for a few seconds
            if pr["k"] >= n:
                self.guarded("open slot 1", lambda: e.open_slot(0))
                x["stage"], x["at"] = "settle", now + 3
                self.say("    (all back: the measurements go on)")
                return
            pr["mid"] = e.slots[pr["k"]]
            self.guarded("probe out %d" % (pr["k"] + 1), lambda: e.set_slot(pr["k"], None))
            pr["step"], pr["at"] = "start", now + 2
        elif pr["step"] == "start":
            x["loads"], pr["cpu0"], pr["t"] = [], _status().get("cpu", 0), now
            pr["step"], pr["at"] = "measure", now + 4
        elif pr["step"] == "measure":
            ld = x["loads"]
            cpu = 100.0 * (_status().get("cpu", 0) - pr["cpu0"]) / max(0.001, now - pr["t"])
            self.say("    without slot %d (%s): dsp avg %5.1f%%  max %5.1f%%  app cpu %4.0f%%" % (
                pr["k"] + 1, pr["mid"], sum(ld) / len(ld) if ld else -1, max(ld) if ld else -1, cpu))
            k, mid = pr["k"], pr["mid"]
            self.guarded("probe back %d" % (k + 1), lambda: self._fill(k, mid))
            pr["k"] += 1
            pr["step"], pr["at"] = "out", now + 2

    def songfx_result(self):
        x = self.sfx or {}
        rows = x.get("rows", {})
        counts = x.get("counts", [])
        self.say("")
        self.say("SONG INSERTS: RESULT (the heaviest first, by their worst load)")
        worst = sorted(rows.items(), key=lambda kv: -max(v[1] for v in kv[1].values()))
        for name, r in worst:
            self.say("  %-20s %s" % (name, "   ".join("%d inst: max %5.1f%% %s" % (c, r[c][1], r[c][3])
                                                         for c in counts if c in r)))
        rows = {k: v for k, v in rows.items() if not k.startswith("(")}
        bad = [name for name, r in rows.items() if any(v[3] in ("OVERLOAD", "FAILED TO START") for v in r.values())]
        heavy = [name for name, r in rows.items() if name not in bad and any(v[3] == "HEAVY" for v in r.values())]
        base = x.get("rows", {}).get("(no song insert)", {})
        if len(counts) > 1 and all(c in base for c in counts) and base[counts[0]][1] > base[counts[-1]][1] + 10:
            self.say("")
            self.say("  NOTE: with no effect, %d instruments loaded the Move more than %d did (max %.0f%% vs %.0f%%):"
                     % (counts[0], counts[-1], base[counts[0]][1], base[counts[-1]][1]))
            self.say("  something else was busy during the first part. Trust the %d-instrument numbers, or run it again."
                     % counts[-1])
        import insertfx
        import catalog
        off = {f["title"].upper() for f in catalog.FX if f["id"] in insertfx.SONG_SKIP}
        self.say("")
        self.say("  ALREADY OFF THE SONG INSERT LIST: %s" % (", ".join(sorted(off)) or "none"))
        bad = [b for b in bad if b not in off]
        heavy = [h for h in heavy if h not in off]
        self.say("  TO KEEP OFF THE SONG INSERT LIST (overload or don't start): %s" % (", ".join(bad) or "none"))
        self.say("  HEAVY (fine with fewer instruments): %s" % (", ".join(heavy) or "none"))

    # ------------------------------------------------------------ 3: random use

    def checkpoint(self, now):
        """Every 8 minutes: an empty project (no instruments, no effects), memory measured after a few seconds.
        Those should stay about the same; if they keep climbing, something isn't giving memory back."""
        e, T = self.e, self.T
        if self.cp_at is None:
            self.release_all()
            self.playing(False)

            def empty():
                for k in range(8):
                    for pos in (0, 1):
                        ins = (getattr(T, "_insfx", None) or {}).get((k, pos))
                        if ins is not None and ins.index:
                            ins.choose(0)
                    e.set_slot(k, None)
                T._insfx_save()
            self.guarded("empty project", empty)
            self.cp_at = now + 6
            return
        if now < self.cp_at:
            return
        kb = self.rss()
        self.baselines.append((now - self.start, kb))
        self.say("CHECK: empty project uses %.1f MB" % _mb(kb))
        self.cp_at = None
        self.next_cp = now + 8 * 60
        for _ in range(3):                                   # and some instruments again
            if self.inst_list:
                k, what = self.rng.randrange(8), self.rng.choice(self.inst_list)
                self.guarded("slot %d %s" % (k + 1, what),
                             lambda k=k, what=what: e.slot_of(what) is None and e.set_slot(k, what))

    def monkey(self, now):
        r = self.rng
        if self.cp_at is not None or now >= self.next_cp:
            self.checkpoint(now)
            return
        if now >= self.next_home:                            # now and then: back out of wherever it got to
            self.next_home = now + r.uniform(40, 90)
            self.release_all()
            for k in range(3):
                self.later(0.05 + k * 0.1, 0xB0, BACK, 127)
                self.later(0.08 + k * 0.1, 0xB0, BACK, 0)
            if self.disk_low():
                self.playing(False)
                self.say("disk nearly full: stopped")
            return
        if now >= self.next_action:
            self.next_action = now + r.uniform(12, 30)
            self.direct(now)
            return
        if now < self.next_event:
            return
        self.next_event = now + r.expovariate(10)            # about 10 a second
        x = r.random()
        if x < 0.30:
            self.pad(r.choice(PADS), r.randint(1, 127), r.uniform(0.03, 1.5))
        elif x < 0.45:
            n = r.choice(STEPS)
            self.send(0x90, n, 127)
            self.later(r.choice((0.05, 0.1, 0.6, 1.5)), 0x90, n, 0)
        elif x < 0.65:
            k = r.choice(KNOBS)
            d = r.choice((1, 1, 1, 2, 5, -1, -1, -1, -2, -5))
            for t in range(r.randint(1, 6)):
                self.later(t * 0.03, 0xB0, k, d if d > 0 else 128 + d)
        elif x < 0.73:
            d = r.choice((1, -1))
            self.send(0xB0, WHEEL, d if d > 0 else 127)
        elif x < 0.77:
            self.press(PUSH)
        elif x < 0.80:
            self.press(r.choice((PLUS, MINUS)))
        elif x < 0.85:
            self.press(r.choice(LEFT_BUTTONS))
        elif x < 0.92:
            names = list(BUTTONS)
            cc = r.choices(names, [BUTTONS[c] for c in names])[0]
            if cc == 86 and self.disk_low():
                return
            self.press(cc)
        elif x < 0.95:
            cc = r.choice(HOLDS)
            self.send(0xB0, cc, 127)
            self.later(r.uniform(0.1, 2.0), 0xB0, cc, 0)
        elif x < 0.98:
            if not self.shift:
                self.send(0xB0, SHIFT, 127)
                self.later(r.uniform(0.2, 2.5), 0xB0, SHIFT, 0)
        else:
            self.press(BACK)

    def direct(self, now):
        """What random presses rarely get to: instruments, insert effects, projects."""
        e, T, r = self.e, self.T, self.rng
        x = r.random()
        if now >= self.next_project and x < 0.25:
            self.next_project = now + r.uniform(180, 420)
            y = r.random()
            if y < 0.4:
                self.saves += 1
                name = "STRESS %d" % self.saves
                self.say("save project as %s" % name)
                self.guarded("save", lambda: e.save_as(name) if e.song is None else e.save(wait=True))
            elif y < 0.7:
                songs = e.song_names()
                if songs:
                    name = r.choice(songs)
                    self.say("open project %s" % name)
                    self.guarded("open " + name, lambda: T.open_song(name))
            else:
                self.say("new project")
                self.guarded("new", lambda: T.new_song(None))
            return
        if x < 0.6 and self.inst_list:
            k = r.randrange(8)
            what = None if r.random() < 0.15 else r.choice(self.inst_list)
            other = e.slot_of(what) if what else None
            self.say("slot %d: %s" % (k + 1, what or "empty"))

            def load():
                if other not in (None, k):
                    e.set_slot(other, None)
                e.set_slot(k, what)
                if what and r.random() < 0.5:
                    e.open_slot(k)
            self.guarded("slot %d %s" % (k + 1, what), load)
        else:
            k, pos = r.randrange(8), r.randrange(2)
            i = 0 if r.random() < 0.2 else r.randrange(1, max(2, self.fx_count))
            self.say("insert %d of slot %d: %d" % (pos + 1, k + 1, i))

            def load():
                ins = T.insfx(k, pos)
                ins.choose(i)
                T._insfx_save()
                if ins.error:
                    self.say("  (%s: %s)" % (ins.name(), ins.error))
            self.guarded("insert", load)

    # ------------------------------------------------------------ the end

    def finish(self, why):
        if self.finished:
            return
        self.finished = True
        try:
            self.release_all()
        except Exception:                                    # noqa: BLE001
            pass
        self.memory(time.monotonic())
        self.say("")
        self.say("RESULT (%s)" % why)
        self.say("  %d presses and turns, %d instrument / effect / project changes" % (self.events, self.actions))
        if len(self.baselines) >= 2:
            first, last = self.baselines[0][1], self.baselines[-1][1]
            self.say("  empty project's memory, every 8 minutes: " +
                     ", ".join("%.0f" % _mb(kb) for _, kb in self.baselines) + " MB")
            prev = self.baselines[-2][1] if len(self.baselines) > 2 else last
            if _mb(last - first) > 30 and _mb(prev - first) > 15:
                self.say("  MEMORY KEEPS GROWING: a likely leak (send this report)")
                if RANDOM_ONLY:
                    self.say("  (an instrument stays in memory once it's been used, so some growth is expected "
                             "here: a full test, without \"random\", tries them all first)")
            else:
                self.say("  memory: no sign of a leak")
        else:
            self.say("  memory: too short a test to tell about leaks (run it for 30 minutes or more)")
        big = sorted(self.loads, key=lambda x: x[1] - x[2])[:5]
        if big:
            self.say("  most memory: " + ", ".join("%s +%.0f MB" % (w, _mb(b - a)) for w, a, b in big))
        if self.problems:
            self.say("  %d PROBLEMS (above, marked PROBLEM)" % len(self.problems))
        else:
            self.say("  no problems")
        if why == "finished":
            self.say("Console restarts as normal now (your own songs).")
        if self.rep:
            try:
                self.rep.close()
            except OSError:
                pass
            self.rep = None
        _cleanup()
