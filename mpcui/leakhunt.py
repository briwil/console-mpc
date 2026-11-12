"""Which instrument or insert effect keeps memory: each one is loaded and taken out again 4 times, and what Console
uses after the 4th time is compared with after the 1st. Something that gives its memory back shows about 0; a leak
shows the same amount again every time. Started from your computer with tools/leak-hunt.sh (about 25 minutes).

Three numbers per line, each "MB more per load":
    total     what the whole of Console uses (as the stress test's MEMORY)
    in use    memory asked for and not given back (the leak itself); total without in use = memory given back but
              still held in pieces
    python    Console's own Python code (thousands of objects: 0 unless Console's own code keeps something)

It runs in its own empty project folder (console/leak-data); Console restarts as normal when it's done.
    console/leakhunt            the flag: Console sees it when it starts
    console/leak-report.txt     the report (written as it goes)"""
import ctypes
import gc
import os
import shutil
import sys
import time

HOME = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
FLAG = os.path.join(HOME, "leakhunt")
DATA = os.path.join(HOME, "leak-data")
REPORT = os.path.join(HOME, "leak-report.txt")
CYCLES = 4
LOAD_WAIT, OUT_WAIT = 3.0, 1.5
IDLE = 60.0
RESTART = 75

ACTIVE = False
S = {}


def malloc_totals():
    """(in use, held free) in bytes over every thread's share of the C library's memory (malloc_info: mallinfo only
    knows the main thread's, and the synths and effects run on the sound thread). None, None if it can't say."""
    import re
    path = "/tmp/console-malloc-info.xml"
    try:
        libc = ctypes.CDLL(None)
        libc.fopen.restype = ctypes.c_void_p
        libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        libc.malloc_info.argtypes = [ctypes.c_int, ctypes.c_void_p]
        libc.fclose.argtypes = [ctypes.c_void_p]
        fp = libc.fopen(path.encode(), b"w")
        if not fp:
            return None, None
        libc.malloc_info(0, fp)
        libc.fclose(fp)
        text = open(path).read()
        tail = text[text.rindex("</heap>"):] if "</heap>" in text else text       # the totals come after the last heap
        free = sum(int(x) for x in re.findall(r'<total type="(?:fast|rest)" count="\d+" size="(\d+)"', tail))
        mm = sum(int(x) for x in re.findall(r'<total type="mmap" count="\d+" size="(\d+)"', tail))
        cur = re.search(r'<system type="current" size="(\d+)"', tail)
        if not cur:
            return None, None
        return int(cur.group(1)) - free + mm, free
    except Exception:
        return None, None


def _in_use():
    return malloc_totals()[0]


def _rss():
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def measure():
    gc.collect()
    return (_rss(), _in_use(), sys.getallocatedblocks())


def prepare():
    """At the very start (before anything reads CONSOLE_DATA): True when the hunt was asked for."""
    global ACTIVE
    if not os.path.exists(FLAG):
        return False
    try:
        os.remove(FLAG)
        shutil.rmtree(DATA, ignore_errors=True)
        os.makedirs(DATA, exist_ok=True)
        open(REPORT, "w").close()
    except OSError:
        return False
    os.environ["CONSOLE_DATA"] = DATA
    ACTIVE = True
    S.update(phase="start", at=time.monotonic() + 5.0, rows=[], line="STARTING", done=0, todo=1, started=time.monotonic())
    return True


def say(text):
    try:
        with open(REPORT, "a") as fh:
            fh.write(text + "\n")
    except OSError:
        pass


def _mb(a, b, per=1.0):
    if a is None or b is None:
        return "     ?"
    return "%+6.1f" % ((b - a) / per / 1048576.0)


def _row(name, first, last, per):
    """A line of the report: what one more load costs (after the last cycle against after the first)."""
    blocks = (last[2] - first[2]) / per
    S["rows"].append((name, (last[0] - first[0]) / per, None if last[1] is None else (last[1] - first[1]) / per, blocks))
    say("  %-18s total %s   in use %s   python %+7d objects" % (name[:18], _mb(first[0], last[0], per), _mb(first[1], last[1], per), blocks))


def _begin(kind, items, now):
    S.update(phase=kind, items=items, i=0, cycle=0, sub="in", marks=[], at=now)
    S["todo"] = S.get("todo", 0) + len(items)


def tick(T):
    """Every frame while it runs (from the screen's draw wrapper: Console's own thread)."""
    now = time.monotonic()
    e = T.engine
    if e is None or not e.drums or now < S["at"]:
        return
    ph = S["phase"]
    if ph == "start":
        import drums
        for i in range(len(e.slots)):
            if e.slots[i]:
                e.set_slot(i, None)
        S["machines"] = [mid for mid, _t in drums.available_machines()]
        try:
            S["fx"] = list(T.insfx(0, 0).choices())[1:]
        except Exception:
            S["fx"] = []
        S["todo"] = 0
        say("CONSOLE LEAK HUNT  started %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        say("each line: MB more per load (loaded and taken out %d times; after the last against after the first)" % CYCLES)
        say("")
        S.update(phase="idle", idle0=None, at=now + 2.0, line="DOING NOTHING FOR A MINUTE")
        return
    if ph == "idle":
        if S["idle0"] is None:
            S["idle0"] = measure()
            S["at"] = now + IDLE
            return
        say("0. DOING NOTHING for a minute (an empty project)")
        _row("nothing", S["idle0"], measure(), 1.0)
        say("")
        say("1. EVERY INSTRUMENT")
        _begin("inst", S["machines"], now)
        return
    if ph in ("inst", "fx"):
        if S["i"] >= len(S["items"]):
            if ph == "inst":
                say("")
                say("2. EVERY INSERT EFFECT (slot 1's first insert, a synth in the slot)")
                synth = next((m for m in ("braids", "plaits", "obxd") if m in S["machines"]), S["machines"][0] if S["machines"] else None)
                if synth:
                    e.set_slot(0, synth)
                    e.open_slot(0)
                _begin("fx", S["fx"], now + 4.0)
                S["at"] = now + 4.0
                return
            try:
                T.insfx(0, 0).choose(0)
                T._insfx_save()
                e.set_slot(0, None)
            except Exception:
                pass
            S["phase"] = "result"
            return
        name = S["items"][S["i"]]
        S["line"] = "%s  %d/%d" % (str(name).upper()[:20], S["cycle"] + 1, CYCLES)
        try:
            if S["sub"] == "in":
                if ph == "inst":
                    ok = e.set_slot(0, name)
                    if ok and e.slot != 0:
                        e.open_slot(0)
                    if not ok:
                        say("  %-18s couldn't be loaded" % name)
                        S["i"] += 1
                        S["done"] += 1
                        return
                else:
                    T.insfx(0, 0).choose(S["i"] + 1)
                    T._insfx_save()
                S["sub"], S["at"] = "out", now + LOAD_WAIT
                return
            if S["sub"] == "out":
                if ph == "inst":
                    e.set_slot(0, None)
                else:
                    T.insfx(0, 0).choose(0)
                    T._insfx_save()
                S["sub"], S["at"] = "mark", now + OUT_WAIT
                return
            S["marks"].append(measure())
            S["cycle"] += 1
            S["sub"] = "in"
            if S["cycle"] >= CYCLES:
                _row(str(name), S["marks"][0], S["marks"][-1], CYCLES - 1.0)
                S["i"] += 1
                S["done"] += 1
                S["cycle"], S["marks"] = 0, []
        except Exception as ex:                              # noqa: BLE001
            say("  %-18s failed: %s" % (str(name)[:18], ex))
            S["i"] += 1
            S["done"] += 1
            S["cycle"], S["marks"], S["sub"] = 0, [], "in"
        return
    if ph == "result":
        say("")
        say("RESULT (%d minutes)" % ((now - S["started"]) / 60))
        worst = sorted([r for r in S["rows"] if r[0] != "nothing"], key=lambda r: -r[1])[:10]
        say("  most memory kept per load:")
        for name, total, used, blocks in worst:
            if total < 0.2 * 1048576:
                break
            say("    %-18s %+.1f MB%s%s" % (name[:18], total / 1048576.0,
                                           "" if used is None else "  (in use %+.1f MB)" % (used / 1048576.0),
                                           "  python %+d objects" % blocks if abs(blocks) > 200 else ""))
        tot = sum(r[1] for r in S["rows"] if r[0] != "nothing") / 1048576.0
        say("  every instrument and effect loaded once more: %+.1f MB in all" % tot)
        say("  Console restarts as normal now (your own songs).")
        S["phase"], S["at"], S["line"] = "done", now + 3.0, "DONE"
        return
    if ph == "done":
        raise SystemExit(RESTART)


def draw(nat):
    c = nat.canvas
    c.clear((0, 0, 0))
    W = (255, 255, 255)
    c.text_px(8, 40, "LOOKING FOR THE LEAK", W, 16, -1)
    c.text_px(8, 70, "LEAVE THE CONTROLS ALONE", nat.ACC, 8, 0)
    c.text_px(8, 84, "CONSOLE RESTARTS WHEN IT IS DONE", nat.ACC, 8, 0)
    n = max(1, len(S.get("machines") or []) + len(S.get("fx") or []))
    c.frame(8, 132, 304, 10, W)
    c.rect(10, 134, int(300 * min(1.0, S.get("done", 0) / float(n))), 6, W)
    c.text_px(8, 124, "%d OF %d" % (S.get("done", 0), n), W, 8, 0)
    c.text_px(8, 170, str(S.get("line", ""))[:38], W, 8, 0)
    c.text_px(8, 190, "%d MB" % (_rss() // 1048576), W, 8, 0)
