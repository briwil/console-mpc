"""The GUITAR instrument needs the jacks on the back (REAR, left and right): while an instrument slot holds GUITAR the input is
forced to REAR; when the last GUITAR is gone the input goes back to what SETTINGS > INPUT says."""
import inputsrc

N = {"n": 0}


def _sync():
    inputsrc.FORCE = "REAR" if N["n"] > 0 else None
    inputsrc.apply()


def install(instruments):
    S = instruments.Slot
    if getattr(S, "_guitar_in", False):
        return
    S._guitar_in = True
    o_init, o_remove = S.__init__, S.remove

    def is_guitar(m):
        return bool(getattr(m, "live_input", False))

    def init(self, core, machine, k=None):
        o_init(self, core, machine, k)
        if is_guitar(machine):
            self._guitar_on = True
            N["n"] += 1
            _sync()

    def remove(self):
        o_remove(self)
        if getattr(self, "_guitar_on", False):
            self._guitar_on = False
            N["n"] = max(0, N["n"] - 1)
            _sync()

    S.__init__, S.remove = init, remove
