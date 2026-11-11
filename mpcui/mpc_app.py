"""Starts Console on the MPC Sample with its native 320 x 240 screens (mpcui/native.py) laid over Console's own pages.
Console's files are not changed: this adds the same search paths app.py does, wraps pages.draw, then runs app.py."""
import os
import runpy
import sys

C = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
APP_PY = os.path.join(C, "move", "app.py")
sys.path[:0] = [os.path.join(C, "tools", "sim", "stubs"), os.path.join(C, "pi-app"), os.path.join(C, "move"),
                os.path.dirname(os.path.abspath(__file__))]
os.environ.setdefault("CONSOLE_PLATFORM", "move")
try:
    import pygame
    pygame.init()
    import pages
    import native
    native.install(pages)
except Exception:
    import traceback
    print("native screens are off:\n" + traceback.format_exc(), flush=True)
sys.argv[0] = APP_PY


def song_after_punch(handle):
    """Left button 1 goes round an instrument's pages (sound, sequencer, automation, punch FX); on the MPC the SONG page
    comes after punch FX (left button 2 is the mixer there). Console's own files are not changed."""
    def wrapped(name, T, m, e):
        try:
            if (name == "DRUMS" and not (m.open or m.kits.open) and T.drum_page and not T.fx_page and T.seq_page
                    and getattr(T, "auto_page", False) not in (False, True, None)):
                handle("DRUMS", T, m, e)                 # the original: punch FX done, the sound page again ...
                handle("SONG", T, m, e)                  # ... and straight on to the song page
                return
        except Exception:
            import traceback
            print("song page step failed:\n" + traceback.format_exc(), flush=True)
        handle(name, T, m, e)
        try:
            if name == "DRUMS" and T.inst_page and T.instp.mode == "pick" and not T.drum_page:
                T.instp.mode = None                      # from the song page: the INSTRUMENTS list, not the instrument picker
        except Exception:
            pass
    return wrapped


# run app.py as a module (not __main__: its main() is called below), put the wrapper in where main() looks for handle
G = runpy.run_path(APP_PY, run_name="console_app")
main = G["main"]
try:
    import stepentry
    stepentry.install(G["MoveBoard"], G.get("pad_velocity"))
    import native as _native
    _orig_note = G["MoveBoard"].note

    def _note(self, num, val):
        if 0 <= num < 8:
            _native.set_touch(num, bool(val))             # knob-mode pads: a held pad = that knob touched
        _orig_note(self, num, val)
    G["MoveBoard"].note = _note
except Exception:
    import traceback
    print("step entry is off:\n" + traceback.format_exc(), flush=True)
main.__globals__["handle"] = song_after_punch(G["handle"])
main()
