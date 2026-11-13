"""The crash log: every run of the app writes to console/crashes/running.log (what it prints, the buttons
pressed, and - if the app crashes inside an effect or synth - the Python line it was on). When the app quits
normally the file is thrown away. If it's still there at the next start, the last run crashed (or froze and
was killed): it's kept as crashes/crash-<date>.log, so it's never overwritten by the next run.

    ls /data/UserData/console/crashes
    cat /data/UserData/console/crashes/crash-*.log | tail -120

Black box: watch(engine) also writes BOX lines (transport changes, a heartbeat while playing, and every thread's
Python line if the sound bridge or sequencer stalls). Since a power-off leaves running.log behind, it is kept as a
crash file at the next start, so a freeze you ended by switching off can still be read.

If the main loop stops for FREEZE seconds (a hang, not a crash) every thread's Python line is written too.
"""
import collections
import faulthandler
import os
import sys
import time

HOME = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
DIR = os.path.join(HOME, "crashes")
RUNNING = os.path.join(DIR, "running.log")
KEEP = 20                       # crash files kept (the oldest go)
MAX_BYTES = 1500000             # running.log is trimmed to its last part past this
FREEZE = 20                     # seconds the main loop can stop before its threads are written out

_fd = None
_writes = 0
_last_arm = 0.0
_crash = None                   # the crash file saved at start-up (the last run's), or None
recent = collections.deque(maxlen=12)    # the last few actions (the stress test shows them)


def _write(text):
    global _writes
    if _fd is None or not text:
        return
    try:
        os.write(_fd, text.encode("utf-8", "replace"))
    except OSError:
        return
    _writes += 1
    if _writes % 200 == 0:
        _trim()


def _trim():
    """Too big: keep its last third (the part that matters for a crash)."""
    try:
        if os.fstat(_fd).st_size <= MAX_BYTES:
            return
        with open(RUNNING, "rb") as fh:
            fh.seek(-MAX_BYTES // 3, os.SEEK_END)
            tail = fh.read()
        os.ftruncate(_fd, 0)
        os.write(_fd, b"(older lines trimmed)\n" + tail)
    except OSError:
        pass


class _Tee:
    """Prints still go to app.log, and to running.log too."""

    def __init__(self, real):
        self.real = real

    def write(self, s):
        try:
            self.real.write(s)
        except Exception:                                # noqa: BLE001
            pass
        _write(s)
        return len(s)

    def flush(self):
        try:
            self.real.flush()
        except Exception:                                # noqa: BLE001
            pass

    def __getattr__(self, name):
        return getattr(self.real, name)


def _commit():
    try:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        head = open(os.path.join(repo, ".git", "HEAD")).read().strip()
        if head.startswith("ref: "):
            return open(os.path.join(repo, ".git", head[5:])).read().strip()[:8]
        return head[:8]
    except OSError:
        return "?"


def start(note=""):
    """At start-up: keep the last run's log if it crashed, then start this run's. Returns the kept crash
    file's name, or None."""
    global _fd, _crash
    try:
        os.makedirs(DIR, exist_ok=True)
        if os.path.exists(RUNNING) and os.path.getsize(RUNNING) > 0:
            stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(os.path.getmtime(RUNNING)))
            name = "crash-%s.log" % stamp
            os.replace(RUNNING, os.path.join(DIR, name))
            _crash = name
            old = sorted(f for f in os.listdir(DIR) if f.startswith("crash-"))
            for f in old[:-KEEP]:
                os.remove(os.path.join(DIR, f))
        _fd = os.open(RUNNING, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND, 0o644)
    except OSError as ex:
        print("crash log: can't write %s (%s)" % (DIR, ex))
        _fd = None
        return None
    _write("Console started %s  (version %s)%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), _commit(),
                                                     ("  " + note) if note else ""))
    faulthandler.enable(file=_fd, all_threads=True)       # a native crash (an effect, a synth): the Python line
    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)
    return _crash


def last_crash():
    return _crash


def action(what):
    """A button, knob, pad... (the last ones before a crash say what led to it)."""
    recent.append(str(what))
    if _fd is not None:
        _write("%s %s\n" % (time.strftime("%H:%M:%S"), what))


def alive(now):
    """Called by the main loop: if it stops for FREEZE seconds, every thread's Python line gets written."""
    global _last_arm
    if _fd is None or now - _last_arm < 1.0:
        return
    _last_arm = now
    try:
        faulthandler.dump_traceback_later(FREEZE, repeat=True, file=_fd)
    except (ValueError, RuntimeError):
        pass


def watch(engine):
    """The black box: a thread that looks at the engine once a second and writes down what matters, so a stop
    like "it was playing, then it froze" can be read afterwards. Lines start with BOX:
      - play / record changes, and a heartbeat every 10 s while playing
      - STALL: the bridge (which feeds the sound core) stopped stepping: every thread's Python line is written
      - SEQ STUCK: the bridge runs but the sequencer's clock doesn't move while playing: threads written too
      - CORE STOPPED: the sound core's own clock isn't moving
      - SLOW: one bridge step took over 0.25 s"""
    import threading

    def run():
        was = None
        beat = 0
        stalled = stuck = False
        last_seq, seq_since = None, time.monotonic()
        last_core, core_since, core_dead = None, time.monotonic(), False
        while True:
            time.sleep(1.0)
            try:
                now = time.monotonic()
                br = getattr(engine, "bridge", None)
                if br is None or _fd is None:
                    continue
                state = (bool(engine.playing), bool(engine.recording), engine.slot)
                if state != was:
                    _write("%s BOX play=%s rec=%s slot=%s bpm=%.1f\n" % (
                        time.strftime("%H:%M:%S"), state[0], state[1], state[2], engine.bpm))
                    was = state
                    last_seq, seq_since = None, now
                step_max, br.step_max = br.step_max, 0.0
                if step_max > 0.25:
                    _write("%s BOX SLOW: a bridge step took %.2f s\n" % (time.strftime("%H:%M:%S"), step_max))
                silent = now - br.last_step
                if silent > 1.5 and not stalled:
                    stalled = True
                    _write("%s BOX STALL: the bridge hasn't stepped for %.1f s. Threads:\n" % (
                        time.strftime("%H:%M:%S"), silent))
                    faulthandler.dump_traceback(file=_fd, all_threads=True)
                elif silent <= 1.5 and stalled:
                    stalled = False
                    _write("%s BOX bridge stepping again\n" % time.strftime("%H:%M:%S"))
                if engine.playing and silent <= 1.5:
                    if engine.seq_clock != last_seq:
                        last_seq, seq_since = engine.seq_clock, now
                        stuck = False
                    elif now - seq_since > 1.5 and not stuck:
                        stuck = True
                        _write("%s BOX SEQ STUCK: playing but the sequencer clock stays at %s. Threads:\n" % (
                            time.strftime("%H:%M:%S"), last_seq))
                        faulthandler.dump_traceback(file=_fd, all_threads=True)
                core = getattr(br, "core", None)
                if core is not None:
                    c = core.now()
                    if c != last_core:
                        last_core, core_since = c, now
                        if core_dead:
                            core_dead = False
                            _write("%s BOX sound core running again\n" % time.strftime("%H:%M:%S"))
                    elif now - core_since > 1.5 and not core_dead:
                        core_dead = True
                        _write("%s BOX CORE STOPPED: the sound core's clock isn't moving. Threads:\n" %
                               time.strftime("%H:%M:%S"))
                        faulthandler.dump_traceback(file=_fd, all_threads=True)
                beat += 1
                if engine.playing and beat % 10 == 0:
                    _write("%s BOX ok steps=%d seq_clock=%s core=%s\n" % (
                        time.strftime("%H:%M:%S"), br.steps, engine.seq_clock, last_core))
            except Exception as ex:                      # noqa: BLE001  (the watcher must never stop)
                _write("BOX watcher: %r\n" % (ex,))

    threading.Thread(target=run, daemon=True, name="black box").start()


def done():
    """The app quit normally: this run's log isn't needed."""
    global _fd
    if _fd is None:
        return
    try:
        faulthandler.cancel_dump_traceback_later()
        faulthandler.enable(all_threads=True)             # back to app.log
    except Exception:                                    # noqa: BLE001
        pass
    for s in ("stdout", "stderr"):
        t = getattr(sys, s)
        if isinstance(t, _Tee):
            setattr(sys, s, t.real)
    try:
        os.close(_fd)
        os.remove(RUNNING)
    except OSError:
        pass
    _fd = None
