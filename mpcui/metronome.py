"""The metronome: Shift + TAP TEMPO on the tape page turns it on / off; it clicks while you record. Its volume is a row in SETTINGS.
Console writes /tmp/console-metro (on, volume, tempo, beats per bar, when a bar started) a few times a second while recording, and the
bridge (bridge/jackshim.c) makes the clicks in the audio, on the same clock."""
import json
import os
import time

PATH = os.environ.get("CONSOLE_METRO", "/tmp/console-metro")
SAVE = os.path.join(os.environ.get("CONSOLE_HOME", "/data/UserData/console"), "metronome.json")
STATE = {"on": False, "vol": 60, "sent": 0.0, "was": False}


def load():
    try:
        d = json.load(open(SAVE))
        STATE["on"], STATE["vol"] = bool(d.get("on")), max(0, min(100, int(d.get("vol", 60))))
    except (OSError, ValueError):
        pass


def save():
    try:
        json.dump({"on": STATE["on"], "vol": STATE["vol"]}, open(SAVE + ".tmp", "w"))
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


def toggle(T):
    STATE["on"] = not STATE["on"]
    save()
    T.say("METRONOME %s  (CLICKS WHILE RECORDING, VOLUME %d%%)" % ("ON" if STATE["on"] else "OFF", STATE["vol"]), 3)


def set_volume(delta):
    STATE["vol"] = max(0, min(100, STATE["vol"] + delta))
    save()


def tick(T):
    """Every screen frame: keep the bridge told while recording."""
    e = T.engine
    live = bool(e and STATE["on"] and e.recording and e.playing)
    now = time.monotonic()
    if not live:
        if STATE["was"]:
            STATE["was"] = False
            _write("0 0 12000 4 0")
        return
    if now - STATE["sent"] < 0.2:
        return
    STATE["sent"], STATE["was"] = now, True
    fpb = e.frames_per_beat()
    bar = max(1, int(round(e.bar_beats())))
    beats = e.pos / fpb
    within = beats % bar
    t0 = time.monotonic_ns() - int(within * 60e9 / e.bpm)
    _write("1 %d %d %d %d" % (STATE["vol"], round(e.bpm * 100), bar, t0))


def install_menu(menu_mod):
    """A METRONOME row in SETTINGS (before UPDATE): the wheel (push it first) or the arrows change the volume."""
    if "METRONOME" in menu_mod.SETTINGS:
        return
    menu_mod.SETTINGS.insert(menu_mod.SETTINGS.index("UPDATE") if "UPDATE" in menu_mod.SETTINGS else len(menu_mod.SETTINGS), "METRONOME")
    menu_mod.LABELS["METRONOME"] = "METRONOME"
    M = menu_mod.Menu
    o_change, o_text, o_key = M.change, M.setting_text, M.settings_key

    def change(self, delta, fine=False):
        if menu_mod.SETTINGS[self.row] == "METRONOME":
            set_volume((1 if fine else 5) * (1 if delta > 0 else -1))
            self.msg = ""
            return
        o_change(self, delta, fine)

    def setting_text(self, what):
        if what == "METRONOME":
            return "%s %d%%  (SHIFT + TAP TEMPO: ON / OFF, CLICKS WHILE RECORDING)" % ("ON" if STATE["on"] else "OFF", STATE["vol"])
        return o_text(self, what)

    def settings_key(self, name):
        if name in menu_mod.CONFIRM and menu_mod.SETTINGS[self.row] == "METRONOME":
            self.editing = not self.editing
            return
        o_key(self, name)

    M.change, M.setting_text, M.settings_key = change, setting_text, settings_key
