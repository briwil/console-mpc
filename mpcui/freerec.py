"""Recording into a sequencer keeps your timing: a hit still lands on the nearest step, and the step's NUDGE is set to how early
or late you played it (a drum step: 10% of a step at a time; a synth note: 1%), up to half a step either way. SETTINGS > REC TIMING
switches between FREE (as played) and GRID (snapped to the steps, Console's own way). Console's files are not changed."""
import json
import os

SAVE = os.path.join(os.environ.get("CONSOLE_HOME", "/data/UserData/console"), "rectiming.json")
STATE = {"free": True}
ROW = "RECTIMING"


def load():
    try:
        STATE["free"] = bool(json.load(open(SAVE)).get("free", True))
    except (OSError, ValueError):
        pass


def save():
    try:
        json.dump({"free": STATE["free"]}, open(SAVE + ".tmp", "w"))
        os.replace(SAVE + ".tmp", SAVE)
    except OSError:
        pass


def _off_step(tape_frame, anchor, step_frames):
    """(the step's count, how far from it the hit was: -0.5 .. 0.5 of a step)"""
    x = (tape_frame - anchor) / step_frames
    k = round(x)
    return k, x - k


def install(Sequencer, NoteSequencer, sequencer):
    drum_place, note_place = Sequencer.live_place, NoteSequencer.live_place
    nudges = [int(v.rstrip("%")) for v in sequencer.COMPONENTS["nudge"]]

    def live_place(self, lane, tape_frame, frames_per_beat):
        i = drum_place(self, lane, tape_frame, frames_per_beat)
        if not STATE["free"]:
            return i
        with self.lock:
            ln = self.lane(lane)
            k, off = _off_step(tape_frame, self.anchor, frames_per_beat / self.spb(ln))
            n = max(-50, min(50, int(round(off * 10)) * 10))
            comp = ln.steps[i].comp
            if n in nudges:
                comp["nudge"] = nudges.index(n)
            else:
                comp.pop("nudge", None)                          # on the beat
            comp.pop("nudge_c", None)
            self._skip.add((lane, k))                            # you've just played it: not again this time round
        return i

    def note_live_place(self, note, tape_frame, frames_per_beat, *a, **kw):
        i = note_place(self, note, tape_frame, frames_per_beat, *a, **kw)
        if not STATE["free"]:
            return i
        with self.lock:
            p = self.pattern
            k, off = _off_step(tape_frame, self.anchor, frames_per_beat / (p.steps_per_beat(note) * self._tf()))
            try:
                p.notes[i][note].nudge = max(-50, min(50, int(round(off * 100))))
            except (KeyError, AttributeError):
                pass
            self._skip.add((note, k))
        return i

    Sequencer.live_place, NoteSequencer.live_place = live_place, note_live_place


def install_menu(menu_mod):
    """A REC TIMING row in SETTINGS (before UPDATE): the wheel, the arrows or a push switch FREE / GRID."""
    if ROW in menu_mod.SETTINGS:
        return
    menu_mod.SETTINGS.insert(menu_mod.SETTINGS.index("UPDATE") if "UPDATE" in menu_mod.SETTINGS else len(menu_mod.SETTINGS), ROW)
    menu_mod.LABELS[ROW] = "REC TIMING"
    M = menu_mod.Menu
    o_change, o_text, o_key = M.change, M.setting_text, M.settings_key

    def flip():
        STATE["free"] = not STATE["free"]
        save()

    def change(self, delta, fine=False):
        if menu_mod.SETTINGS[self.row] == ROW:
            flip()
            self.msg = ""
            return
        o_change(self, delta, fine)

    def setting_text(self, what):
        if what == ROW:
            return "FREE  (SEQUENCER RECORDING KEEPS YOUR TIMING)" if STATE["free"] else "GRID  (SEQUENCER RECORDING SNAPS TO THE STEPS)"
        return o_text(self, what)

    def settings_key(self, name):
        if name in menu_mod.CONFIRM and menu_mod.SETTINGS[self.row] == ROW:
            flip()
            return
        o_key(self, name)

    M.change, M.setting_text, M.settings_key = change, setting_text, settings_key
