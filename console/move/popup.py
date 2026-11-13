"""A step setting's popup on the external (phone) screen: which step, the setting, its value, big in the middle,
for a couple of seconds. The Move's own screen gets the same as a line of text (T.say)."""
import time

SECONDS = 2.0
_n = [0]


def show(T, top, label, value="", hint="", seconds=SECONDS):
    _n[0] += 1
    T.popup = {"id": _n[0], "top": top, "label": label, "value": str(value), "hint": hint}
    T.popup_until = time.monotonic() + seconds
    T.say("  ".join(x for x in (top, label, str(value), "(%s)" % hint if hint else "") if x), seconds)


def current(T):
    p = getattr(T, "popup", None)
    return p if p and time.monotonic() < getattr(T, "popup_until", 0) else None
