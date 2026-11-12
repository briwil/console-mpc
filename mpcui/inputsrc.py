"""What Console's audio input is on the MPC Sample: SETTINGS > INPUT = REAR (the jacks on the back), MIC (the built-in
microphone) or USB (what a computer plays to "MPC Sample Audio").

The mic and the jacks share the one recording input (sound card 2): two of its switches pick between them, 'Builtin
Microphone Switch' and 'TRS Switch' (seen with the stock app on its mic: microphone on, TRS off). USB is its own
sound card, read by the bridge (bridge/jackshim.c) while /tmp/console-input holds "u"."""
import ctypes
import json
import os

HOME = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
FILE = os.path.join(HOME, "inputsrc.json")
FLAG = "/tmp/console-input"
LOG = os.path.join(HOME, "input-status.txt")
ROW = "INPUTSRC"
CHOICES = ["REAR", "MIC", "USB"]
STATE = {"src": "REAR"}


def load():
    try:
        with open(FILE) as fh:
            s = json.load(fh).get("src")
        if s in CHOICES:
            STATE["src"] = s
    except (OSError, ValueError, AttributeError):
        pass


def save():
    try:
        with open(FILE, "w") as fh:
            json.dump(STATE, fh)
    except OSError:
        pass


def _switch(A, ctl, name, on):
    P = ctypes.c_void_p
    eid, val = P(), P()
    A.snd_ctl_elem_id_malloc(ctypes.byref(eid))
    A.snd_ctl_elem_value_malloc(ctypes.byref(val))
    A.snd_ctl_elem_id_set_interface(eid, 2)                  # the mixer's controls
    A.snd_ctl_elem_id_set_name(eid, name.encode())
    A.snd_ctl_elem_value_set_id(val, eid)
    A.snd_ctl_elem_value_set_boolean(val, 0, 1 if on else 0)
    r = A.snd_ctl_elem_write(ctl, val)
    A.snd_ctl_elem_id_free(eid)
    A.snd_ctl_elem_value_free(val)
    return r


def apply():
    """Sets the card's switches and tells the bridge. What happened goes to console/input-status.txt."""
    src = STATE["src"]
    try:
        with open(FLAG, "w") as fh:
            fh.write("u" if src == "USB" else "c")
    except OSError:
        pass
    note = "input %s:" % src
    try:
        A = ctypes.CDLL("libasound.so.2")
        for f in ("snd_ctl_open", "snd_ctl_elem_write", "snd_ctl_close", "snd_ctl_elem_id_malloc", "snd_ctl_elem_value_malloc"):
            getattr(A, f).restype = ctypes.c_int
        for f in ("snd_ctl_elem_id_set_interface", "snd_ctl_elem_id_set_name", "snd_ctl_elem_value_set_id",
                  "snd_ctl_elem_value_set_boolean", "snd_ctl_elem_id_free", "snd_ctl_elem_value_free"):
            getattr(A, f).restype = None
        A.snd_ctl_elem_id_set_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        A.snd_ctl_elem_id_set_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        A.snd_ctl_elem_value_set_id.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        A.snd_ctl_elem_value_set_boolean.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_long]
        A.snd_ctl_elem_write.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        A.snd_ctl_elem_id_free.argtypes = [ctypes.c_void_p]
        A.snd_ctl_elem_value_free.argtypes = [ctypes.c_void_p]
        A.snd_ctl_close.argtypes = [ctypes.c_void_p]
        ctl = ctypes.c_void_p()
        r = A.snd_ctl_open(ctypes.byref(ctl), b"hw:2", 0)
        note += " open %d" % r
        if r >= 0:
            if src != "USB":                                 # (USB: the mic and the jacks stay as they are)
                note += " mic %d" % _switch(A, ctl, "Builtin Microphone Switch", src == "MIC")
                note += " trs %d" % _switch(A, ctl, "TRS Switch", src == "REAR")
            A.snd_ctl_close(ctl)
    except Exception as ex:                                  # noqa: BLE001
        note += " failed: %s" % ex
    try:
        with open(LOG, "a") as fh:
            fh.write(note + "\n")
    except OSError:
        pass


def name():
    return STATE["src"]


def install_menu(menu_mod):
    """An INPUT row in SETTINGS (before UPDATE): the wheel, the arrows or a push go through REAR / MIC / USB."""
    load()
    apply()
    if ROW in menu_mod.SETTINGS:
        return
    menu_mod.SETTINGS.insert(menu_mod.SETTINGS.index("UPDATE") if "UPDATE" in menu_mod.SETTINGS else len(menu_mod.SETTINGS), ROW)
    menu_mod.LABELS[ROW] = "INPUT"
    M = menu_mod.Menu
    o_change, o_text, o_key = M.change, M.setting_text, M.settings_key

    def step(way):
        i = CHOICES.index(STATE["src"])
        STATE["src"] = CHOICES[(i + (1 if way >= 0 else -1)) % len(CHOICES)]
        save()
        apply()

    def change(self, delta, fine=False):
        if menu_mod.SETTINGS[self.row] == ROW:
            step(delta)
            self.msg = ""
            return
        o_change(self, delta, fine)

    def setting_text(self, what):
        if what == ROW:
            return STATE["src"]
        return o_text(self, what)

    def settings_key(self, name):
        if name in menu_mod.CONFIRM and menu_mod.SETTINGS[self.row] == ROW:
            step(1)
            return
        o_key(self, name)

    M.change, M.setting_text, M.settings_key = change, setting_text, settings_key
