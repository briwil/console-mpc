"""SETTINGS > SCREEN REC: records the screen, the sound and every control you touch, for making videos.

Hidden until you hold Shift on the SETTINGS page; then the row stays for the rest of the session.
Turn the wheel right for ON, left for OFF; a push switches it either way. While it is on, the row shows how long it has been recording.

The recording itself is done by the bridge (bridge/screenrec.h): this only tells it where to write, through the file
/tmp/console-rec (its text is the folder). Each recording is a folder on the card:
    <card>/ConsoleRecordings/<date>_<time>/   screen.cvr, audio.wav, controls.txt, timing.txt
It sits next to ConsoleData, not in it, so the internal-drive backup of ConsoleData doesn't fill up with video.
tools/screenrec-convert.py (on a Mac) turns a folder into frames + audio + an After Effects script.
"""
import os
import time

ROW = "SCREENREC"
CTL = "/tmp/console-rec"
STATE = {"on": False, "since": 0.0, "dir": ""}


def _base():
    data = os.environ.get("CONSOLE_DATA", "")
    if data and os.path.basename(data.rstrip("/")) == "ConsoleData":
        return os.path.join(os.path.dirname(data.rstrip("/")), "ConsoleRecordings")      # on the card, next to ConsoleData
    return "/data/UserData/console/recordings"                                             # no card: the internal drive


def start():
    d = os.path.join(_base(), time.strftime("%Y-%m-%d_%H%M%S"))
    try:
        os.makedirs(d, exist_ok=True)
        with open(CTL + ".new", "w") as f:
            f.write(d + "\n")
        os.replace(CTL + ".new", CTL)
    except OSError as e:
        print("screen rec: can't start: %s" % e, flush=True)
        return False
    STATE.update(on=True, since=time.monotonic(), dir=d)
    print("screen rec: on, %s" % d, flush=True)
    return True


def stop():
    try:
        os.remove(CTL)
    except OSError:
        pass
    if STATE["on"]:
        print("screen rec: off, %s" % STATE["dir"], flush=True)
    STATE.update(on=False)


def text():
    if not STATE["on"]:
        return "OFF"
    s = int(time.monotonic() - STATE["since"])
    return "REC %d:%02d" % (s // 60, s % 60)


def tick(T, menu, on_settings, menu_mod):
    """Every screen update: Shift held on SETTINGS reveals the row."""
    if on_settings and ROW not in menu_mod.SETTINGS:
        try:
            if T.shift_held():
                menu_mod.SETTINGS.append(ROW)
        except Exception:
            pass


def install(menu_mod):
    stop()                                                    # (a file left by a Console that ended without stopping)
    menu_mod.LABELS[ROW] = "SCREEN REC"
    M = menu_mod.Menu
    o_change, o_text, o_key = M.change, M.setting_text, M.settings_key

    def toggle(self):
        if STATE["on"]:
            stop()
            self.say("SAVED TO " + os.path.basename(os.path.dirname(STATE["dir"])) + "/" + os.path.basename(STATE["dir"]))
        elif start():
            self.say("RECORDING SCREEN, SOUND AND CONTROLS")
        else:
            self.say("CAN'T WRITE TO THE CARD")

    def change(self, delta, fine=False):
        if menu_mod.SETTINGS[self.row] == ROW:
            if (delta > 0) != STATE["on"]:                # turning right switches it on, left off (a fast turn doesn't flip it back and forth)
                toggle(self)
            return
        o_change(self, delta, fine)

    def setting_text(self, what):
        if what == ROW:
            return text()
        return o_text(self, what)

    def settings_key(self, name):
        if name in menu_mod.CONFIRM and menu_mod.SETTINGS[self.row] == ROW:
            toggle(self)
            return
        o_key(self, name)

    M.change, M.setting_text, M.settings_key = change, setting_text, settings_key
