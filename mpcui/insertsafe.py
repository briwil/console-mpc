"""Safer closing of an insert effect.

Console's Insert.unload() tells the sound core to let go of the effect, sleeps about three audio blocks (8 ms) and
frees it. Under heavy load (many effects, the CPU near its limit) the sound core can still be inside the effect after
8 ms, and freeing it then corrupts the heap: the stress test died with "malloc(): mismatching next->prev_size" while
closing an effect. Here, after letting go, we wait until the sound core has finished 3 whole cycles (core.cycles()),
and only then free it. If the core isn't running (the counter doesn't move), we give up waiting after half a second."""
import time

NEED_CYCLES = 3
GIVE_UP = 0.5          # seconds


def wait_for_core(core, need=NEED_CYCLES, give_up=GIVE_UP):
    """True once the core has run `need` cycles since now (or False if it didn't within `give_up`)."""
    try:
        start = core.cycles()
    except Exception:
        return False
    end = time.monotonic() + give_up
    while time.monotonic() < end:
        if ((core.cycles() - start) & 0xFFFFFFFF) >= need:
            return True
        time.sleep(0.002)
    return False


def install(insertfx_mod):
    Insert = insertfx_mod.Insert

    def unload(self):
        if self.core is not None:
            self.core.set_slot_insert(self.slot, self.pos, 0, 0)
            if self.h:
                wait_for_core(self.core)
        if self.h and self.lib:
            self.lib.sh_fx_close(self.h)
        self.h, self.params, self.values = None, [], {}

    Insert.unload = unload
