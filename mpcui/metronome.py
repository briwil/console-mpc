"""The metronome: Shift + TAP TEMPO on the tape page or a sequencer page turns it on / off; it clicks while you record, and while a sequence plays on a sequencer page. Its volume is a row in SETTINGS.
Console writes /tmp/console-metro (on, volume, tempo, beats per bar, when a bar started) a few times a second while recording, and the
bridge (bridge/jackshim.c) makes the clicks in the audio, on the same clock."""
import json
import os
import time

PATH = os.environ.get("CONSOLE_METRO", "/tmp/console-metro")
SAVE = os.path.join(os.environ.get("CONSOLE_HOME", "/data/UserData/console"), "metronome.json")
STATE = {"on": False, "vol": 60, "sent": 0.0, "was": False, "count": 0}
COUNTS = [0, 1, 2, 4]                       # COUNT IN: OFF, or this many bars of clicks before a recording starts
BEAT = {"n": 0, "est": None, "bpm": 0, "bar": 0}      # the click grid: a steady bar start, and a heartbeat the bridge watches
CI = {"active": False, "end": 0.0, "start_ns": 0, "e": None, "last": -1, "patched": False}


def load():
    try:
        d = json.load(open(SAVE))
        STATE["on"], STATE["vol"] = bool(d.get("on")), max(0, min(100, int(d.get("vol", 60))))
        STATE["count"] = int(d.get("count", 0)) if int(d.get("count", 0)) in COUNTS else 0
    except (OSError, ValueError):
        pass


def save():
    try:
        json.dump({"on": STATE["on"], "vol": STATE["vol"], "count": STATE["count"]}, open(SAVE + ".tmp", "w"))
        os.replace(SAVE + ".tmp", SAVE)
    except OSError:
        pass


def _write(text):
    try:
        with open(PATH + ".tmp", "w") as f:
            f.write(text)
        os.replace(PATH + ".tmp", PATH)
    except OSError:
        pass


def _send(vol, bpm, bar, t0):
    BEAT["n"] += 1
    _write("1 %d %d %d %d %d" % (vol, round(bpm * 100), bar, t0, BEAT["n"]))


def _steady(m, bpm, bar):
    """m = a bar start worked out from the playhead just now: late by however long the loop took to get here (never early).
    Keeps one steady grid instead of moving the clicks every time: only a real jump (a seek, a new tempo) moves it."""
    bar_ns = bar * 6e10 / bpm
    est = BEAT["est"]
    if est is None or BEAT["bpm"] != bpm or BEAT["bar"] != bar:
        est = m
    else:
        k = round((m - est) / bar_ns)
        adv = est + k * bar_ns
        d = m - adv
        if abs(d) > 40e6:
            est = m
        else:
            est = adv + (d if d < 0 else 0.05 * d)         # (a late reading is noise: follow it only a little)
    BEAT["est"], BEAT["bpm"], BEAT["bar"] = est, bpm, bar
    return int(est)


def toggle(T):
    STATE["on"] = not STATE["on"]
    save()
    T.say("METRONOME %s  (CLICKS WHILE RECORDING, OR PLAYING ON A SEQUENCER PAGE, VOLUME %d%%)" % ("ON" if STATE["on"] else "OFF", STATE["vol"]), 3)


def step_count(way):
    i = COUNTS.index(STATE["count"]) if STATE["count"] in COUNTS else 0
    STATE["count"] = COUNTS[(i + way) % len(COUNTS)]
    save()


def set_volume(delta):
    STATE["vol"] = max(0, min(100, STATE["vol"] + delta))
    save()


def _patch(Engine):
    """COUNT IN: pressing record while the tape is stopped clicks the chosen number of bars first, then the recording starts."""
    CI["patched"] = True
    orig = Engine.set_recording

    def set_recording(self, on):
        if not on:
            CI["active"] = False                         # (record again, or stop, during the count: it is cancelled)
            return orig(self, on)
        if CI["active"]:                                 # record pressed again during the count: it is cancelled
            CI["active"] = False
            _write("0 0 12000 4 0")
            return
        if STATE["count"] and not self.recording and not self.playing and not CI["active"]:
            bars = STATE["count"]
            CI.update(active=True, e=self, last=-1, start_ns=time.monotonic_ns(),
                      end=time.monotonic() + bars * max(1, int(round(self.bar_beats()))) * 60.0 / self.bpm)
            return
        return orig(self, on)
    Engine.set_recording = set_recording
    CI["orig"] = orig


def _count_tick(T):
    e, now = CI["e"], time.monotonic()
    if now >= CI["end"]:
        CI["active"] = False
        _write("0 0 12000 4 0")
        CI["orig"](e, True)
        return
    bar = max(1, int(round(e.bar_beats())))
    beat = int((now - (CI["end"] - STATE["count"] * bar * 60.0 / e.bpm)) * e.bpm / 60.0)
    left = STATE["count"] * bar - beat
    if left != CI["last"]:
        CI["last"] = left
        T.say("COUNT IN  %d" % left, 2)
    if now - STATE["sent"] >= 0.2:
        STATE["sent"], STATE["was"] = now, True
        _send(max(STATE["vol"], 40), e.bpm, bar, CI["start_ns"])


def tick(T):
    """Every screen frame: keep the bridge told while recording."""
    e = T.engine
    if e is not None and not CI["patched"]:
        _patch(type(e))
    if CI["active"]:
        _count_tick(T)
        return
    seq = bool(getattr(T, "seq_page", False) and not getattr(T, "fx_page", False))      # a sequencer page: it clicks while the sequence plays too
    guitar = False                                    # GUITAR has no sequencer page: it clicks while it plays
    try:
        guitar = bool(e and e.inst_view and getattr(e.drums.get(e.slots[e.slot]), "live_input", False))
    except Exception:                                 # noqa: BLE001
        pass
    live = bool(e and STATE["on"] and e.playing and (e.recording or seq or guitar))
    now = time.monotonic()
    if not live:
        if STATE["was"]:
            STATE["was"] = False
            BEAT["est"] = None
            _write("0 0 12000 4 0")
        return
    if now - STATE["sent"] < 0.2:
        return
    STATE["sent"], STATE["was"] = now, True
    fpb = e.frames_per_beat()
    bar = max(1, int(round(e.bar_beats())))
    beats = e.pos / fpb                               # (the tape's own bars)
    if seq and not e.recording:                       # a sequencer page: the clicks follow the pattern, as the white line under the steps does
        try:
            sq = e.seqs.get(e.slots[e.slot]) if e.slot is not None else None
            if sq is not None:
                beats = (e.seq_clock + e.read_ahead - sq.anchor) / fpb      # (not _heard_frame(): that one is moved on for the screen)
        except Exception:                             # noqa: BLE001
            pass
    within = beats % bar
    t0 = _steady(time.monotonic_ns() - within * 60e9 / e.bpm, e.bpm, bar)
    _send(STATE["vol"], e.bpm, bar, t0)


def install_menu(menu_mod):
    """A METRONOME row in SETTINGS (before UPDATE): the wheel (push it first) or the arrows change the volume."""
    if "METRONOME" in menu_mod.SETTINGS:
        return
    menu_mod.SETTINGS.insert(menu_mod.SETTINGS.index("UPDATE") if "UPDATE" in menu_mod.SETTINGS else len(menu_mod.SETTINGS), "METRONOME")
    menu_mod.LABELS["METRONOME"] = "METRONOME"
    menu_mod.SETTINGS.insert(menu_mod.SETTINGS.index("METRONOME") + 1, "COUNTIN")
    menu_mod.LABELS["COUNTIN"] = "COUNT IN"
    M = menu_mod.Menu
    o_change, o_text, o_key = M.change, M.setting_text, M.settings_key

    def change(self, delta, fine=False):
        if menu_mod.SETTINGS[self.row] == "METRONOME":
            set_volume((1 if fine else 5) * (1 if delta > 0 else -1))
            self.msg = ""
            return
        if menu_mod.SETTINGS[self.row] == "COUNTIN":
            step_count(1 if delta > 0 else -1)
            self.msg = ""
            return
        o_change(self, delta, fine)

    def setting_text(self, what):
        if what == "METRONOME":
            return "%s   VOLUME %d%%   (PUSH: ON / OFF, WHEEL: VOLUME)" % ("ON" if STATE["on"] else "OFF", STATE["vol"])
        if what == "COUNTIN":
            return "OFF" if not STATE["count"] else "%d BAR%s   (CLICKS BEFORE RECORDING STARTS)" % (STATE["count"], "" if STATE["count"] == 1 else "S")
        return o_text(self, what)

    def settings_key(self, name):
        if name in menu_mod.CONFIRM and menu_mod.SETTINGS[self.row] == "METRONOME":
            STATE["on"] = not STATE["on"]               # push = on / off (the wheel is the volume)
            save()
            return
        if name in menu_mod.CONFIRM and menu_mod.SETTINGS[self.row] == "COUNTIN":
            step_count(1)
            return
        o_key(self, name)

    M.change, M.setting_text, M.settings_key = change, setting_text, settings_key
