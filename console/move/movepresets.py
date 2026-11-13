"""The PRESETS page: the first sound page of a synth.

    the wheel        through the presets: yours (saved with Menu > SAVE PRESET, marked *) first, then the
                     synth's own, then Console's (pi-app/presets/<synth>/, marked +); each heard as you land on it
    push the wheel   keep it
    Back             the sound you had before you started turning
    knob 1           the synth's bank (OB-Xd, Dexed and others with more than one)
    Left / Right     the other pages (what you landed on is kept)
"""
import json
import os
import time

import kitmenu

PAGE = "PRESETS"
OURS = os.path.join(os.path.dirname(os.path.abspath(kitmenu.__file__)), "presets")    # Console's own (make_presets.py)
NAME_WAIT = 0.25                        # the synth needs a moment after a preset before its name is read


class Presets:
    def __init__(self, T, kits):
        self.T = T
        self.kits = kits                # the Menu's presets (kitmenu.KitMenu): for loading yours in full
        self.pos = 0
        self.orig = None                # the sound before you started turning (Back puts it back)
        self.landed = 0.0
        self.names = {}                 # (machine, bank, n) -> name, as they're read
        self.mine = []
        self.ours = []
        self._seen = None

    # ------------------------------------------------------------ what's shown
    def d(self):
        e = self.T.engine
        return e.drums if e else None

    def for_synth(self):
        """Has this instrument a PRESETS page? (every synth)"""
        e = self.T.engine
        d = self.d()
        return bool(d and e.is_synth(d.machine) and hasattr(d, "has_presets"))

    def on_page(self):
        T = self.T
        if not (T.drum_page and not (T.seq_page or T.fx_page or T.inst_page or T.song_page) and self.for_synth()):
            return False
        if T.mlfo.active():
            return False
        pages = T.drum_pages()
        return bool(pages) and pages[min(T.drum_tab, len(pages) - 1)][0] == PAGE

    def builtin(self):
        d = self.d()
        return d.preset_count() if d.has_presets() else 0

    def total(self):
        return len(self.mine) + self.builtin() + len(self.ours)

    def _ours_path(self, i):
        """i: a place in the list; Console's own preset there, or None."""
        k = i - len(self.mine) - self.builtin()
        if 0 <= k < len(self.ours):
            return os.path.join(OURS, self.d().machine, self.ours[k] + ".json")
        return None

    def sync(self):
        """Coming to the page (or another synth): the list, and where its current sound is in it."""
        d = self.d()
        key = (d.machine, d.bank() if d.has_presets() else 0)
        self.mine = kitmenu.kit_names(d.machine)
        try:
            self.ours = sorted((f[:-5] for f in os.listdir(os.path.join(OURS, d.machine)) if f.endswith(".json")),
                               key=str.lower)
        except OSError:
            self.ours = []
        if self._seen != key and self.orig is None:
            self.pos = len(self.mine) + (d.preset_now() if d.has_presets() else 0)
            self.pos = max(0, min(self.total() - 1, self.pos))
        self._seen = key

    def label(self, i):
        d = self.d()
        if i < len(self.mine):
            return "* " + self.mine[i].upper()
        if self._ours_path(i):
            return "+ " + self.ours[i - len(self.mine) - self.builtin()].upper()
        n = i - len(self.mine)
        bank = d.bank()
        key = (d.machine, bank, n)
        if key not in self.names and i == self.pos and time.monotonic() - self.landed > NAME_WAIT \
                and d.preset_now() == n:
            nm = d.preset_name()
            if nm:
                self.names[key] = nm
        return "%d %s" % (n + 1, self.names.get(key, "")) if key in self.names else "%d" % (n + 1)

    def bank_label(self):
        d = self.d()
        banks = d.banks() if d.has_presets() else []
        if len(banks) < 2:
            return None
        b = d.bank()
        lab = next((l for l, ix in banks if ix == b), banks[0][0])
        return lab.rsplit(".", 1)[0] if lab.lower().endswith((".syx", ".fxb", ".bin")) else lab

    # ------------------------------------------------------------ controls
    def _begin(self):
        if self.orig is None:
            self.orig = list(self.d().kit())

    def _apply(self):
        d = self.d()
        self.landed = time.monotonic()
        path = kitmenu.kit_path(self.mine[self.pos], d.machine) if self.pos < len(self.mine) else self._ours_path(self.pos)
        if path:
            try:
                with open(path) as f:
                    d.load_kit(list(json.load(f)["values"]))
            except (OSError, ValueError, KeyError, TypeError):
                self.T.say("COULDN'T READ THAT PRESET", 2)
        else:
            d.set_preset(self.pos - len(self.mine))

    def turn(self, step):
        self.sync()
        n = self.total()
        if not n:
            self.T.say("NO PRESETS: MENU > SAVE PRESET MAKES ONE", 2)
            return
        new = max(0, min(n - 1, self.pos + (1 if step > 0 else -1)))
        if new == self.pos:
            return
        self._begin()
        self.pos = new
        self._apply()

    def keep(self):
        """Push the wheel: keep it (yours: in full, with its inserts, as Menu > LOAD PRESET)."""
        if self.orig is None:
            return
        if self.pos < len(self.mine):
            self.kits.kits = list(self.mine)
            self.kits.pick = self.pos
            self.kits.load()
        else:
            self.T.say("PRESET: %s" % self.label(self.pos).split(" ", 1)[-1].upper(), 2)   # (already playing it)
        self._done()

    def leave(self):
        """Off the page while trying them: what you landed on stays."""
        if self.orig is not None:
            self._done()

    def _done(self):
        self.orig = None
        e = self.T.engine
        with e.lock:
            e.dirty.add(-1)                         # the song keeps the sound

    def back(self):
        """Back: the sound before you started turning. False when there's nothing to put back."""
        if self.orig is None:
            return False
        self.d().load_kit(self.orig)
        self.orig = None
        self._seen = None
        self.sync()
        self.T.say("BACK TO YOUR SOUND", 2)
        return True

    def knob(self, number, delta):
        """Knob 1: the bank."""
        d = self.d()
        if number != 1 or not d.has_presets():
            return
        banks = d.banks()
        if len(banks) < 2:
            return
        import knobgate
        way = knobgate.gate(("preset-bank",), delta, False)
        if not way:
            return
        idx = [ix for _l, ix in banks]
        b = d.bank()
        at = idx.index(b) if b in idx else 0
        nb = idx[max(0, min(len(idx) - 1, at + way))]
        if nb == b:
            return
        self._begin()
        d.set_bank(nb)
        self.pos = len(self.mine)                   # its first preset (the bank loads it)
        self.landed = time.monotonic()
        self._seen = (d.machine, nb)
