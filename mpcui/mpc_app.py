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
    import menu as _menu
    import metronome
    metronome.load()
    metronome.install_menu(_menu)        # SETTINGS gets a METRONOME row (its volume)
except Exception:
    import traceback
    print("metronome is off:\n" + traceback.format_exc(), flush=True)
try:
    import menu as _menu2
    import sequencer as _seq2
    import notes as _notes2
    import freerec
    freerec.load()
    freerec.install(_seq2.Sequencer, _notes2.NoteSequencer, _seq2)   # recording into a sequencer keeps your timing (the steps' NUDGE)
    freerec.install_menu(_menu2)                                     # SETTINGS > REC TIMING: FREE / GRID
    import nolink
    nolink.install(_menu2)                                           # SETTINGS > SYNC: no Link on the MPC
    import inputsrc
    inputsrc.install_menu(_menu2)                                    # SETTINGS > INPUT: REAR / MIC / USB
    import nobigscreen
    nobigscreen.install(_menu2)                                      # no extended screen (web page) and no EXTERNAL SCREEN row
    import insertfx as _insfx_mod
    import insertsafe
    insertsafe.install(_insfx_mod)                                   # closing an insert effect waits for the sound core (no heap damage under load)
except Exception:
    import traceback
    print("free recording is off:\n" + traceback.format_exc(), flush=True)
try:
    import audio
    import redo
    redo.install(audio.Engine)           # PLUS on the tape page: REDO (Console only has UNDO)
    import memtrim
    memtrim.install(audio)               # freed memory goes back to the system (after a project opens, and every 2 minutes)
    import freshempty
    freshempty.install(audio)            # a brand-new project (first start) has empty instrument slots, not the LXR-02 in slot 1
    import sequencer as _sequencer
    redo.install_seq(_sequencer.Sequencer)   # ... and Shift + PLUS on a sequencer page
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


# the stress test (Console's own, move/stress.py): `echo 60 > /data/UserData/console/stress`. It has to pick its own data folder
# before anything reads CONSOLE_DATA, so it is asked here, before app.py is loaded.
_STRESS = None
try:
    import stress as _stress
    _STRESS = _stress.prepare()
    if _STRESS:
        import stressmem
        stressmem.install(_stress)        # the report says where the memory is (in use / held free / Python), every 2 minutes
except Exception:
    import traceback
    print("stress test is off:\n" + traceback.format_exc(), flush=True)
try:
    import namescan
    if not _STRESS:
        import leakhunt
        namescan.prepare() or leakhunt.prepare()      # tools/scan-names.sh: every synth's preset names; tools/leak-hunt.sh: which instrument or effect keeps memory (each in its own empty project folder)
except Exception:
    import traceback
    print("preset name scan is off:\n" + traceback.format_exc(), flush=True)
# run app.py as a module (not __main__: its main() is called below), put the wrapper in where main() looks for handle
G = runpy.run_path(APP_PY, run_name="console_app")
if _STRESS:
    G["main"].__globals__["STRESS_MINUTES"] = _STRESS      # (where main() looks it up)
main = G["main"]
try:
    import padhello
    padhello.install(main.__globals__)                   # start-up on the pads: 2 seconds of random colours (no HELLO letters)
except Exception:
    import traceback
    print("pad start-up is off:\n" + traceback.format_exc(), flush=True)
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
            for path in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "preset-names.json"), _names_file):
                try:                                     # the names that come with Console (read once by namescan.py), then yours
                    with open(path) as fh:
                        for key, nm in json.load(fh).items():
                            m, b, n = key.split("|")
                            self.names[(m, int(b), int(n))] = nm
                except Exception:
                    pass

        def _p_label2(self, i):
            try:                                         # a synth whose presets are a menu: every name is known at once
                d = self.d()
                pi = d.preset_info or {}
                n = i - len(self.mine)
                if pi.get("menu") and n >= 0 and (d.machine, d.bank(), n) not in self.names:
                    opts = d.params[d.preset_param()]["options"]
                    if n < len(opts):
                        self.names[(d.machine, d.bank(), n)] = str(opts[n]).title()
            except Exception:
                pass
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
    import pages as _pages
    _input_parts = _pages.input_parts

    def _input_parts2(e, c):
        who, what = _input_parts(e, c)
        if who == "MOVE INPUT":                                        # (this isn't a Move: what SETTINGS > INPUT is on)
            try:
                import inputsrc as _is
                who = _is.name() + " INPUT"
            except Exception:
                who = "INPUT"
        return who, what
    _pages.input_parts = _input_parts2
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
_handle = song_after_punch(G["handle"])
try:
    import presetpop
    _handle = presetpop.wrap(_handle)                    # PRESETS: a box, and the list pops up when you push the wheel
except Exception:
    import traceback
    print("presets list is off:\n" + traceback.format_exc(), flush=True)
try:
    import movelfo as _movelfo
    import lfo as _lfo
    import lfodest
    lfodest.install(_movelfo, _lfo)                      # the LFO's DEST names the drum: "SNR DECAY"
except Exception:
    import traceback
    print("LFO drum names are off:\n" + traceback.format_exc(), flush=True)
try:
    import moveseq as _moveseq
    import movesynth as _movesynth
    import sequencer as _sequencer
    import padvel
    padvel.install(G["MoveBoard"], _moveseq.MoveSeq, _movesynth.MoveSynth, _sequencer.Sequencer, G.get("pad_velocity"))   # steps from the pads keep the pad's velocity
except Exception:
    import traceback
    print("pad velocity on steps is off:\n" + traceback.format_exc(), flush=True)
    try:
        import padvel
        padvel.log("INSTALL FAILED: " + traceback.format_exc().replace("\n", " | ")[-600:])
    except Exception:
        pass
try:
    import shiftknobs
    _handle = shiftknobs.wrap(_handle)                   # Shift + K1-K3 / FADER = knobs 5-8 on an instrument's pages; no fine steps there
except Exception:
    import traceback
    print("Shift + knobs is off:\n" + traceback.format_exc(), flush=True)
main.__globals__["handle"] = _handle
main()
