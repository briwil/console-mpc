"""The stress test's report (Console's move/stress.py), with where the memory is: every 2 minutes, after a MEMORY line,

       in use 412.3 MB  held free 96.0 MB  python 251344 objects  (most more since the start: dict +5210, list +3100 ...)

    in use      memory asked for and not given back: if this is what climbs, something keeps it (a leak, or a list that
                only grows)
    held free   memory given back but still held in pieces: if this climbs instead, nothing is lost, it's only spread out
    python      Console's own Python objects, and the kinds there are most more of since the test began"""
import gc
import sys

EVERY = 4                   # MEMORY lines (one per 30 seconds) per breakdown
_n = [0]
_first = [None]


def _kinds():
    out = {}
    for o in gc.get_objects():
        k = type(o).__name__
        out[k] = out.get(k, 0) + 1
    return out


def line():
    import leakhunt
    used, free = leakhunt.malloc_totals()
    kinds = _kinds()
    if _first[0] is None:
        _first[0] = kinds
    more = sorted(((n - _first[0].get(k, 0), k) for k, n in kinds.items()), reverse=True)[:5]
    grow = ", ".join("%s %+d" % (k, d) for d, k in more if d > 50)
    mb = lambda v: "?" if v is None else "%.1f MB" % (v / 1048576.0)
    return "   in use %s  held free %s  python %d objects%s" % (mb(used), mb(free), sys.getallocatedblocks(),
                                                             ("  (most more since the start: %s)" % grow) if grow else "")


def install(stress_mod):
    orig = stress_mod.Stress.memory

    def memory(self, now):
        orig(self, now)
        try:
            _n[0] += 1
            if _n[0] % EVERY == 1:
                self.say(line())
        except Exception as ex:                              # noqa: BLE001
            self.say("   (no breakdown: %s)" % ex)
    stress_mod.Stress.memory = memory
