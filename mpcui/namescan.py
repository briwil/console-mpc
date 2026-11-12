"""Reads every synth's own preset names, once, so the PRESETS lists are full from the first time a synth is loaded.

A synth only tells Console the name of the preset it is on, so this goes through them: every synth, every bank, every
preset (silently: no notes are played), and writes what it reads to console/preset-names-scan.json (and into the
names Console already remembers). Start it from your computer with tools/scan-names.sh. It runs in its own empty
project folder (console/scan-data), so your songs aren't touched, and Console restarts as normal when it's done.

    console/scan-names             the flag: Console sees it when it starts
    console/preset-names-scan.txt  how far it is, a line per synth
    console/preset-names-scan.json the names: {"synth|bank|number": "NAME"}
"""
import json
import os
import shutil
import sys
import time

HOME = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
FLAG = os.path.join(HOME, "scan-names")
DATA = os.path.join(HOME, "scan-data")
OUT = os.path.join(HOME, "preset-names-scan.json")
LOG = os.path.join(HOME, "preset-names-scan.txt")
CACHE = os.path.join(HOME, "data", "preset-names.json")      # what mpc_app.py's PRESETS page remembers
LOAD_WAIT = 3.0             # after a synth is put in the slot
BANK_WAIT = 1.0             # after a bank change
NAME_WAIT = 0.25            # after a preset, before its name is right (as movepresets.py)
STUCK = 2.5                 # a preset that never arrives: skipped
MOST = 5000                 # presets of one synth, at most
RESTART = 75                # the launcher starts Console again on this exit code

ACTIVE = False
S = {}


def prepare():
    """At the very start (before anything reads CONSOLE_DATA): True when a scan was asked for."""
    global ACTIVE
    if not os.path.exists(FLAG):
        return False
    try:
        os.remove(FLAG)
        shutil.rmtree(DATA, ignore_errors=True)
        os.makedirs(DATA, exist_ok=True)
        open(LOG, "w").close()
    except OSError:
        return False
    os.environ["CONSOLE_DATA"] = DATA
    ACTIVE = True
    S.update(phase="start", names={}, at=time.monotonic() + 4.0, machines=None, mi=-1, line="STARTING", count=0, started=time.monotonic())
    return True


def _log(text):
    try:
        with open(LOG, "a") as fh:
            fh.write(text + "\n")
    except OSError:
        pass


def _save():
    out = {"%s|%d|%d" % k: v for k, v in sorted(S["names"].items())}
    try:
        with open(OUT + ".tmp", "w") as fh:
            json.dump(out, fh, indent=0, sort_keys=True)
        os.replace(OUT + ".tmp", OUT)
    except OSError:
        pass
    try:                                                     # ... and into the names the PRESETS page already keeps
        try:
            with open(CACHE) as fh:
                old = json.load(fh)
        except (OSError, ValueError):
            old = {}
        old.update(out)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE + ".tmp", "w") as fh:
            json.dump(old, fh)
        os.replace(CACHE + ".tmp", CACHE)
    except OSError:
        pass


def _next_machine(T, now):
    e = T.engine
    if S.get("mid"):
        _log("%-16s %d names" % (S["mid"], S["got"]))
        _save()
    S["mi"] += 1
    if S["mi"] >= len(S["machines"]):
        S["phase"] = "done"
        S["at"] = now + 3.0
        S["line"] = "DONE: %d NAMES" % len(S["names"])
        _log("DONE: %d names, %d seconds" % (len(S["names"]), now - S["started"]))
        return
    mid = S["machines"][S["mi"]]
    S.update(mid=mid, got=0, banks=None, bi=0, n=0, phase="load", at=now + LOAD_WAIT, seen=0)
    S["line"] = mid.upper()
    for i in range(len(e.slots)):
        if e.slots[i]:
            e.set_slot(i, None)
    if not e.set_slot(0, mid):
        _log("%-16s couldn't be loaded" % mid)
        S["mid"] = None
        S["phase"] = "next"
        return
    if e.slot != 0:
        e.open_slot(0)


def _ask(d, now):
    """Asks for preset S["n"] of the bank that's up."""
    d.set_preset(S["n"])
    S["phase"], S["asked"], S["there"] = "preset", now, None


def tick(T):
    """Every frame while a scan runs (from the screen's draw wrapper: Console's own thread)."""
    now = time.monotonic()
    e = T.engine
    if e is None or not e.drums or now < S["at"]:
        return
    ph = S["phase"]
    if ph == "start":
        import drums
        S["machines"] = [mid for mid, _t in drums.available_machines() if e.is_synth(mid)]
        _log("%d synths" % len(S["machines"]))
        S["phase"] = "next"
        return
    if ph == "next":
        _next_machine(T, now)
        return
    if ph == "done":
        _save()
        sys.stdout.flush()
        raise SystemExit(RESTART)                    # Console starts again, as normal (your own project folder)
    d = e.drums
    if ph == "load":
        if not (hasattr(d, "has_presets") and d.has_presets()):
            _log("%-16s no presets of its own" % S["mid"])
            S["mid"] = None
            S["phase"] = "next"
            return
        pi = d.preset_info or {}
        if pi.get("menu"):                           # the names are a menu's options: all there at once
            opts = d.params[d.preset_param()]["options"]
            for n, o in enumerate(opts):
                S["names"][(S["mid"], 0, n)] = str(o).title()
            S["got"] = len(opts)
            S["phase"] = "next"
            return
        if not pi.get("name"):
            _log("%-16s its presets have no names" % S["mid"])
            S["mid"] = None
            S["phase"] = "next"
            return
        banks = [ix for _l, ix in d.banks()]
        S["banks"] = banks if len(banks) > 1 else [d.bank()]
        S["bi"] = -1
        S["phase"] = "bank"
        return
    if ph == "bank":
        S["bi"] += 1
        if S["bi"] >= len(S["banks"]) or S["seen"] >= MOST:
            S["phase"] = "next"
            return
        b = S["banks"][S["bi"]]
        if d.bank() != b:
            d.set_bank(b)
        S["phase"], S["at"] = "bank2", now + BANK_WAIT
        return
    if ph == "bank2":
        S["total"] = max(0, min(MOST, int(d.preset_count())))
        S["n"] = 0
        if S["total"] < 1:
            S["phase"] = "bank"
            return
        _ask(d, now)
        return
    if ph == "preset":
        b = S["banks"][S["bi"]]
        if S["there"] is None:
            if d.preset_now() == S["n"]:
                S["there"] = now
            elif now - S["asked"] < STUCK:
                return
        elif now - S["there"] < NAME_WAIT:
            return
        if S["there"] is not None:
            nm = d.preset_name()
            if nm:
                S["names"][(S["mid"], int(b), S["n"])] = nm
                S["got"] += 1
        S["seen"] += 1
        S["line"] = "%s  %d/%d%s" % (S["mid"].upper(), S["n"] + 1, S["total"],
                                    ("  BANK %d/%d" % (S["bi"] + 1, len(S["banks"]))) if len(S["banks"]) > 1 else "")
        S["n"] += 1
        if S["n"] >= S["total"]:
            _save()
            S["phase"] = "bank"
            return
        _ask(d, now)


def draw(nat):
    """The screen while it runs."""
    c = nat.canvas
    c.clear((0, 0, 0))
    c.text_px(8, 40, "READING PRESET NAMES", (255, 255, 255), 16, -1)
    c.text_px(8, 70, "LEAVE THE CONTROLS ALONE", nat.ACC, 8, 0)
    c.text_px(8, 84, "CONSOLE RESTARTS WHEN IT IS DONE", nat.ACC, 8, 0)
    n, k = len(S.get("machines") or []), max(0, S.get("mi", 0))
    if n:
        c.text_px(8, 124, "SYNTH %d OF %d" % (min(k + 1, n), n), (255, 255, 255), 8, 0)
        c.frame(8, 132, 304, 10, (255, 255, 255))
        c.rect(10, 134, int(300 * min(1.0, k / float(n))), 6, (255, 255, 255))
    c.text_px(8, 170, str(S.get("line", ""))[:38], (255, 255, 255), 8, 0)
    c.text_px(8, 190, "%d NAMES SO FAR" % len(S.get("names", {})), (255, 255, 255), 8, 0)
