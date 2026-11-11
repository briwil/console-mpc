"""Starts Console on the MPC Sample with its native 320 x 240 screens (mpcui/native.py) laid over Console's own pages.
Console's files are not changed: this adds the same search paths app.py does, wraps pages.draw, then runs app.py."""
import os
import runpy
import sys
try:                                  # `kill -USR1 <pid>` writes where every thread is into the log (to find out where a freeze sits)
    import faulthandler
    import signal
    faulthandler.register(signal.SIGUSR1, all_threads=True)
except Exception:
    pass

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
try:
    import audio
    import redo
    redo.install(audio.Engine)           # PLUS on the tape page: REDO (Console only has UNDO)
except Exception:
    import traceback
    print("redo is off:\n" + traceback.format_exc(), flush=True)
try:
    import sf2link
    sf2link.sync()                    # soundfonts on the SD card (sf2 folder) or in the samples: SF2 SYNTH sees them
except Exception:
    pass


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
        from_song = name == "DRUMS" and bool(getattr(T, "song_page", False)) and not (m.open or m.kits.open)
        handle(name, T, m, e)
        try:
            if from_song and T.inst_page and not T.drum_page:
                T.instp.mode = None                      # from the song page: not the instrument picker ...
                eng = T.engine
                if eng is not None and eng.slot is not None and eng.slots[eng.slot]:
                    T.instp.row = eng.slot
                    T.instp.open()                       # ... but the last instrument's sound page
            elif name == "DRUMS" and T.inst_page and T.instp.mode == "pick" and not T.drum_page:
                T.instp.mode = None
        except Exception:
            import traceback
            print("leave song failed:\n" + traceback.format_exc(), flush=True)
    return wrapped


# run app.py as a module (not __main__: its main() is called below), put the wrapper in where main() looks for handle
G = runpy.run_path(APP_PY, run_name="console_app")
main = G["main"]
try:
    import stepentry
    stepentry.install(G["MoveBoard"], G.get("pad_velocity"))
    import native as _native
    try:                                                 # built-in preset names are only read from a synth once you land on
        import json                                      # them: remember them, so the list fills in and stays filled
        import movepresets
        _P = movepresets.Presets
        _names_file = os.path.join(C, "data", "preset-names.json")
        _p_init, _p_label = _P.__init__, _P.label

        def _p_init2(self, *a, **k):
            _p_init(self, *a, **k)
            try:
                with open(_names_file) as fh:
                    for key, nm in json.load(fh).items():
                        m, b, n = key.split("|")
                        self.names[(m, int(b), int(n))] = nm
            except Exception:
                pass

        def _p_label2(self, i):
            before = len(self.names)
            out = _p_label(self, i)
            if len(self.names) != before:
                try:
                    with open(_names_file, "w") as fh:
                        json.dump({"%s|%s|%s" % k: v for k, v in self.names.items()}, fh)
                except Exception:
                    pass
            return out
        _P.__init__, _P.label = _p_init2, _p_label2
    except Exception as ex:
        print("preset name memory is off:", ex, flush=True)
    import pagefx as _pagefx
    _label = _pagefx.label

    def _label2(T):
        name = _label(T)
        return "INSTRUMENTS" if name == "INSTRUMENT SELECTION" else name        # the page-change card's name for the list
    _pagefx.label = _label2
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
